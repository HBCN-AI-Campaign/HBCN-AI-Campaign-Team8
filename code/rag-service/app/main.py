import hashlib
import hmac
import ipaddress
import secrets
import time
from contextlib import asynccontextmanager
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
from .database import ResourceError
from .runtime_client import RuntimeErrorResponse
from .version import API_CONTRACT_VERSION, SERVICE_VERSION
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(application):
    if engine_kind() == "postgres":
        try:
            engine = await run_in_threadpool(get_engine)
            await run_in_threadpool(engine.documents.recover_interrupted)
        except Exception:
            application.state.startup_error = "数据库初始化失败，请检查 /api/v1/ready"
    yield

app = FastAPI(title="HBCN Business Knowledge Service", version=SERVICE_VERSION, lifespan=lifespan)
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


def require_local_ui_session(request: Request) -> None:
    """Additional guard for explicitly enabled local operator actions.

    A service Bearer or proxy forwarding header is never sufficient. The local
    workbench is an operator surface, not a production user identity provider.
    """
    host = request.client.host if request.client else ""
    if (not _is_loopback(host)
        or not _is_loopback(request.url.hostname or "")
        or not _valid_ui_session(request.cookies.get(UI_SESSION_COOKIE))
        or not _same_origin(request)
        or request.headers.get("sec-fetch-site") == "cross-site"):
        raise HTTPException(401, "需要有效的本机工作台会话")


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
    return {"status": "ok", "service": "hbcn-rag-service", "service_version": SERVICE_VERSION,
            "api_contract_version": API_CONTRACT_VERSION}


class ContractIdentityMiddleware:
    """Pure ASGI wrapper: preserve receive/disconnect and streaming semantics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def versioned_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                    (b"x-rag-service-version", SERVICE_VERSION.encode()),
                    (b"x-rag-contract-version", API_CONTRACT_VERSION.encode())]}
                if scope.get("path", "").startswith("/api/v1/"):
                    message["headers"] = [(key, value) for key, value in message["headers"] if key.lower() != b"cache-control"]
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)
        await self.app(scope, receive, versioned_send)


app.add_middleware(ContractIdentityMiddleware)


@app.get("/api/v1/capabilities", response_model=Capabilities, dependencies=[Depends(require_service_token)])
def capabilities(request: Request = None):
    kind = engine_kind()
    supported_extensions = ALLOWED_EXTENSIONS
    if kind == "postgres":
        from .postgres_engine import SUPPORTED_EXTENSIONS

        supported_extensions = SUPPORTED_EXTENSIONS
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
    elif kind in {"local", "postgres"}:
        configured = True
        configured_scopes = ["business_rules", "project_design", "law"]
    else:
        configured = False
        configured_scopes = []
    review_scopes, review_subject = [], None
    if request is not None and kind == "postgres" and settings.RAG_UI_DOCUMENT_REVIEW_KEY.get_secret_value():
        from .backend_api import local_ui_reviewer
        try:
            actor = local_ui_reviewer(request)
            if "reviewer" in actor.roles:
                review_scopes = sorted(actor.namespaces & {"law", "business_rules", "project_design"})
                review_subject = actor.subject
        except HTTPException:
            pass
    return Capabilities(
        workbench_contract_version=1 if kind == "postgres" else 0,
        engine=kind,
        retrieval=configured,
        document_ingestion=configured,
        agentic_orchestration=kind == "postgres",
        answer_generation=kind == "postgres",
        document_source=kind == "postgres",
        enhanced_retrieval=kind == "postgres",
        external_law_mcp=kind == "postgres" and settings.PKULAW_MCP_ENABLED and bool(settings.PKULAW_MCP_TOKEN.get_secret_value()),
        dedicated_reranking=kind == "postgres" and settings.RAG_RERANK_PROVIDER != "disabled" and bool(settings.RAG_RERANK_URL and settings.RAG_RERANK_MODEL),
        web_context=kind == "postgres" and settings.RAG_WEB_CONTEXT_ENABLED and bool(settings.RAG_WEB_CONTEXT_PRINCIPALS_FILE and settings.RAG_WEB_CONTEXT_ALLOWED_HOSTS),
        document_quality_review_scopes=review_scopes,
        document_quality_review_subject=review_subject,
        supported_scopes=configured_scopes,
        max_upload_bytes=settings.MAX_UPLOAD_BYTES,
        upload_timeout_seconds=settings.UPLOAD_TIMEOUT_SECONDS,
        supported_file_extensions=sorted(supported_extensions),
    )


_QUERY_SCOPES = ("business_rules", "project_design", "law")


def _retrieve_evidence(query: str, scope: str, top_k: int) -> list[dict]:
    """按 scope 检索；scope 为 ``all`` 时合并默认范围并去重排序。"""
    if engine_kind() == "postgres":
        return get_engine().retrieve(query=query, scope=scope, top_k=top_k)
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
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "检索引擎尚未配置，请检查服务就绪状态") from None
    except (RAGFlowError, EmbeddingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "检索依赖调用失败，请稍后重试") from None

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
        engine = get_engine()
        document_ids = await run_in_threadpool(
            engine.upload,
            scope=scope,
            filename=filename,
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
    except RAGFlowNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "检索引擎尚未配置，请检查服务就绪状态") from None
    except (RAGFlowError, EmbeddingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "文档处理依赖调用失败，请稍后重试") from None
    return IndexResponse(
        status="ready" if getattr(engine, "synchronous_upload_ready", False) else "processing",
        scope=scope,
        document_ids=document_ids,
        message="文件已完成解析与索引" if getattr(engine, "synchronous_upload_ready", False) else "文件已提交解析与索引",
    )


@app.get("/api/v1/documents", dependencies=[Depends(require_service_token)])
def list_documents():
    """列出已入库文档（供试用 UI 展示）。"""
    kind = engine_kind()
    if kind == "postgres":
        return {"engine": "postgres", "documents": get_engine().documents.list()}
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


@app.exception_handler(ResourceError)
@app.exception_handler(SQLAlchemyError)
@app.exception_handler(RuntimeErrorResponse)
def resource_failure(request, exc):
    return JSONResponse(status_code=503, content={"detail": "依赖服务暂不可用或处理队列已满，请检查服务就绪状态后重试"})


@app.exception_handler(EmbeddingError)
def embedding_failure(request, exc):
    return JSONResponse(status_code=502, content={"detail": "向量服务调用失败，请稍后重试"})


from .backend_api import router as backend_router

app.include_router(backend_router, dependencies=[Depends(require_service_token)])

from .reference_api import router as reference_router

app.include_router(reference_router, dependencies=[Depends(require_service_token)])


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
    response = FileResponse(built_index) if built_index.exists() else HTMLResponse(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>知识库工作台未就绪</title>"
        "<p>React 工作台尚未构建，请由部署人员构建 UI 资源后重试。</p></html>", status_code=503,
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
