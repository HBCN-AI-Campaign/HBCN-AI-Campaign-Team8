import unittest
import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, MetaData, String, Table, Text, create_engine, delete, insert, select, update

from app.config import settings
from app.embedding import EmbeddingError
from app.main import app, lifespan
from app.postgres_engine import PostgresEngine


class SQLiteIngestionHarness:
    """Offline transaction harness; it does not emulate PostgreSQL or pgvector."""

    def __init__(self, directory, document_id, content):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata = MetaData()
        self.table = Table("documents", metadata,
            Column("id", String, primary_key=True), Column("name", Text, nullable=False),
            Column("scope", String, nullable=False), Column("sha256", String, nullable=False),
            Column("state", String, nullable=False), Column("stage", String, nullable=False),
            Column("error", Text), Column("chunk_count", Integer, nullable=False),
            Column("pages", JSON, nullable=False), Column("provenance", JSON, nullable=False),
            Column("events", JSON, nullable=False), Column("created_at", DateTime(timezone=True)),
            Column("updated_at", DateTime(timezone=True)))
        self.chunks = Table("chunks", metadata,
            Column("chunk_id", String, primary_key=True), Column("document_id", String, nullable=False),
            Column("content", Text, nullable=False), Column("searchable", Boolean, nullable=False))
        metadata.create_all(self.engine)
        now = datetime.now(timezone.utc)
        self.original = Path(directory) / "original"
        self.original.write_bytes(content)
        with self.engine.begin() as connection:
            connection.execute(insert(self.table).values(id=document_id, name="synthetic.txt", scope="business_rules",
                sha256=hashlib.sha256(content).hexdigest(), state="queued", stage="received", error=None,
                chunk_count=0, pages=[], provenance={}, events=[], created_at=now, updated_at=now))

    def get(self, document_id):
        with self.engine.connect() as connection:
            return dict(connection.execute(select(self.table).where(self.table.c.id == document_id)).mappings().one())

    def set_stage(self, document_id, stage, label, **values):
        del label
        with self.engine.begin() as connection:
            connection.execute(update(self.table).where(self.table.c.id == document_id).values(
                stage=stage, updated_at=datetime.now(timezone.utc), **values))

    def original_path(self, document_id):
        del document_id
        return self.original


class PartialVectorWriter:
    def __init__(self, engine, chunks, fail_once=True):
        self.engine, self.chunks, self.fail_once = engine, chunks, fail_once
        self.deleted_generations = []

    def delete(self, *, filter):
        document_id = filter["document_id"]
        with self.engine.begin() as connection:
            stale = connection.execute(select(self.chunks.c.chunk_id).where(
                self.chunks.c.document_id == document_id)).scalars().all()
            self.deleted_generations.append(list(stale))
            connection.execute(delete(self.chunks).where(self.chunks.c.document_id == document_id))

    def add_documents(self, documents, *, ids):
        rows = [{"chunk_id": chunk_id, "document_id": item.metadata["document_id"],
                 "content": item.page_content, "searchable": False}
                for chunk_id, item in zip(ids, documents)]
        if self.fail_once:
            self.fail_once = False
            with self.engine.begin() as connection:
                connection.execute(insert(self.chunks), rows[:1])
            raise EmbeddingError("synthetic embedding timeout after partial write")
        with self.engine.begin() as connection:
            connection.execute(insert(self.chunks), rows)


class StartupRecoveryTests(unittest.TestCase):
    def test_postgres_startup_invokes_interrupted_job_recovery(self):
        recover = Mock()
        engine = SimpleNamespace(documents=SimpleNamespace(recover_interrupted=recover))
        application = SimpleNamespace(state=SimpleNamespace())

        with patch("app.main.engine_kind", return_value="postgres"), \
                patch("app.main.get_engine", return_value=engine):
            async def start_and_stop():
                async with lifespan(application):
                    pass

            import asyncio
            asyncio.run(start_and_stop())

        recover.assert_called_once_with()
        self.assertFalse(hasattr(application.state, "startup_error"))

    def test_ready_stays_unavailable_when_startup_recovery_fails(self):
        previous_token = settings.SERVICE_TOKEN
        previous_error = getattr(app.state, "startup_error", None)
        settings.SERVICE_TOKEN = "synthetic-service-token"
        app.state.startup_error = None
        engine = SimpleNamespace(documents=SimpleNamespace(
            recover_interrupted=Mock(side_effect=RuntimeError("synthetic recovery failure"))))
        readiness = Mock(return_value={"unverified_ready_documents": 0})

        try:
            with patch("app.main.engine_kind", return_value="postgres"), \
                    patch("app.main.get_engine", return_value=engine), \
                    patch("app.backend_api.postgres_engine", return_value=SimpleNamespace(readiness=readiness)) as make_engine, \
                    patch("app.backend_api.SDKRuntime") as runtime:
                runtime.return_value.health.return_value = True
                with TestClient(app) as client:
                    response = client.get("/api/v1/ready", headers={
                        "Authorization": "Bearer synthetic-service-token",
                    })
        finally:
            settings.SERVICE_TOKEN = previous_token
            if previous_error is None:
                if hasattr(app.state, "startup_error"):
                    del app.state.startup_error
            else:
                app.state.startup_error = previous_error

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["message"], "数据库初始化失败，请检查 /api/v1/ready")
        make_engine.assert_not_called()
        readiness.assert_not_called()
        runtime.assert_not_called()


class IngestionFailureTests(unittest.TestCase):
    def test_partial_vector_write_is_hidden_and_next_attempt_replaces_stale_generation(self):
        content = ("合成政策要求核对金额并保留原文依据。" * 12).encode()
        document_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory:
            documents = SQLiteIngestionHarness(directory, document_id, content)
            service = PostgresEngine.__new__(PostgresEngine)
            service.documents = documents
            service.chunks = documents.chunks
            service.vectors = PartialVectorWriter(documents.engine, documents.chunks)

            with patch.object(settings, "RAG_SEARCH_MODE", "vector"), \
                    patch.object(settings, "CHUNK_SIZE", 32), patch.object(settings, "CHUNK_OVERLAP", 0), \
                    patch("app.postgres_engine.extract_pages", return_value=[{"page": 1, "text": content.decode()}]), \
                    patch("app.postgres_engine.assess_pages", return_value={"status": "mechanically_checked"}):
                service.process(document_id)

                failed = documents.get(document_id)
                with documents.engine.connect() as connection:
                    partial = connection.execute(select(documents.chunks)).mappings().all()
                self.assertEqual(failed["state"], "failed")
                self.assertEqual(failed["stage"], "failed")
                self.assertTrue(partial)
                self.assertTrue(all(row["searchable"] is False for row in partial))

                service.process(document_id)

            ready = documents.get(document_id)
            with documents.engine.connect() as connection:
                published = connection.execute(select(documents.chunks)).mappings().all()
            self.assertEqual(ready["state"], "ready")
            self.assertEqual(ready["chunk_count"], len(published))
            self.assertGreater(len(published), 1)
            self.assertTrue(all(row["searchable"] is True for row in published))
            self.assertEqual(len(service.vectors.deleted_generations), 2)
            self.assertEqual(len(service.vectors.deleted_generations[1]), 1,
                "retry should remove the partial first attempt before writing a new generation")
            self.assertEqual(len({row["chunk_id"] for row in published}), len(published))


if __name__ == "__main__":
    unittest.main()
