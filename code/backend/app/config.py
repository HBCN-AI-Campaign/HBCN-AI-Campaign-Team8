"""应用配置。

数据库：
  - 默认 SQLite（零依赖，开箱即跑）。
  - 生产/比赛环境切 PostgreSQL（阿里云 RDS PG16，需从队内 ECS 内网连接）：
    在 backend/.env 设置（勿把真实密码提交进仓库）：
        DATABASE_URL=postgresql+psycopg2://<user>:<pass>@pgm-xxx.rwlb.rds.aliyuncs.com:5432/<db>
    连接池：账号连接上限 30，应用池建议 5–10（见 DB_POOL_SIZE / DB_MAX_OVERFLOW）。

规则核对服务（对方同事提供）：
  - RULE_CHECK_BASE_URL 指向对方的规则核对 API。
  - 核对前先探 {RULE_CHECK_BASE_URL}{RULE_CHECK_HEALTH_PATH}；ready 才调用，
    否则回退到本地内置 rule_engine。
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
    # 连接池（仅 PostgreSQL 生效；SQLite 自动忽略）。账号上限 30 → 应用池建议 5–10。
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_PRE_PING: bool = True   # 长连接失效（RDS 断线）自动重连，避免偶发 500

    # --- JWT 鉴权（权限雏形）---
    JWT_SECRET: str = "change-me-in-production-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # --- 应用 ---
    APP_NAME: str = "境外贷款单据智能审核平台 · API"
    DEBUG: bool = True

    # --- OCR 服务 ---
    # 本地开发时在 .env 里设置为服务器地址；部署到同台服务器后默认值直接可用
    OCR_BASE_URL: str = "http://127.0.0.1:7888"

    # --- 规则核对服务（对方同事）---
    # 对方 API 根地址；留空表示未配置 → 直接走本地内置 rule_engine。
    RULE_CHECK_BASE_URL: str = ""
    RULE_CHECK_HEALTH_PATH: str = "/health"   # GET，200 且（可选）body.status in {ok,ready,up}
    RULE_CHECK_PATH: str = "/rule_check"      # POST，提交 task 字段，返回核对结果
    RULE_CHECK_TIMEOUT: float = 30.0          # 单次核对超时（秒）
    RULE_CHECK_HEALTH_TIMEOUT: float = 3.0    # health 探测超时（秒），探测要快


settings = Settings()
