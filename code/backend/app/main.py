"""FastAPI 应用入口。

启动：
    cd backend
    uvicorn app.main:app --reload
文档：http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .config import SAMPLE_PDF_DIR as _SAMPLE_PDF_DIR
from .config import UPLOAD_DIR as _UPLOAD_DIR
from .database import Base, engine
from .routers import assistant, auth, customers, tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表（POC 阶段用 create_all；生产应改用 Alembic 迁移）
    Base.metadata.create_all(bind=engine)
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
app.include_router(assistant.router)

# 静态托管样本 PDF —— 前端 pdfjs 据此拉取原件做预览/高亮
if _SAMPLE_PDF_DIR.is_dir():
    app.mount("/pdf", StaticFiles(directory=str(_SAMPLE_PDF_DIR)), name="pdf")

# 静态托管经办人上传的真实 PDF —— 前端经 /uploads/<批次>/<文件名> 预览/高亮
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
