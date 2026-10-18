"""FastAPI 应用入口。

启动：
    cd backend
    uvicorn app.main:app --reload
文档：http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, tasks


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
app.include_router(tasks.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
