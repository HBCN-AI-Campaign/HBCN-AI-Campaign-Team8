from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, UniqueConstraint, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.schema import CreateSchema

from .config import settings
from .database import ResourceError, sql_engine


class DocumentWithdrawn(ResourceError):
    """A withdrawn source cannot be republished by an in-flight worker."""


class DocumentConflict(ResourceError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def data_root() -> Path:
    path = Path(settings.RAG_DATA_DIR)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


class DocumentStore:
    def __init__(self, *, engine=None, schema=None):
        self.engine = engine if engine is not None else sql_engine()
        schema = settings.RAG_DATABASE_SCHEMA if schema is None else schema
        metadata = MetaData(schema=schema)
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
            connection.execute(CreateSchema(schema, if_not_exists=True))
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
            row = connection.execute(select(self.table.c.events, self.table.c.state).where(self.table.c.id == document_id).with_for_update()).first()
            if not row:
                raise LookupError("文档不存在")
            if row.state == "withdrawn":
                raise DocumentWithdrawn("文档已撤回，不能继续发布")
            events = [*row[0], {"stage": stage, "label": label, "at": now.isoformat()}]
            connection.execute(update(self.table).where(self.table.c.id == document_id).values(
                stage=stage, updated_at=now, events=events, **values,
            ))

    def withdraw(self, document_id, chunks, *, expected_sha256, reason):
        """Invalidate document and all vector/lexical visibility in one transaction.

        Raw data is retained for an independently authorized retention process.
        The document lock also fences the worker's final publication transaction.
        """
        with self.engine.begin() as connection:
            connection.execute(select(func.set_config("lock_timeout", "5000", True)))
            connection.execute(select(func.set_config("statement_timeout", "10000", True)))
            row = connection.execute(select(self.table).where(self.table.c.id == document_id).with_for_update()).mappings().first()
            if not row:
                raise LookupError("文档不存在")
            if row["sha256"] != expected_sha256:
                raise DocumentConflict("文档版本不匹配，请重新核对")
            if row["state"] == "withdrawn":
                return dict(row)
            now = utc_now()
            connection.execute(update(chunks).where(chunks.c.document_id == document_id).values(searchable=False))
            connection.execute(update(self.table).where(self.table.c.id == document_id).values(
                state="withdrawn", stage="withdrawn", error=None, updated_at=now,
                events=[*row["events"], {"stage": "withdrawn", "label": "文档已撤回", "reason": reason,
                                       "actor": "trusted_service", "at": now.isoformat()}],
            ))
            return dict(connection.execute(select(self.table).where(self.table.c.id == document_id)).mappings().one())

    def list(self):
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table).order_by(self.table.c.created_at.desc())).mappings().all()
        return [self.public(dict(row)) for row in rows]

    def review_quality(self, document_id, review, actor):
        from .document_quality import POLICY_VERSION, assess_pages
        with self.engine.begin() as connection:
            connection.execute(select(func.set_config("lock_timeout", "5000", True)))
            row = connection.execute(select(self.table).where(self.table.c.id == document_id).with_for_update()).mappings().first()
            if not row:
                raise LookupError("文档不存在")
            actor.require(row["scope"], "reviewer")
            report = assess_pages(row["pages"])
            if row["state"] != "quality_review" or report["status"] != "quality_review":
                raise DocumentConflict("文档不处于可复核状态")
            if (review.expected_sha256 != row["sha256"] or review.expected_parsed_sha256 != report["parsed_sha256"]
                or review.expected_report_sha256 != report["report_sha256"]
                or report != row["provenance"].get("quality_report")):
                raise DocumentConflict("文档或质量报告已变化，请重新核对")
            if review.decision == "approve" and (review.reason != "source_compared"
                or sorted(review.verified_units) != list(range(len(row["pages"])))):
                raise DocumentConflict("必须逐单元核对原件后才能放行")
            now = utc_now()
            provenance = {**row["provenance"], "quality_review": {"reviewer": actor.subject, "decision": review.decision,
                "reason": review.reason, "at": now.isoformat(), "report_sha256": report["report_sha256"]}}
            if review.decision == "approve":
                provenance["quality_approval"] = {"policy_version": POLICY_VERSION, "source_sha256": row["sha256"],
                    "parsed_sha256": report["parsed_sha256"], "report_sha256": report["report_sha256"],
                    "decision": "approve", "reviewer": actor.subject, "at": now.isoformat()}
            stage = "quality_approved" if review.decision == "approve" else "quality_rejected"
            connection.execute(update(self.table).where(self.table.c.id == document_id).values(
                state="queued" if review.decision == "approve" else "failed", stage=stage, updated_at=now,
                error=None if review.decision == "approve" else "解析质量复核未通过，请更正原件或解析后重试",
                provenance=provenance, events=[*row["events"], {"stage": stage, "label": "解析质量复核已记录",
                    "actor": actor.subject, "decision": review.decision, "at": now.isoformat()}]))

    def recover_interrupted(self):
        with self.engine.begin() as connection:
            connection.execute(update(self.table).where(self.table.c.state.in_(["queued", "processing"])).values(
                state="failed", stage="interrupted", error="服务重启中断了处理，请重试该文档", updated_at=utc_now(),
            ))

    def public(self, row):
        fields = ("id", "name", "scope", "sha256", "state", "stage", "size_bytes", "chunk_count", "error", "events", "provenance", "created_at", "updated_at")
        result = {key: row[key] for key in fields}
        report = row["provenance"].get("quality_report")
        if report:
            from .document_quality import approval_matches
            result["quality"] = {**report, "review_status": "approved" if approval_matches(row, report)
                else "pending" if report["status"] == "quality_review" else "not_required"}
        else:
            result["quality"] = None
        result["run"] = "DONE" if row["state"] == "ready" else "FAILED" if row["state"] in {"failed", "withdrawn", "quarantined", "quality_review"} else "RUNNING"
        result["page_count"] = len(row["pages"]) if row["pages"] and all(page["page"] is not None for page in row["pages"]) else None
        result["section_count"] = len(row["pages"])
        result["source_available"] = row["state"] != "withdrawn" and self.original_path(row["id"]).is_file()
        return result
