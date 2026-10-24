# -*- coding: utf-8 -*-
"""全局配置常量（轻量方案：PaddleOCR + 轻量文档解析）。"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "samples"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# --------------------------------------------------------------------------
# 支持的输入类型
# --------------------------------------------------------------------------
# 图片类：走 OCR
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

# 办公文档：走各自的轻量解析器（无文本层时回退 OCR）
WORD_EXTENSIONS = {".doc", ".docx"}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
PDF_EXTENSIONS = {".pdf"}

# Optional page-level vision OCR fallback. Disabled unless explicitly approved and configured.
OCR_VISION_ENABLED = os.getenv("OCR_VISION_ENABLED", "false").strip().lower() == "true"
OCR_VISION_BASE_URL = os.getenv("OCR_VISION_BASE_URL", "").strip().rstrip("/")
OCR_VISION_API_KEY = os.getenv("OCR_VISION_API_KEY", "")
OCR_VISION_MODEL = os.getenv("OCR_VISION_MODEL", "").strip()
OCR_VISION_TIMEOUT_SECONDS = float(os.getenv("OCR_VISION_TIMEOUT_SECONDS", "45"))
OCR_VISION_MAX_IMAGE_BYTES = int(os.getenv("OCR_VISION_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
OCR_VISION_TRIGGER_MIN_LINES = int(os.getenv("OCR_VISION_TRIGGER_MIN_LINES", "2"))
OCR_VISION_TRIGGER_MIN_SCORE = float(os.getenv("OCR_VISION_TRIGGER_MIN_SCORE", "0.55"))
_DEFAULT_OCR_CPU_THREADS = max(1, min(10, (os.cpu_count() or 2) // 2))
try:
    OCR_CPU_THREADS = max(1, int(os.getenv("OCR_CPU_THREADS", str(_DEFAULT_OCR_CPU_THREADS))))
except ValueError:
    OCR_CPU_THREADS = _DEFAULT_OCR_CPU_THREADS
try:
    OCR_TEXT_RECOGNITION_BATCH_SIZE = max(
        1, int(os.getenv("OCR_TEXT_RECOGNITION_BATCH_SIZE", "1"))
    )
except ValueError:
    OCR_TEXT_RECOGNITION_BATCH_SIZE = 1

SUPPORTED_EXTENSIONS: dict[str, str] = {}
for _ext in IMAGE_EXTENSIONS:
    SUPPORTED_EXTENSIONS[_ext] = "image"
for _ext in WORD_EXTENSIONS:
    SUPPORTED_EXTENSIONS[_ext] = "word"
for _ext in EXCEL_EXTENSIONS:
    SUPPORTED_EXTENSIONS[_ext] = "excel"
for _ext in PDF_EXTENSIONS:
    SUPPORTED_EXTENSIONS[_ext] = "pdf"

DOC_TYPE_LABELS: dict[str, str] = {
    "image": "图片",
    "word": "Word",
    "excel": "Excel",
    "pdf": "PDF",
    "unknown": "未知",
}


def classify(path: Path) -> str:
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower(), "unknown")


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS
