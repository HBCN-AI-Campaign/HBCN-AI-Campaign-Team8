import hashlib
import hmac
import ipaddress
import secrets
import time
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

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
UI_SESSION_COOKIE = "rag_ui_session"
UI_SESSION_MAX_AGE = 8 * 60 * 60
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".html", ".htm", ".csv", ".json", ".mmd",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
}


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _ui_session_signature(payload: str) -> str:
    key = hashlib.sha256(f"hbcn-rag-ui:{settings.SERVICE_TOKEN}".encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _valid_ui_session(value: str | None) -> bool:
    if not settings.SERVICE_TOKEN or not value:
        return False
    try:
        issued_at, nonce, signature = value.split(".", 2)
        timestamp = int(issued_at)
    except (ValueError, TypeError):
        return False
    age = int(time.time()) - timestamp
    payload = f"{issued_at}.{nonce}"
    return 0 <= age <= UI_SESSION_MAX_AGE and hmac.compare_digest(
        signature,
        _ui_session_signature(payload),
    )


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    return origin == f"{request.url.scheme}://{host}"


def require_service_token(
    request: Request,
    authorization: str | None = Header(default=None),
    rag_ui_session: str | None = Cookie(default=None),
) -> None:
    if not settings.SERVICE_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SERVICE_TOKEN 尚未配置")
    expected = f"Bearer {settings.SERVICE_TOKEN}"
    if authorization is not None and secrets.compare_digest(authorization, expected):
        return
    client_host = request.client.host if request.client else ""
    if (
        _valid_ui_session(rag_ui_session)
        and _is_loopback(client_host)
        and _same_origin(request)
    ):
        return
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
        configured_scopes = ["business_rules", "project_design", "law"]
    else:
        configured = False
        configured_scopes = []
    return Capabilities(
        engine=kind,
        retrieval=configured,
        document_ingestion=configured,
        supported_scopes=configured_scopes,
        max_upload_bytes=settings.MAX_UPLOAD_BYTES,
        upload_timeout_seconds=settings.UPLOAD_TIMEOUT_SECONDS,
        supported_file_extensions=sorted(ALLOWED_EXTENSIONS),
    )


_QUERY_SCOPES = ("business_rules", "project_design", "law")


def _retrieve_evidence(query: str, scope: str, top_k: int) -> list[dict]:
    """按 scope 检索；scope 为 ``all`` 时合并默认范围并去重排序。"""
    if scope == "all":
        merged: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item_scope in _QUERY_SCOPES:
            for chunk in get_engine().retrieve(query=query, scope=item_scope, top_k=top_k):
                key = (str(chunk.get("document_id") or ""), str(chunk.get("content") or ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(chunk)
        merged.sort(key=lambda item: item.get("similarity") or 0.0, reverse=True)
        return merged[:top_k]
    return get_engine().retrieve(query=query, scope=scope, top_k=top_k)


@app.post("/api/v1/query", response_model=QueryResponse, dependencies=[Depends(require_service_token)])
def query(payload: QueryRequest):
    if payload.scope == "task_documents":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "此范围需先完成任务级权限过滤",
        )
    try:
        chunks = _retrieve_evidence(payload.query, payload.scope, payload.top_k)
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
    scope: str = Form("business_rules"),
    file: UploadFile = File(...),
):
    if scope not in ("business_rules", "project_design", "law"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "当前只接受业务规则、项目设计或法规资料")
    filename = file.filename or "document"
    extension = filename[filename.rfind("."):].lower() if "." in filename else ""
    if filename.startswith(".") or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持该文件类型")
    try:
        content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(content) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过上传大小限制")
        document_ids = await run_in_threadpool(
            get_engine().upload,
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
                    "run": doc.get("run"),
                    "chunk_count": doc.get("chunk_count"),
                })
        return {"engine": "ragflow", "documents": documents}
    return {"engine": "none", "documents": []}


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_UI_BUILD_DIR = _STATIC_DIR / "ui-build"
app.mount(
    "/ui/assets",
    StaticFiles(directory=_UI_BUILD_DIR / "assets", check_dir=False),
    name="rag-ui-assets",
)


@app.get("/ui", include_in_schema=False)
@app.get("/ui/", include_in_schema=False)
def trial_ui(request: Request):
    """Serve the local UI and issue a short-lived, HttpOnly browser session."""
    client_host = request.client.host if request.client else ""
    if not _is_loopback(client_host):
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    built_index = _UI_BUILD_DIR / "index.html"
    index_path = built_index if built_index.exists() else _STATIC_DIR / "workbench.html"
    response = FileResponse(index_path) if index_path == built_index else HTMLResponse(
        index_path.read_text(encoding="utf-8")
    )
    if settings.SERVICE_TOKEN:
        payload = f"{int(time.time())}.{secrets.token_urlsafe(18)}"
        response.set_cookie(
            UI_SESSION_COOKIE,
            f"{payload}.{_ui_session_signature(payload)}",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/api/v1",
            max_age=UI_SESSION_MAX_AGE,
        )
    return response
