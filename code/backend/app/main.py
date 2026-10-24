"""FastAPI 应用入口。

启动：
    cd backend
    uvicorn app.main:app --reload
文档：http://127.0.0.1:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .config import SAMPLE_PDF_DIR as _SAMPLE_PDF_DIR
from .config import UPLOAD_DIR as _UPLOAD_DIR
from .database import Base, engine
from .routers import auth, customers, tasks
from .seed import seed as _seed

# 统一日志级别，使各模块 log.info（含 OCR 调用过程）可见
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表（首次部署按新 ORM/schema 创建全部表）→ 种子数据
    Base.metadata.create_all(bind=engine)
    _seed()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# 允许前端 mockup（file:// 或本地静态服务器）跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(tasks.router)

# 静态托管样本 PDF —— 前端 pdfjs 据此拉取原件做预览/高亮
if _SAMPLE_PDF_DIR.is_dir():
    app.mount("/pdf", StaticFiles(directory=str(_SAMPLE_PDF_DIR)), name="pdf")

# 静态托管经办人上传的真实 PDF —— 前端经 /uploads/<批次>/<文件名> 预览/高亮
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/api/rule-check/health")
def rule_check_health():
    """探测对方规则核对服务状态，供前端/运维确认当前核对走对方还是本地引擎。"""
    from . import rule_check_client

    configured = rule_check_client.configured()
    ready = rule_check_client.health(force=True) if configured else False
    return {
        "configured": configured,
        "base_url": settings.RULE_CHECK_BASE_URL or None,
        "ready": ready,
        # 当前规则核对实际使用的来源
        "active_source": "remote" if ready else "local",
    }
