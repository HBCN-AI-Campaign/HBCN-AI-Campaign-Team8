"""Optional, fail-closed OpenAI-compatible vision OCR adapter."""
from __future__ import annotations

import base64
import ipaddress
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config


def is_configured() -> bool:
    return bool(
        config.OCR_VISION_ENABLED
        and config.OCR_VISION_BASE_URL
        and config.OCR_VISION_API_KEY
        and config.OCR_VISION_MODEL
    )


def _completion_url(base_url: str) -> str | None:
    parsed = urlsplit(base_url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if parsed.scheme != "https":
        try:
            if parsed.scheme != "http" or not ipaddress.ip_address(parsed.hostname).is_loopback:
                return None
        except ValueError:
            return None
    return f"{base_url.rstrip('/')}/chat/completions"


def recognize_page(image_path: Path) -> str | None:
    """Return literal page text, or None when disabled or when the response is unusable."""
    if not is_configured():
        return None
    endpoint = _completion_url(config.OCR_VISION_BASE_URL)
    if endpoint is None:
        return None

    try:
        image = image_path.read_bytes()
        if not image or len(image) > config.OCR_VISION_MAX_IMAGE_BYTES:
            return None
        mime_type = mimetypes.guess_type(image_path.name)[0]
        if not mime_type or not mime_type.startswith("image/"):
            return None
        data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        response = httpx.post(
            endpoint,
            json={
                "model": config.OCR_VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": (
                            "逐字识别页面中实际可见的文字，保留原有阅读顺序和表格行列。"
                            "不要推断、补全或作业务判断；无法辨认处写 [UNCLEAR]。只返回识别文本。"
                        )},
                    ],
                }],
                "max_tokens": 4000,
            },
            headers={"Authorization": f"Bearer {config.OCR_VISION_API_KEY}"},
            timeout=config.OCR_VISION_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        if response.status_code >= 400:
            return None
        choice = response.json()["choices"][0]
        text = choice["message"]["content"]
        if choice.get("finish_reason") != "stop" or not isinstance(text, str):
            return None
        text = text.strip()
        if not text or len(text) > 20000:
            return None
        return text
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OSError):
        return None
