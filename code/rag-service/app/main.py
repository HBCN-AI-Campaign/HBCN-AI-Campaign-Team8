import json
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse

from .config import settings
from .embedding import EmbeddingError
from .engine import engine_kind, get_engine
from .local_store import LocalVectorStore
from .ragflow import (
    DATASET_SETTINGS,
    RAGFlowClient,
    RAGFlowError,
    RAGFlowNotConfiguredError,
)
from .schemas import Capabilities, Evidence, IndexResponse, QueryRequest, QueryResponse

app = FastAPI(title="HBCN Business Knowledge Service", version="0.1.0")
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".html", ".htm", ".csv", ".json", ".mmd",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
}


def require_service_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.SERVICE_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SERVICE_TOKEN 尚未配置")
    expected = f"Bearer {settings.SERVICE_TOKEN}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "服务凭证无效")


@app.get("/health")
def health():
    return {"status": "ok", "service": "hbcn-rag-service"}


@app.get("/api/v1/capabilities", response_model=Capabilities, dependencies=[Depends(require_service_token)])
def capabilities():
    kind = engine_kind()
    if kind == "ragflow":
        client = RAGFlowClient()
        configured_scopes = []
        for scope in DATASET_SETTINGS:
            try:
                client.dataset_id(scope)
            except RAGFlowError:
                continue
            configured_scopes.append(scope)
        configured = bool(configured_scopes)
    elif kind == "local":
        configured = True
        configured_scopes = ["business_rules", "project_design"]
    else:
        configured = False
        configured_scopes = []
    return Capabilities(
        engine=kind,
        retrieval=configured,
        document_ingestion=configured,
        supported_scopes=configured_scopes,
    )


@app.post("/api/v1/query", response_model=QueryResponse, dependencies=[Depends(require_service_token)])
def query(payload: QueryRequest):
    if payload.scope in ("task_documents", "law"):
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "此范围需先完成任务级权限过滤或法规 MCP 授权接入",
        )
    try:
        chunks = get_engine().retrieve(
            query=payload.query,
            scope=payload.scope,
            top_k=payload.top_k,
        )
    except RAGFlowNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (RAGFlowError, EmbeddingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    evidence = [
        Evidence(
            content=str(chunk.get("content", "")),
            document_id=chunk.get("document_id"),
            document_name=chunk.get("document_keyword"),
            page=chunk.get("page_num"),
            score=chunk.get("similarity"),
            metadata=chunk,
        )
        for chunk in chunks
    ]
    warnings = [] if evidence else ["没有检索到证据；不应据此生成确定性审核结论"]
    return QueryResponse(query=payload.query, scope=payload.scope, evidence=evidence, warnings=warnings)


@app.post("/api/v1/documents", response_model=IndexResponse, dependencies=[Depends(require_service_token)])
async def index_document(
    scope: str = Form(...),
    file: UploadFile = File(...),
):
    if scope not in ("business_rules", "project_design"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "当前只接受业务规则或项目设计资料")
    filename = file.filename or "document"
    extension = filename[filename.rfind("."):].lower() if "." in filename else ""
    if filename.startswith(".") or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持该文件类型")
    try:
        content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(content) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过上传大小限制")
        document_ids = get_engine().upload(
            scope=scope,
            filename=filename,
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
    except RAGFlowNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (RAGFlowError, EmbeddingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return IndexResponse(
        status="processing",
        scope=scope,
        document_ids=document_ids,
        message="文件已提交解析与索引",
    )


@app.get("/api/v1/documents", dependencies=[Depends(require_service_token)])
def list_documents():
    """列出已入库文档（供试用 UI 展示）。"""
    kind = engine_kind()
    if kind == "local":
        return {"engine": "local", "documents": LocalVectorStore().list_documents()}
    if kind == "ragflow":
        client = RAGFlowClient()
        documents: list[dict[str, object]] = []
        for scope in DATASET_SETTINGS:
            try:
                docs = client.list_documents(scope=scope)
            except RAGFlowError:
                continue
            for doc in docs:
                documents.append({
                    "id": str(doc.get("id") or ""),
                    "name": doc.get("name"),
                    "scope": scope,
                    "created_at": doc.get("create_time"),
                })
        return {"engine": "ragflow", "documents": documents}
    return {"engine": "none", "documents": []}


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/ui", include_in_schema=False)
@app.get("/ui/", include_in_schema=False)
def trial_ui():
    """本地试用页：服务端注入 SERVICE_TOKEN，免手动粘贴（仅本地试用，生产勿暴露）。"""
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    index = index.replace("__SERVICE_TOKEN__", json.dumps(settings.SERVICE_TOKEN))
    return HTMLResponse(index)
