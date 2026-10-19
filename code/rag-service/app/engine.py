"""知识库引擎工厂：按配置在 RAGFlow 与本地引擎之间选择。

- 配置了 RAGFLOW_BASE_URL + RAGFLOW_API_KEY -> 使用 RAGFlowClient（正式检索底座）
- 否则配置了 BAILIAN_BASE_URL + BAILIAN_API_KEY -> 使用 LocalEngine（试运行：
  百炼 Embedding + SQLite 向量库 + OCR 文档解析）

两种引擎暴露相同的 ``retrieve`` / ``upload`` 接口，HTTP 契约不变，便于后续无缝切换。
"""
from __future__ import annotations

from typing import Any

from .config import settings
from .embedding import EmbeddingClient
from .local_store import LocalVectorStore
from .ocr import OCRClient
from .ragflow import RAGFlowClient, RAGFlowError, RAGFlowNotConfiguredError


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """按固定字符窗口切片，带重叠，近似 RAGFlow 的 naive 切分。"""
    size = size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


class LocalEngine:
    """本地引擎：百炼 Embedding + SQLite 向量库 + OCR 文档解析。"""

    def __init__(self) -> None:
        self.embedding = EmbeddingClient()
        self.store = LocalVectorStore()
        self.ocr = OCRClient()

    def retrieve(self, *, query: str, scope: str, top_k: int) -> list[dict[str, Any]]:
        vector = self.embedding.embed_one(query)
        return self.store.query(vector, scope, top_k)

    def upload(
        self,
        *,
        scope: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> list[str]:
        del content_type
        extracted = self.ocr.extract(filename, content)
        if extracted["error"]:
            raise RAGFlowError(extracted["error"])

        chunks = [
            {
                "content": piece,
                "page": None,
                "metadata": {
                    "source": filename,
                    "knowledge_scope": scope,
                    "via_ocr": bool(extracted.get("via_ocr")),
                },
            }
            for piece in chunk_text(extracted["text"])
        ]
        if not chunks:
            raise RAGFlowError("未从文件中提取到可入库的文本")

        vectors = self.embedding.embed([chunk["content"] for chunk in chunks])
        for chunk, vector in zip(chunks, vectors):
            chunk["embedding"] = vector

        document_id = self.store.add_document(filename, scope, chunks)
        return [document_id]


def engine_kind() -> str:
    ragflow_ready = bool(settings.RAGFLOW_BASE_URL and settings.RAGFLOW_API_KEY)
    local_ready = bool(settings.BAILIAN_BASE_URL and settings.BAILIAN_API_KEY)

    if settings.RAG_ENGINE == "ragflow":
        return "ragflow" if ragflow_ready else "none"
    if settings.RAG_ENGINE == "local":
        return "local" if local_ready else "none"
    if ragflow_ready:
        return "ragflow"
    if local_ready:
        return "local"
    return "none"


def get_engine() -> Any:
    """按配置返回可用引擎；都未配置时抛出 RAGFlowNotConfiguredError。"""
    kind = engine_kind()
    if kind == "ragflow":
        return RAGFlowClient()
    if kind == "local":
        return LocalEngine()
    raise RAGFlowNotConfiguredError(
        "RAG 引擎尚未配置：设置 RAGFLOW_BASE_URL/RAGFLOW_API_KEY，或 BAILIAN_BASE_URL/BAILIAN_API_KEY"
    )
