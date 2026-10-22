"""应用配置。

默认使用 SQLite（零依赖，开箱即跑），切换 PostgreSQL 只需在 .env 设置：
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/loan_review
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# backend/ 目录绝对路径，保证 SQLite 文件位置与启动 cwd 无关
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE = f"sqlite:///{_BACKEND_DIR / 'loan_review.db'}"

# 样本 PDF（随仓库分发） / 上传件（运行时落盘）目录
SAMPLE_PDF_DIR = _BACKEND_DIR / "sample_pdfs"
UPLOAD_DIR = _BACKEND_DIR / "uploads"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- 数据库 ---
    # POC 默认 SQLite（放在 backend/ 下）；生产改为 postgresql+psycopg2://...
    DATABASE_URL: str = _DEFAULT_SQLITE

    # --- JWT 鉴权（权限雏形）---
    JWT_SECRET: str = "change-me-in-production-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # --- 应用 ---
    APP_NAME: str = "境外贷款单据智能审核平台 · API"
    DEBUG: bool = True

    # --- AI assistant runtime ---
    # Provider credentials live only in the isolated OpenCode runtime.
    AI_REQUEST_TIMEOUT: float = 45.0
    # Internal Bun service hosting the OpenCode SDK. Keep this on the private network.
    ASSISTANT_RUNTIME_URL: str = ""
    ASSISTANT_RUNTIME_TOKEN: str = ""

    # --- RAG 服务（独立 hbcn-rag-service，见 code/rag-service，默认端口 8010）---
    # 主项目通过 app/rag_service.py 适配层调用该独立知识库服务；未配置时助手回退本地证据。
    RAG_BASE_URL: str = ""          # 例如 http://127.0.0.1:8010
    RAG_SERVICE_TOKEN: str = ""     # 与 rag-service/.env 的 SERVICE_TOKEN 保持一致
    # Enhanced RAG has a bounded 240s internal budget; allow transport headroom.
    RAG_REQUEST_TIMEOUT: float = 300.0


settings = Settings()
