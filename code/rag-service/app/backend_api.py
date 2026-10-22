from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from .answer_graph import build_answer_graph
from .config import settings
from .engine import engine_kind, get_engine
from .postgres_engine import SUPPORTED_EXTENSIONS
from .runtime_client import SDKRuntime
from .schemas import AnswerResponse, RetrievalResponse
from .evidence_context import utf16_units
from .legal_applicability import LegalContext
from .graph_transport import GraphRun
from .document_store import DocumentConflict
from .document_quality import QualityReview
from .reference_security import ReferenceForbidden, resolve_principal
from .web_context import WebSnapshot, WebContextSource


router = APIRouter(prefix="/api/v1")
answer_slots = threading.BoundedSemaphore(4)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def runtime_character_limit(cls, value):
        if utf16_units(value) > 4000:
            raise ValueError("会话内容超过 SDK 的 4000 UTF-16 字符限制")
        return value


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: Literal["all", "business_rules", "project_design", "law"] = "all"
    top_k: int = Field(default=5, ge=1, le=8)
    conversation: list[ConversationMessage] = Field(default_factory=list, max_length=12)
    sources: list[Literal["knowledge_base", "pkulaw", "web_context"]] = Field(default_factory=lambda: ["knowledge_base"], min_length=1, max_length=3)
    web_context: list[WebSnapshot] = Field(default_factory=list, max_length=4)
    purpose: Literal["reference", "case_assessment"] = "reference"
    legal_context: LegalContext | None = None

    @model_validator(mode="after")
    def source_scope(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("来源不能重复")
        if "pkulaw" in self.sources and self.scope not in {"all", "law"}:
            raise ValueError("北大法宝仅用于 law/all 范围，不能扩展当前知识范围")
        if bool(self.web_context) != ("web_context" in self.sources):
            raise ValueError("网页上下文须显式选择来源并提交实际文本快照")
        if sum(len(item.text.encode()) for item in self.web_context) > 160000:
            raise ValueError("网页上下文超过 160000 UTF-8 字节预算，不能静默截断")
        if len({(item.url, item.captured_at, item.text) for item in self.web_context}) != len(self.web_context):
            raise ValueError("网页快照不能重复提交")
        return self

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
        fully_ready = runtime_ready and resources.get("unverified_ready_documents", 0) == 0
        return JSONResponse(status_code=200 if fully_ready else 503, content={
            "status": "ready" if fully_ready else "degraded", "engine": engine_kind(),
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


class DocumentWithdrawal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: Literal["superseded", "incorrect", "authorization_revoked", "quality_issue", "other"]


def document_reviewer(x_document_review_key: str | None = Header(default=None)):
    if not settings.RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE:
        raise HTTPException(404, "文档质量复核接口未开放")
    return resolve_principal(x_document_review_key, settings.RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE)


@router.get("/documents/{document_id}/quality")
def document_quality(document_id: str, actor=Depends(document_reviewer)):
    engine = postgres_engine()
    row = engine.documents.get(valid_uuid(document_id))
    if not row or row["state"] == "withdrawn":
        raise HTTPException(404, "文档不存在或不可用")
    try:
        actor.require(row["scope"], "reviewer")
    except ReferenceForbidden:
        raise HTTPException(403, "无权复核此知识范围") from None
    return {"document": engine.documents.public(row), "pages": row["pages"],
            "notice": "解析结果尚需与原件逐单元核对，质量复核不构成法规或业务审批"}


@router.post("/documents/{document_id}/quality-review", status_code=202)
def review_document_quality(document_id: str, payload: QualityReview, actor=Depends(document_reviewer)):
    try:
        document = postgres_engine().review_quality(valid_uuid(document_id), payload, actor)
    except LookupError:
        raise HTTPException(404, "文档不存在") from None
    except ReferenceForbidden:
        raise HTTPException(403, "无权复核此知识范围") from None
    except DocumentConflict:
        raise HTTPException(409, "状态、内容或复核范围不匹配，请重新核对") from None
    return {"document": document}


class QualityRecheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/documents/{document_id}/quality-recheck", status_code=202)
def recheck_document_quality(document_id: str, payload: QualityRecheck, actor=Depends(document_reviewer)):
    try:
        document = postgres_engine().recheck_quality(valid_uuid(document_id), payload.expected_sha256, actor)
    except LookupError:
        raise HTTPException(404, "文档不存在") from None
    except ReferenceForbidden:
        raise HTTPException(403, "无权重检此知识范围") from None
    except DocumentConflict:
        raise HTTPException(409, "文档版本或重检状态不匹配") from None
    return {"document": document}


@router.post("/documents/{document_id}/withdraw")
def withdraw_document(document_id: str, payload: DocumentWithdrawal):
    try:
        document = postgres_engine().withdraw(valid_uuid(document_id), **payload.model_dump())
    except LookupError:
        raise HTTPException(404, "文档不存在") from None
    except DocumentConflict:
        raise HTTPException(409, "文档版本不匹配，请重新核对") from None
    return JSONResponse(content=jsonable_encoder({"document": document}),
                        headers={"Cache-Control": "no-store"})


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
    if not row or row["state"] == "withdrawn" or not engine.documents.original_path(document_id).is_file():
        raise HTTPException(404, "原件不存在")
    is_pdf = Path(row["name"]).suffix.lower() == ".pdf"
    return FileResponse(
        engine.documents.original_path(document_id), filename=row["name"],
        media_type="application/pdf" if is_pdf else "application/octet-stream",
        content_disposition_type="inline" if is_pdf else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Cache-Control": "no-store"},
    )


def answer_state(payload):
    return {**payload.model_dump(exclude={"web_context"}), "attempts": 0, "warnings": []}


@router.post("/answers", response_model=AnswerResponse)
async def answer(payload: AnswerRequest, request: Request, web_key: str | None = Header(default=None, alias="X-Web-Context-Key")):
    return await graph_response(payload, request, generate_answer=True, web_key=web_key)


@router.post("/retrievals", response_model=RetrievalResponse)
async def enhanced_retrieval(payload: AnswerRequest, request: Request, web_key: str | None = Header(default=None, alias="X-Web-Context-Key")):
    """Return original evidence after query planning; never generate an answer."""
    return await graph_response(payload, request, generate_answer=False, web_key=web_key)


async def start_graph(payload, *, generate_answer=True, stream=False, web_key=None):
    web_source = (WebContextSource(payload.web_context, scope=payload.scope, key=web_key)
                  if payload.web_context else None)
    engine = await run_in_threadpool(postgres_engine)
    graph = build_answer_graph(engine, generate_answer=generate_answer, web_source=web_source)
    if not answer_slots.acquire(blocking=False):
        raise HTTPException(429, "当前检索请求较多，请稍后重试")
    return GraphRun(graph, answer_state(payload), answer_slots, stream=stream)


async def graph_response(payload, request, *, generate_answer, web_key=None):
    run = await start_graph(payload, generate_answer=generate_answer, web_key=web_key)
    try:
        while True:
            if await request.is_disconnected():
                raise HTTPException(499, "请求已断开")
            event = await run.next()
            if event is None:
                raise HTTPException(503, "本轮请求未返回完整结果")
            kind, data = event
            if kind == "result":
                return data
            if kind == "error":
                raise HTTPException(503, data["message"])
    finally:
        run.cancel()


class GraphStreamingResponse(StreamingResponse):
    """Cancel even if ASGI fails before entering the event generator."""

    def __init__(self, content, run):
        self.run = run
        super().__init__(content, media_type="text/event-stream",
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.run.cancel()


@router.post("/answers/stream")
async def answer_stream(payload: AnswerRequest, web_key: str | None = Header(default=None, alias="X-Web-Context-Key")):
    run = await start_graph(payload, stream=True, web_key=web_key)

    async def events():
        try:
            while True:
                event = await run.next()
                if event is None:
                    break
                kind, data = event
                if kind != "pending":
                    yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            run.cancel()

    return GraphStreamingResponse(events(), run)
