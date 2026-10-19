# -*- coding: utf-8 -*-
"""全局配置常量（轻量方案：PaddleOCR + 轻量文档解析）。"""

from __future__ import annotations

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
