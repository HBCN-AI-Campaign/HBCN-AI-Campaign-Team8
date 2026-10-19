"""百炼 OpenAI 兼容 Embedding 客户端（本地试运行引擎用）。

本地引擎不依赖 RAGFlow：文档切片后用本客户端生成向量，存入本地 SQLite。
"""
from __future__ import annotations

from typing import Any

import httpx

from .config import settings

EMBEDDING_BATCH_SIZE = 20


class EmbeddingError(RuntimeError):
    """Embedding 调用失败。"""


class EmbeddingNotConfiguredError(EmbeddingError):
    """BAILIAN_BASE_URL 或 BAILIAN_API_KEY 尚未配置。"""


class EmbeddingClient:
    def __init__(self) -> None:
        self.base_url = settings.BAILIAN_BASE_URL.rstrip("/")
        self.api_key = settings.BAILIAN_API_KEY
        self.model = settings.EMBEDDING_MODEL
        self.timeout = settings.REQUEST_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _require_configured(self) -> None:
        if not self.configured:
            raise EmbeddingNotConfiguredError("BAILIAN_BASE_URL 或 BAILIAN_API_KEY 尚未配置")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量，返回与 ``texts`` 同序的向量列表。"""
        self._require_configured()
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[offset:offset + EMBEDDING_BATCH_SIZE]
            try:
                response = httpx.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model, "input": batch},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Embedding 请求失败：{exc}") from exc
            if response.status_code >= 400:
                raise EmbeddingError(f"Embedding 返回 {response.status_code}：{response.text[:200]}")
            try:
                data = response.json()
            except ValueError as exc:
                raise EmbeddingError("Embedding 返回了无效 JSON") from exc

            items = data.get("data") or []
            batch_vectors = [
                [float(value) for value in item["embedding"]]
                for item in sorted(items, key=lambda entry: entry.get("index", 0))
                if isinstance(item.get("embedding"), list)
            ]
            if len(batch_vectors) != len(batch):
                raise EmbeddingError(
                    f"Embedding 返回数量不符：期望 {len(batch)}，实际 {len(batch_vectors)}"
                )
            vectors.extend(batch_vectors)
        return vectors

    def embed_one(self, text: str) -> list[float]:
        vectors = self.embed([text])
        if not vectors:
            raise EmbeddingError("Embedding 未返回向量")
        return vectors[0]
