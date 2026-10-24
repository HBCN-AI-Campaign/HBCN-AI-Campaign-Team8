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
from .routers import auth, customers, tasks
from .seed import seed as _seed


def _migrate(eng):
    """为旧版数据库补齐新增列（兼容 SQLite / PostgreSQL）。"""
    from sqlalchemy import inspect, text

    inspector = inspect(eng)
    if "review_tasks" not in inspector.get_table_names():
        return  # 表还没建，create_all 会完整建，不需要补列
    existing = {col["name"] for col in inspector.get_columns("review_tasks")}
    pending = [
        ("needs_recheck",   "BOOLEAN DEFAULT FALSE"),
        ("review_comment",  "TEXT"),
        ("supplement_note", "TEXT"),
        ("submitted_by",    "INTEGER"),
    ]
    with eng.begin() as conn:
        for col, definition in pending:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE review_tasks ADD COLUMN {col} {definition}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 补列（老库升级）→ 建表（首次部署）
    _migrate(engine)
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
