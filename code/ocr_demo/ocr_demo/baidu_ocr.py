# -*- coding: utf-8 -*-
"""百度智能云 OCR 适配器。

用法：
    1. 在 .env 中配置 BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY
    2. 调用 recognize() 识别图片或 PDF，返回与本地引擎一致的文本 + 坐标结构

接口：
    - 通用文字识别（高精度版）accurate_basic：图片，返回 words + location + probability
    - 支持 pdf_file 参数直接传 PDF（需 base64），PDF 走 accurate 接口按页返回

合规提示：本模块会把文件内容上传到百度智能云，请在确认数据可外发后使用。
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 配置（优先读环境变量，其次读 .env 文件）
# ---------------------------------------------------------------------------
_API_KEY: str | None = None
_SECRET_KEY: str | None = None


def _load_env():
    global _API_KEY, _SECRET_KEY
    import os

    # 先读环境变量
    _API_KEY = os.environ.get("BAIDU_OCR_API_KEY")
    _SECRET_KEY = os.environ.get("BAIDU_OCR_SECRET_KEY")

    # 再尝试从 .env 文件读取
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists() and (not _API_KEY or not _SECRET_KEY):
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "BAIDU_OCR_API_KEY" and not _API_KEY:
                _API_KEY = v
            elif k == "BAIDU_OCR_SECRET_KEY" and not _SECRET_KEY:
                _SECRET_KEY = v


class BaiduOcrClient:
    """百度智能云 OCR 客户端（带 token 缓存）。"""

    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    ACCURATE_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"
    PDF_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate"

    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        _load_env()
        self.api_key = api_key or _API_KEY
        self.secret_key = secret_key or _SECRET_KEY
        self._token: str | None = None
        self._token_expire: float = 0.0

        if not self.api_key or not self.secret_key:
            raise RuntimeError(
                "缺少百度 OCR 密钥。请在 .env 中配置：\n"
                "  BAIDU_OCR_API_KEY=你的API Key\n"
                "  BAIDU_OCR_SECRET_KEY=你的Secret Key"
            )

    # ------------------------------------------------------------------
    # token
    # ------------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expire:
            return self._token
        resp = requests.get(
            self.TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            },
            timeout=30,
        )
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取 access_token 失败：{data}")
        self._token = data["access_token"]
        # token 有效期 30 天，提前 1 天过期
        self._token_expire = time.time() + data.get("expires_in", 2592000) - 86400
        return self._token

    # ------------------------------------------------------------------
    # 识别
    # ------------------------------------------------------------------
    def recognize_image(self, image_path: Path, language_type: str = "CHN_ENG") -> dict:
        """识别单张图片，返回 {text, blocks}。"""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        token = self._get_token()
        url = f"{self.ACCURATE_URL}?access_token={token}"
        resp = requests.post(
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "image": image_b64,
                "language_type": language_type,
                "detect_direction": "true",
                "paragraph": "false",
            },
            timeout=60,
        )
        return self._parse(resp.json())

    def recognize_pdf(self, pdf_path: Path, language_type: str = "CHN_ENG") -> dict:
        """识别 PDF（百度 accurate 接口直接支持 pdf_file）。"""
        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

        token = self._get_token()
        url = f"{self.PDF_URL}?access_token={token}"
        resp = requests.post(
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "pdf_file": pdf_b64,
                "language_type": language_type,
                "detect_direction": "true",
            },
            timeout=120,
        )
        return self._parse(resp.json())

    @staticmethod
    def _parse(data: dict) -> dict:
        """把百度返回转成与本地引擎一致的结构。"""
        if "error_code" in data:
            raise RuntimeError(
                f"百度 OCR 错误 {data.get('error_code')}: {data.get('error_msg')}"
            )

        blocks: list[dict] = []
        for item in data.get("words_result", []):
            loc = item.get("location", {})
            box = [
                loc.get("left", 0),
                loc.get("top", 0),
                loc.get("left", 0) + loc.get("width", 0),
                loc.get("top", 0) + loc.get("height", 0),
            ]
            blocks.append(
                {
                    "text": item.get("words", ""),
                    "score": float(item.get("probability", {}).get("average", 1.0)),
                    "box": box,
                    "poly": [
                        [box[0], box[1]],
                        [box[2], box[1]],
                        [box[2], box[3]],
                        [box[0], box[3]],
                    ],
                }
            )

        text = "\n".join(b["text"] for b in blocks)
        return {"text": text, "blocks": blocks}


# 模块级单例
_client: BaiduOcrClient | None = None


def get_client() -> BaiduOcrClient:
    global _client
    if _client is None:
        _client = BaiduOcrClient()
    return _client


def recognize(path: Path) -> dict:
    """统一入口：按扩展名分派，返回 {text, blocks}。"""
    suffix = path.suffix.lower()
    client = get_client()
    if suffix == ".pdf":
        return client.recognize_pdf(path)
    return client.recognize_image(path)
