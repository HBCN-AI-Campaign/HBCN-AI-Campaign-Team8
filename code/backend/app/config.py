"""应用配置。

默认使用 SQLite（零依赖，开箱即跑），切换 PostgreSQL 只需在 .env 设置：
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/loan_review
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# backend/ 目录绝对路径，保证 SQLite 文件位置与启动 cwd 无关
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE = f"sqlite:///{_BACKEND_DIR / 'loan_review.db'}"


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


settings = Settings()
