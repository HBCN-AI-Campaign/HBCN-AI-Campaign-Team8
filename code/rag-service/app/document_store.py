from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, UniqueConstraint, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.schema import CreateSchema

from .config import settings
from .database import sql_engine


def utc_now():
    return datetime.now(timezone.utc)


def data_root() -> Path:
    path = Path(settings.RAG_DATA_DIR)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


class DocumentStore:
    def __init__(self):
        self.engine = sql_engine()
        metadata = MetaData(schema=settings.RAG_DATABASE_SCHEMA)
        self.table = Table(
            "documents", metadata,
            Column("id", String(36), primary_key=True),
            Column("name", Text, nullable=False),
            Column("scope", String(32), nullable=False),
            Column("sha256", String(64), nullable=False),
            Column("embedding_model", String(128), nullable=False),
            Column("state", String(24), nullable=False),
            Column("stage", String(24), nullable=False),
            Column("content_type", String(128), nullable=False),
            Column("size_bytes", Integer, nullable=False),
            Column("chunk_count", Integer, nullable=False, default=0),
            Column("error", Text),
            Column("pages", JSONB, nullable=False),
            Column("provenance", JSONB, nullable=False),
            Column("events", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("scope", "sha256", "embedding_model", name="document_content_version"),
        )
        with self.engine.begin() as connection:
            connection.execute(CreateSchema(settings.RAG_DATABASE_SCHEMA, if_not_exists=True))
        metadata.create_all(self.engine)

    def create(self, name: str, scope: str, content: bytes, content_type: str, provenance: dict | None = None):
        document_id = str(uuid.uuid4())
        now = utc_now()
        digest = hashlib.sha256(content).hexdigest()
        event = {"stage": "received", "label": "文件已接收", "at": now.isoformat()}
        statement = pg_insert(self.table).values(
            id=document_id, name=Path(name.replace("\\", "/")).name, scope=scope,
            sha256=digest, embedding_model=settings.EMBEDDING_MODEL,
            state="queued", stage="received", content_type=content_type, size_bytes=len(content),
            chunk_count=0, error=None, pages=[], provenance=provenance or {}, events=[event], created_at=now, updated_at=now,
        ).on_conflict_do_nothing(constraint="document_content_version").returning(self.table.c.id)
        with self.engine.begin() as connection:
            created = connection.execute(statement).scalar_one_or_none()
            if created is None:
                existing = connection.execute(select(self.table).where(
                    self.table.c.scope == scope,
                    self.table.c.sha256 == digest,
                    self.table.c.embedding_model == settings.EMBEDDING_MODEL,
                )).mappings().one()
                return dict(existing), False
        path = self.original_path(document_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            self.set_stage(document_id, "failed", "文件保存失败", state="failed", error="文件保存失败")
            raise
        return self.get(document_id), True

    def original_path(self, document_id: str) -> Path:
        normalized = str(uuid.UUID(document_id))
        return data_root() / "originals" / normalized / "original"

    def get(self, document_id: str):
        with self.engine.connect() as connection:
            row = connection.execute(select(self.table).where(self.table.c.id == document_id)).mappings().first()
        return dict(row) if row else None

    def set_stage(self, document_id: str, stage: str, label: str, **values):
        now = utc_now()
        with self.engine.begin() as connection:
            row = connection.execute(select(self.table.c.events).where(self.table.c.id == document_id).with_for_update()).first()
            if not row:
                raise LookupError("文档不存在")
            events = [*row[0], {"stage": stage, "label": label, "at": now.isoformat()}]
            connection.execute(update(self.table).where(self.table.c.id == document_id).values(
                stage=stage, updated_at=now, events=events, **values,
            ))

    def list(self):
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table).order_by(self.table.c.created_at.desc())).mappings().all()
        return [self.public(dict(row)) for row in rows]

    def recover_interrupted(self):
        with self.engine.begin() as connection:
            connection.execute(update(self.table).where(self.table.c.state.in_(["queued", "processing"])).values(
                state="failed", stage="interrupted", error="服务重启中断了处理，请重试该文档", updated_at=utc_now(),
            ))

    def public(self, row):
        fields = ("id", "name", "scope", "state", "stage", "size_bytes", "chunk_count", "error", "events", "provenance", "created_at", "updated_at")
        result = {key: row[key] for key in fields}
        result["run"] = "DONE" if row["state"] == "ready" else "FAILED" if row["state"] == "failed" else "RUNNING"
        result["page_count"] = len(row["pages"]) if row["pages"] and all(page["page"] is not None for page in row["pages"]) else None
        result["section_count"] = len(row["pages"])
        result["source_available"] = self.original_path(row["id"]).is_file()
        return result
