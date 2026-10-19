"""本地 SQLite 向量库（本地试运行引擎用）。

在无 RAGFlow 的试运行阶段，用 SQLite 保存文档、切片与向量，
用纯 Python 余弦相似度做 top-k 检索。正式接入 RAGFlow/pgvector 后
本地引擎可整体替换，HTTP 契约不变。
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    page INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_scope ON documents(scope);
"""


def _default_path() -> Path:
    configured = settings.LOCAL_STORE_PATH
    if not configured:
        return Path(__file__).resolve().parent.parent / "rag_store.sqlite3"
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


class LocalVectorStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connection() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """打开连接并在结束时提交/关闭（Windows 下必须显式 close 才能释放文件句柄）。"""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_document(self, name: str, scope: str, chunks: list[dict[str, Any]]) -> str:
        with self._lock, self._connection() as conn:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "INSERT INTO documents(name, scope, created_at) VALUES (?, ?, ?)",
                (name, scope, now),
            )
            document_id = cursor.lastrowid
            conn.executemany(
                "INSERT INTO chunks(document_id, content, page, metadata, embedding) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        document_id,
                        chunk["content"],
                        chunk.get("page"),
                        json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                        json.dumps(chunk["embedding"]),
                    )
                    for chunk in chunks
                ],
            )
        return str(document_id)

    def query(self, vector: list[float], scope: str, top_k: int) -> list[dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT c.content, c.page, c.metadata, c.embedding,
                       d.id AS document_id, d.name AS document_name
                FROM chunks c JOIN documents d ON c.document_id = d.id
                WHERE d.scope = ?
                """,
                (scope,),
            ).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            chunk_vector = json.loads(row[3])
            similarity = _cosine(vector, chunk_vector)
            if similarity >= 0.2:  # 与 RAGFlow 检索阈值保持一致
                scored.append({
                    "content": row[0],
                    "page_num": row[1],
                    "metadata": json.loads(row[2]),
                    "document_id": str(row[4]),
                    "document_keyword": row[5],
                    "similarity": similarity,
                })
        scored.sort(key=lambda item: item["similarity"], reverse=True)
        return scored[:top_k]

    def list_documents(self, scope: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connection() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT id, name, scope, created_at, "
                    "(SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) "
                    "FROM documents d WHERE scope = ? ORDER BY id DESC",
                    (scope,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, scope, created_at, "
                    "(SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) "
                    "FROM documents d ORDER BY id DESC",
                ).fetchall()
        return [
            {"id": str(row[0]), "name": row[1], "scope": row[2], "created_at": row[3], "chunk_count": row[4]}
            for row in rows
        ]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
