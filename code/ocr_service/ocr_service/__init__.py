# -*- coding: utf-8 -*-
"""ocr_service：轻量 OCR 文档识别。

技术栈（全部纯 CPU 可跑，远小于 MinerU）：
- OCR：PaddleOCR 3.x + PaddlePaddle CPU
- Word：python-docx
- Excel：openpyxl
- PDF：pdfplumber（文本层抽取，扫描件自动转图走 OCR）
"""

from . import config, ocr_engine, parser, pdf_to_image

__all__ = ["config", "ocr_engine", "parser", "pdf_to_image"]
__version__ = "0.1.0"
