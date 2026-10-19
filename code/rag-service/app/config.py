from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_TOKEN: str = ""
    BUSINESS_SOURCE_ROOT: str = ""

    # --- 正式检索底座：RAGFlow ---
    RAGFLOW_BASE_URL: str = ""
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_BUSINESS_RULES_DATASET_ID: str = ""
    RAGFLOW_PROJECT_DESIGN_DATASET_ID: str = ""
    RAGFLOW_BUSINESS_RULES_DATASET_NAME: str = "hbcn-team8-business-rules"
    RAGFLOW_PROJECT_DESIGN_DATASET_NAME: str = "hbcn-team8-project-design"
    RAGFLOW_LANGUAGE: str = "Chinese"
    RAGFLOW_CHUNK_METHOD: str = "naive"
    REQUEST_TIMEOUT_SECONDS: float = 60.0
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024
    PARSE_POLL_INTERVAL_SECONDS: float = 5.0
    PARSE_POLL_TIMEOUT_SECONDS: float = 900.0

    # --- 本地试运行引擎：百炼 Embedding + SQLite 向量库 + OCR ---
    # 未配置 RAGFLOW 时生效；便于在无 Docker 的机器上先跑通查询/入库/UI。
    BAILIAN_BASE_URL: str = ""          # OpenAI 兼容地址，如 https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
    BAILIAN_API_KEY: str = ""
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding-flash"
    LOCAL_STORE_PATH: str = "rag_store.sqlite3"   # 相对 rag-service 根目录
    OCR_BASE_URL: str = "http://127.0.0.1:8000"   # 队友 ocr_demo 服务（code/ocr_demo）
    OCR_TIMEOUT_SECONDS: float = 300.0
    OCR_VISION_MODEL: str = "qwen3.8-flash"       # OCR 服务不可用时，图片走百炼视觉兜底
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 80


settings = Settings()
