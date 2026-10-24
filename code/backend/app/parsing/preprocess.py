"""PDF page routing and rendering; never decide OCR eligibility per whole document."""
from io import BytesIO
from pathlib import Path
import math

from .config import ParserSettings
from .contracts import Block, Page, ParseError


def prepare(path: Path, cfg: ParserSettings) -> list[Page]:
    from PIL import Image
    if path.stat().st_size > cfg.max_file_bytes:
        raise ParseError("FILE_TOO_LARGE")
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            with Image.open(path) as im:
                if im.width * im.height > cfg.max_pixels:
                    raise ParseError("IMAGE_TOO_LARGE")
                buf = BytesIO()
                im.convert("RGB").save(buf, format="PNG")
                return [Page(1, im.width, im.height, buf.getvalue())]
        except ParseError:
            raise
        except Exception:
            raise ParseError("INVALID_IMAGE") from None
    if path.suffix.lower() != ".pdf":
        raise ParseError("UNSUPPORTED_FILE_USE_PDF")
    import pdfplumber
    import pypdfium2 as pdfium
    try:
        result = []
        with pdfplumber.open(path) as pdf, pdfium.PdfDocument(path) as render:
            if not 0 < len(pdf.pages) <= cfg.max_pages:
                raise ParseError("PAGE_LIMIT")
            for n, native in enumerate(pdf.pages, 1):
                words = native.extract_words() or []
                text = " ".join(w["text"] for w in words)
                # Large image plus sparse native overlay must still use OCR.
                image_area = sum(abs(i["x1"]-i["x0"])*abs(i["bottom"]-i["top"]) for i in native.images)
                needs_ocr = len(text.strip()) < 40 or image_area > native.width*native.height*0.45
                page_handle = render[n-1]
                try:
                    width, height = page_handle.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise ParseError("INVALID_PAGE_SIZE")
                    if width*height*cfg.render_scale**2 > cfg.max_pixels:
                        raise ParseError("IMAGE_TOO_LARGE")
                    bitmap = page_handle.render(scale=cfg.render_scale)
                    try:
                        im = bitmap.to_pil()
                        buf = BytesIO(); im.save(buf, format="PNG")
                        page = Page(n, im.width, im.height, buf.getvalue(), needs_ocr=needs_ocr)
                    finally:
                        bitmap.close()
                finally:
                    page_handle.close()
                if not needs_ocr:
                    for i,w in enumerate(words):
                        page.blocks.append(Block(f"p{n}b{i}",w["text"],
                            [w["x0"]/native.width,w["top"]/native.height,w["x1"]/native.width,w["bottom"]/native.height],
                            1.0,"pdf_text"))
                result.append(page)
        return result
    except ParseError:
        raise
    except Exception:
        raise ParseError("INVALID_OR_ENCRYPTED_PDF") from None
