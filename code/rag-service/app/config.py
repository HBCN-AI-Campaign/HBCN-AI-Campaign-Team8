from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_TOKEN: str = ""
    BUSINESS_SOURCE_ROOT: str = ""

    # --- 正式检索底座：RAGFlow ---
    RAG_ENGINE: Literal["ragflow", "local", "postgres", "auto"] = "auto"
    RAGFLOW_BASE_URL: str = ""
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_BUSINESS_RULES_DATASET_ID: str = ""
    RAGFLOW_PROJECT_DESIGN_DATASET_ID: str = ""
    RAGFLOW_BUSINESS_RULES_DATASET_NAME: str = "hbcn-team8-business-rules"
    RAGFLOW_PROJECT_DESIGN_DATASET_NAME: str = "hbcn-team8-project-design"
    RAGFLOW_LANGUAGE: str = "Chinese"
    RAGFLOW_PARSER_ID: str = "general"
    REQUEST_TIMEOUT_SECONDS: float = 60.0
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024
    UPLOAD_TIMEOUT_SECONDS: int = 900
    PARSE_POLL_INTERVAL_SECONDS: float = 5.0
    PARSE_POLL_TIMEOUT_SECONDS: float = 900.0

    # --- 本地试运行引擎：百炼 Embedding + SQLite 向量库 + OCR ---
    # 未配置 RAGFLOW 时生效；便于在无 Docker 的机器上先跑通查询/入库/UI。
    BAILIAN_BASE_URL: str = ""          # OpenAI 兼容地址，如 https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
    BAILIAN_API_KEY: str = ""
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding-flash"
    LOCAL_STORE_PATH: str = "rag_store.sqlite3"   # 相对 rag-service 根目录
    OCR_BASE_URL: str = "http://127.0.0.1:8001"   # 队友 ocr_demo 服务（code/ocr_demo）
    OCR_TIMEOUT_SECONDS: float = 300.0
    OCR_VISION_MODEL: str = "qwen3.8-flash"       # OCR 服务不可用时，图片走百炼视觉兜底
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 80

    RAG_DATABASE_URL: SecretStr = SecretStr("")
    RAG_DATABASE_RESOURCE_FILE: str = ""
    RAG_SSH_RESOURCE_FILE: str = ""
    RAG_SSH_HOST_KEY_SHA256: str = ""
    RAG_POSTGRES_SSLMODE: Literal["require", "verify-full", "disable"] = "require"
    RAG_DATABASE_SCHEMA: str = "hbcn_rag"
    RAG_VECTOR_TABLE: str = "chunks_v1"
    EMBEDDING_DIMENSIONS: int = Field(default=1024, ge=1, le=2000)
    RAG_DATA_DIR: str = "data"
    RAG_MAX_DOCUMENT_PAGES: int = Field(default=500, ge=1, le=2000)
    RAG_MAX_TEXT_CHARS: int = Field(default=2_000_000, ge=1000)
    RAG_RETRIEVAL_MIN_SCORE: float = Field(default=0.35, ge=0, le=1)
    RAG_MAX_CONCURRENT_JOBS: int = Field(default=2, ge=1, le=8)
    ASSISTANT_RUNTIME_URL: str = ""
    ASSISTANT_RUNTIME_TOKEN: SecretStr = SecretStr("")
    ASSISTANT_RUNTIME_RESOURCE_FILE: str = ""
    RAG_ANSWER_TIMEOUT_SECONDS: float = Field(default=90, ge=5, le=240)


settings = Settings()
