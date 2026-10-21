from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
from starlette.concurrency import run_in_threadpool

from .answer_graph import build_answer_graph
from .config import settings
from .database import ResourceError
from .embedding import EmbeddingError
from .engine import engine_kind, get_engine
from .postgres_engine import SUPPORTED_EXTENSIONS
from .runtime_client import RuntimeErrorResponse, SDKRuntime
from .schemas import AnswerResponse


router = APIRouter(prefix="/api/v1")
answer_slots = threading.BoundedSemaphore(4)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: Literal["all", "business_rules", "project_design", "law"] = "all"
    top_k: int = Field(default=5, ge=1, le=8)
    conversation: list[ConversationMessage] = Field(default_factory=list, max_length=12)

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value):
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


def postgres_engine():
    if engine_kind() != "postgres":
        raise HTTPException(503, "此接口需要 PostgreSQL 引擎，请检查服务配置")
    return get_engine()


def valid_uuid(value):
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(404, "文档或片段不存在") from None


@router.get("/ready")
def ready():
    try:
        resources = postgres_engine().readiness()
        runtime_ready = SDKRuntime().health()
        return JSONResponse(status_code=200 if runtime_ready else 503, content={
            "status": "ready" if runtime_ready else "degraded", "engine": engine_kind(),
            **resources, "sdk_runtime": "ready" if runtime_ready else "unavailable",
            "note": "就绪检查不产生模型费用；模型调用由上传与问答真实验收验证",
        })
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "message": "数据库或向量检索尚未就绪，请检查资源配置"})


@router.post("/ingestions", status_code=202)
async def ingest(
    file: UploadFile = File(...), scope: Literal["business_rules", "project_design", "law"] = Form("business_rules"),
    source_url: str = Form(""), jurisdiction: str = Form("", max_length=100),
):
    filename = file.filename or ""
    if Path(filename).name.startswith(".") or Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, "当前支持 PDF、DOCX、XLSX、文本、HTML 或常见图片，请转换旧版 Office 文件")
    provenance = {}
    if source_url:
        try:
            parsed_url = HttpUrl(source_url)
            if parsed_url.username or parsed_url.password:
                raise ValueError("来源地址不能含凭证")
            provenance["original_url"] = str(parsed_url)
        except ValueError:
            raise HTTPException(422, "来源地址必须是有效的 HTTP/HTTPS 地址") from None
    if jurisdiction:
        provenance["jurisdiction"] = jurisdiction
    if scope == "law":
        provenance["validity_review"] = "未核验当前效力和完整附件，需业务/法律人员复核适用范围"
    try:
        content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(422, "文件为空")
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件超过上传大小限制")
    engine = await run_in_threadpool(postgres_engine)
    document, created = await run_in_threadpool(
        engine.submit, scope=scope, filename=filename, content=content,
        content_type=file.content_type or "application/octet-stream", provenance=provenance,
    )
    return {"document": document, "created": created, "status_url": f"/api/v1/documents/{document['id']}"}


@router.get("/documents/{document_id}")
def document_status(document_id: str):
    engine = postgres_engine()
    row = engine.documents.get(valid_uuid(document_id))
    if not row:
        raise HTTPException(404, "文档不存在")
    return engine.documents.public(row)


@router.post("/documents/{document_id}/retry", status_code=202)
def retry_document(document_id: str):
    return {"document": postgres_engine().retry(valid_uuid(document_id))}


@router.get("/documents/{document_id}/content")
def document_content(document_id: str, chunk_id: str | None = Query(default=None)):
    try:
        result = postgres_engine().content(valid_uuid(document_id), valid_uuid(chunk_id) if chunk_id else None)
    except LookupError:
        raise HTTPException(404, "片段不属于该文档或不存在") from None
    if result is None:
        raise HTTPException(404, "文档不存在")
    return result


@router.get("/documents/{document_id}/source")
def document_source(document_id: str):
    engine = postgres_engine()
    row = engine.documents.get(valid_uuid(document_id))
    if not row or not engine.documents.original_path(document_id).is_file():
        raise HTTPException(404, "原件不存在")
    is_pdf = Path(row["name"]).suffix.lower() == ".pdf"
    return FileResponse(
        engine.documents.original_path(document_id), filename=row["name"],
        media_type="application/pdf" if is_pdf else "application/octet-stream",
        content_disposition_type="inline" if is_pdf else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Cache-Control": "no-store"},
    )


def answer_state(payload):
    return {**payload.model_dump(), "attempts": 0, "warnings": []}


@router.post("/answers", response_model=AnswerResponse)
def answer(payload: AnswerRequest):
    engine = postgres_engine()
    if not answer_slots.acquire(blocking=False):
        raise HTTPException(429, "当前问答请求较多，请稍后重试")
    try:
        return build_answer_graph(engine).invoke(answer_state(payload), {"recursion_limit": 10})["result"]
    finally:
        answer_slots.release()


@router.post("/answers/stream")
def answer_stream(payload: AnswerRequest):
    engine = postgres_engine()
    if not answer_slots.acquire(blocking=False):
        raise HTTPException(429, "当前问答请求较多，请稍后重试")

    def events():
        try:
            graph = build_answer_graph(engine)
            for mode, update in graph.stream(answer_state(payload), {"recursion_limit": 10}, stream_mode=["custom", "updates"]):
                if mode == "custom":
                    yield f"event: step\ndata: {json.dumps(update, ensure_ascii=False)}\n\n"
                elif "generate" in update:
                    yield f"event: result\ndata: {json.dumps(update['generate']['result'], ensure_ascii=False)}\n\n"
        except (RuntimeErrorResponse, EmbeddingError, ResourceError):
            yield 'event: error\ndata: {"message":"检索或生成服务暂不可用，请稍后重试；本次未完成回答"}\n\n'
        except Exception:
            yield 'event: error\ndata: {"message":"问答未完成，请检查服务状态或稍后重试"}\n\n'
        finally:
            answer_slots.release()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
