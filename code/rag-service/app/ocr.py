"""文档解析客户端：优先调用队友 ocr_demo（code/ocr_demo）的 HTTP 服务。

解析链路：
- 纯文本格式（txt/md/html/csv/json/mmd/yaml）由本模块直接读取，无需外部服务；
- 图片 / PDF / Word / Excel 交给 OCR 服务（``OCR_BASE_URL``，即队友的 ocr_demo）；
- OCR 服务不可用且文件为图片时，回退到百炼多模态视觉（``OCR_VISION_MODEL``）。

这样在未安装 PaddleOCR 的机器上，图片与手写件仍能走通，
后续 OCR 服务（PaddleOCR）就绪后自动优先使用本地 OCR。
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from .config import settings

TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".csv", ".json", ".mmd", ".yaml", ".yml"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _read_text(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


class OCRClient:
    """OCR 服务客户端 + 百炼视觉兜底。"""

    def __init__(self) -> None:
        self.base_url = settings.OCR_BASE_URL.rstrip("/")
        self.timeout = settings.OCR_TIMEOUT_SECONDS
        self.vision_base_url = settings.BAILIAN_BASE_URL.rstrip("/")
        self.vision_api_key = settings.BAILIAN_API_KEY
        self.vision_model = settings.OCR_VISION_MODEL

    def extract(self, filename: str, content: bytes) -> dict[str, Any]:
        """返回 ``{"text", "via_ocr", "error"}``，error 为 None 表示成功。"""
        extension = filename[filename.rfind("."):].lower() if "." in filename else ""
        if extension in TEXT_EXTENSIONS:
            return {"text": _read_text(content), "via_ocr": False, "error": None}

        if self.base_url:
            result = self._call_ocr_service(filename, content, extension)
            if result is not None:
                return result

        if extension in IMAGE_EXTENSIONS and self.vision_base_url and self.vision_api_key:
            return self._call_vision(filename, content, extension)

        return {
            "text": "",
            "via_ocr": False,
            "error": "OCR 服务未启动（OCR_BASE_URL），图片/扫描件暂无法解析；请启动 code/ocr_demo 后再试",
        }

    def _call_ocr_service(self, filename: str, content: bytes, extension: str) -> dict[str, Any] | None:
        del extension
        try:
            response = httpx.post(
                f"{self.base_url}/ocr/file",
                files={"file": (filename, content, "application/octet-stream")},
                timeout=self.timeout,
            )
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        if data.get("error"):
            return None
        return {"text": data.get("text", ""), "via_ocr": bool(data.get("via_ocr")), "error": None}

    def _call_vision(self, filename: str, content: bytes, extension: str) -> dict[str, Any]:
        data_url = f"data:{IMAGE_MIME[extension]};base64,{base64.b64encode(content).decode('ascii')}"
        payload = {
            "model": self.vision_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "请完整识别这张图片中的文字（含表格），按原文顺序输出，不要解释。"},
                ],
            }],
            "max_tokens": 2000,
        }
        try:
            response = httpx.post(
                f"{self.vision_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.vision_api_key}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return {"text": "", "via_ocr": True, "error": f"视觉 OCR 请求失败：{exc}"}
        if response.status_code >= 400:
            return {"text": "", "via_ocr": True, "error": f"视觉 OCR 返回 {response.status_code}：{response.text[:200]}"}
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError):
            return {"text": "", "via_ocr": True, "error": "视觉 OCR 返回格式异常"}
        return {"text": text, "via_ocr": True, "error": None}
