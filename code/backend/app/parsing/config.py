from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ParserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PARSER_", extra="ignore")

    ocr_base_url: str = ""  # e.g. http://127.0.0.1:7888 or an SSH tunnel
    ocr_token: SecretStr = SecretStr("")
    vision_base_url: str = ""
    vision_api_key: SecretStr = SecretStr("")
    vision_model: str = ""
    request_timeout: float = Field(default=120, gt=0, le=600)
    max_file_bytes: int = Field(default=30 * 1024 * 1024, gt=0)
    max_batch_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=80, ge=1, le=500)
    max_files: int = Field(default=12, ge=1, le=50)
    max_pixels: int = Field(default=16_000_000, gt=0)
    render_scale: float = Field(default=2.0, ge=1, le=4)
    # One OCR request at a time per backend process; shared OCR is CPU constrained.
    max_vision_pages_per_call: int = Field(default=3, ge=1, le=6)
    regional_retry_pages: int = Field(default=2, ge=0, le=4)
    visual_correction_fields: int = Field(default=6, ge=0, le=8)
    max_structure_calls: int = Field(default=10, ge=0, le=24)
    max_terms_calls: int = Field(default=8, ge=0, le=24)


def get_settings() -> ParserSettings:
    cfg = ParserSettings()
    if not cfg.ocr_base_url:
        from ..config import settings

        cfg.ocr_base_url = settings.OCR_BASE_URL
    return cfg
