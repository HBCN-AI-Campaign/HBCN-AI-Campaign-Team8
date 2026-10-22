"""Actual PostgreSQL source withdrawal and in-flight publication races.

Synthetic files only, random schema only, no embedding/model calls.
"""
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, MetaData, String, Table, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import DropSchema

from app.answer_graph import build_answer_graph
from app.config import settings
from app.database import ResourceError, sql_engine
from app.document_store import DocumentConflict, DocumentStore, DocumentWithdrawn
from app.lexical_index import backfill, index_chunk, lexical_table
from app.main import app
from app.postgres_engine import PostgresEngine


@unittest.skipUnless(os.environ.get("HBCN_TEST_POSTGRES") == "1", "opt-in for isolated lifecycle PostgreSQL schema")
class DocumentLifecyclePostgresTests(unittest.TestCase):
    def setUp(self):
        self.schema = "rag_lifecycle_test_" + uuid.uuid4().hex
        self.assertRegex(self.schema, r"^rag_lifecycle_test_[0-9a-f]{32}$")
        self.engine = sql_engine()
        self.folder = tempfile.TemporaryDirectory()
        self.config = patch.multiple(settings, RAG_DATA_DIR=self.folder.name, RAG_SEARCH_MODE="hybrid")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.drop_schema)
        self.store = DocumentStore(engine=self.engine, schema=self.schema)
        self.chunks = Table("chunks", MetaData(schema=self.schema),
            Column("langchain_id", UUID(as_uuid=True), primary_key=True), Column("content", Text, nullable=False),
            Column("document_id", String, nullable=False), Column("scope", String, nullable=False),
            Column("embedding_model", String, nullable=False), Column("searchable", Boolean, nullable=False),
            Column("langchain_metadata", JSONB, nullable=False))
        self.chunks.create(self.engine)
        self.service = PostgresEngine.__new__(PostgresEngine)
        self.service.documents, self.service.chunks = self.store, self.chunks
        self.service.lexical, self.service.vectors = lexical_table(self.chunks), Mock()
        self.service.slots = threading.BoundedSemaphore(1)
        backfill(self.engine, self.chunks)
        self.service.vectors.similarity_search_with_score.return_value = []

    def drop_schema(self):
        with self.engine.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True, if_exists=True))

    def create(self):
        return self.store.create("synthetic.txt", "business_rules", "金额有误须核对原始指令。".encode(), "text/plain")[0]

    def add_chunk(self, document_id, *, searchable=True, content="金额有误须核对原始指令。"):
        from app.document_quality import assess_pages
        pages = [{"page": None, "text": content, "extraction": {"method": "text_decode"}}]
        row = self.store.get(document_id)
        self.store.set_stage(document_id, row["stage"], "synthetic mechanical check",
            pages=pages, provenance={**row["provenance"], "quality_report": assess_pages(pages)})
        key = uuid.uuid4()
        metadata = {"filename": "synthetic.txt", "scope": "business_rules"}
        with self.engine.begin() as connection:
            connection.execute(self.chunks.insert().values(langchain_id=key, document_id=document_id, content=content,
                scope="business_rules", embedding_model=settings.EMBEDDING_MODEL, searchable=searchable,
                langchain_metadata=metadata))
            index_chunk(connection, self.service.lexical, key, content)
        return {"document_id": document_id, "chunk_id": str(key), "content": content,
                "document_keyword": "synthetic.txt", "metadata": metadata, "similarity": .9}

    def test_withdrawal_atomically_blocks_both_channels_readers_and_stale_vector_results(self):
        row = self.create()
        self.store.set_stage(row["id"], "ready", "ready", state="ready")
        evidence = self.add_chunk(row["id"])
        self.assertEqual(len(self.service.retrieve(query="金额", scope="all", top_k=5)), 1)
        with self.assertRaises(DocumentConflict):
            self.service.withdraw(row["id"], expected_sha256="0" * 64, reason="incorrect")
        headers = {"Authorization": "Bearer synthetic-service"}
        payload = {"expected_sha256": row["sha256"], "reason": "authorization_revoked"}
        with patch.object(settings, "SERVICE_TOKEN", "synthetic-service"), patch("app.backend_api.postgres_engine", return_value=self.service):
            client = TestClient(app)
            try:
                path = f'/api/v1/documents/{row["id"]}'
                self.assertEqual(client.post(path + "/withdraw", json=payload).status_code, 401)
                self.assertEqual(client.post(path + "/withdraw", json={**payload, "expected_sha256": "0" * 64}, headers=headers).status_code, 409)
                self.assertEqual(client.post(path + "/withdraw", json={**payload, "actor": "admin"}, headers=headers).status_code, 422)
                response = client.post(path + "/withdraw", json=payload, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertFalse(response.json()["document"]["source_available"])
                self.assertEqual(client.get(path + "/source", headers=headers).status_code, 404)
                self.assertEqual(client.get(path + "/content", headers=headers).status_code, 404)
                self.assertEqual(client.post(path + "/withdraw", json=payload, headers=headers).status_code, 200)
            finally:
                client.close()
        # A provider that began before withdrawal may still return old vectors.
        vector = SimpleNamespace(page_content=evidence["content"], id=evidence["chunk_id"],
            metadata={**evidence["metadata"], "document_id": row["id"]})
        self.service.vectors.similarity_search_with_score.return_value = [(vector, .1)]
        self.assertEqual(self.service.retrieve(query="金额", scope="all", top_k=5), [])
        self.assertEqual(self.service.current_evidence([evidence]), [])
        self.assertIsNone(self.service.content(row["id"]))
        self.assertTrue(self.store.original_path(row["id"]).is_file(), "withdrawal is not physical erasure")
        with self.assertRaises(DocumentWithdrawn):
            self.store.set_stage(row["id"], "failed", "late worker", state="failed")
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(select(self.chunks.c.searchable)).scalar_one(), False)
            self.assertEqual(len(connection.execute(select(self.service.lexical)).all()), 1)
        self.assertEqual(len([event for event in self.store.get(row["id"])["events"] if event["stage"] == "withdrawn"]), 1)
        with self.assertRaisesRegex(ResourceError, "只能重试"):
            self.service.retry(row["id"])
        duplicate, created = self.store.create("new-name.txt", "business_rules", self.store.original_path(row["id"]).read_bytes(), "text/plain")
        self.assertFalse(created)
        self.assertEqual(duplicate["state"], "withdrawn")

    def test_withdrawal_during_indexing_fences_final_publication(self):
        row = self.create()
        waiting, release = threading.Event(), threading.Event()
        original_stage = self.store.set_stage
        def stage(*args, **kwargs):
            original_stage(*args, **kwargs)
            if args[1] == "indexing":
                waiting.set()
                if not release.wait(15): raise RuntimeError("test release timed out")
        def add_documents(chunks, ids):
            with self.engine.begin() as connection:
                connection.execute(self.chunks.insert(), [{"langchain_id": uuid.UUID(key), "content": item.page_content,
                    "document_id": row["id"], "scope": row["scope"], "embedding_model": settings.EMBEDDING_MODEL,
                    "searchable": False, "langchain_metadata": item.metadata} for key, item in zip(ids, chunks)])
        self.service.vectors.add_documents.side_effect = add_documents
        with patch.object(self.store, "set_stage", side_effect=stage), ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.service.process, row["id"])
            try:
                self.assertTrue(waiting.wait(10), "worker did not reach indexing")
                self.service.withdraw(row["id"], expected_sha256=row["sha256"], reason="quality_issue")
            finally:
                release.set()
            future.result(timeout=10)
        self.assertEqual(self.store.get(row["id"])["state"], "withdrawn")
        with self.engine.connect() as connection:
            self.assertFalse(any(connection.execute(select(self.chunks.c.searchable)).scalars()))
        self.assertEqual(self.service.retrieve(query="金额", scope="all", top_k=5), [])

    def test_ordinary_ingestion_can_publish_then_withdraw_without_erasing_original(self):
        row = self.create()
        def add_documents(chunks, ids):
            with self.engine.begin() as connection:
                connection.execute(self.chunks.insert(), [{"langchain_id": uuid.UUID(key), "content": item.page_content,
                    "document_id": row["id"], "scope": row["scope"], "embedding_model": settings.EMBEDDING_MODEL,
                    "searchable": False, "langchain_metadata": item.metadata} for key, item in zip(ids, chunks)])
        self.service.vectors.add_documents.side_effect = add_documents
        self.service.process(row["id"])
        self.assertEqual(self.store.get(row["id"])["state"], "ready")
        self.assertEqual(len(self.service.retrieve(query="金额", scope="all", top_k=5)), 1)
        self.service.withdraw(row["id"], expected_sha256=row["sha256"], reason="superseded")
        self.assertEqual(self.service.retrieve(query="金额", scope="all", top_k=5), [])
        self.assertTrue(self.store.original_path(row["id"]).is_file())

    def test_graph_withdrawal_during_generation_suppresses_answer_and_original_evidence(self):
        row = self.create()
        self.store.set_stage(row["id"], "ready", "ready", state="ready")
        evidence = self.add_chunk(row["id"])
        runtime = Mock()
        def complete(**kwargs):
            if "statements" in kwargs.get("instructions", ""):
                self.service.withdraw(row["id"], expected_sha256=row["sha256"], reason="incorrect")
                return '{"statements":[{"text":"金额有误须核对原始指令。","supports":[{"citation":1,"quote":"金额有误须核对原始指令"}]}]}'
            return '{"intent":"rule","needs_clarification":false,"queries":[]}'
        runtime.complete.side_effect = complete
        # Keep the real graph/runtime stages and PostgreSQL lifecycle, replacing
        # only relevance assessment to isolate the publication-time race.
        evaluation = SimpleNamespace(assessment=SimpleNamespace(missing=[], relevant=True, sufficient=True, rewrite=""),
            selected=[evidence], warnings=[], coverage={}, stop_reason="")
        with patch("app.answer_graph.assess_context", return_value=evaluation):
            result = build_answer_graph(self.service, runtime).invoke({"query":"金额不对如何核查", "scope":"business_rules", "top_k":5,
                "attempts":0, "warnings":[]})["result"]
        self.assertEqual(self.store.get(row["id"])["state"], "withdrawn")
        self.assertEqual(result["stop_reason"], "source_withdrawn")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["grounding"], "insufficient")
        self.assertEqual(result["context_coverage"]["status"], "invalidated_by_source_change")
        self.assertNotIn("须核对原始指令", result["answer"])

    def test_evidence_only_graph_rechecks_after_assessment_and_cannot_claim_sufficiency(self):
        row = self.create()
        self.store.set_stage(row["id"], "ready", "ready", state="ready")
        evidence = self.add_chunk(row["id"])
        runtime = Mock()
        runtime.complete.return_value = '{"intent":"rule","queries":[]}'
        def assess(**kwargs):
            self.service.withdraw(row["id"], expected_sha256=row["sha256"], reason="incorrect")
            return SimpleNamespace(assessment=SimpleNamespace(missing=[], relevant=True, sufficient=True, rewrite=""),
                selected=[evidence], warnings=[], coverage={}, stop_reason="")
        with patch("app.answer_graph.assess_context", side_effect=assess):
            result = build_answer_graph(self.service, runtime, generate_answer=False).invoke({"query":"金额不对如何核查", "scope":"business_rules", "top_k":5,
                "attempts":0, "warnings":[]})["result"]
        self.assertEqual(result["stop_reason"], "source_withdrawn")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["source_status"]["knowledge_base"], "changed")
        self.assertTrue(result["missing"])
        self.assertNotIn("answer", result)
