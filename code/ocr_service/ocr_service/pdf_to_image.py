# -*- coding: utf-8 -*-
"""PDF 转图片：用 pdfplumber 的 Page.to_image 渲染成 PNG。

供扫描件 PDF 走 OCR 时使用。输出到临时目录，调用方用完即弃。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp


def pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[Path]:
    """把 PDF 每一页渲染成 PNG，返回图片路径列表。"""
    import pdfplumber

    out_dir = Path(mkdtemp(prefix="ocr_pdf_"))
    image_paths: list[Path] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            img = page.to_image(resolution=dpi)
            out_path = out_dir / f"page_{idx:03d}.png"
            img.save(str(out_path))
            image_paths.append(out_path)

    return image_paths
