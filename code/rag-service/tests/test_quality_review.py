import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.document_quality import QualityReview
from app.document_store import DocumentConflict
from app.main import app
from app.reference_security import ReferenceForbidden, ReferencePrincipal
import test_document_lifecycle as lifecycle


REVIEWER = ReferencePrincipal("synthetic-reviewer", frozenset({"business_rules"}), frozenset({"reviewer"}))


@unittest.skipUnless(os.environ.get("HBCN_TEST_POSTGRES") == "1", "opt-in for isolated quality PostgreSQL schema")
class QualityReviewPostgresTests(unittest.TestCase):
    # Reuse fixture functions without inheriting or collecting its test methods.
    setUp = lifecycle.DocumentLifecyclePostgresTests.setUp
    drop_schema = lifecycle.DocumentLifecyclePostgresTests.drop_schema
    create = lifecycle.DocumentLifecyclePostgresTests.create

    def pending(self):
        row = self.create()
        self.pages = [{"page": 1, "text": "金额 5000 USD 需核对。", "extraction": {"method": "ocr_service"}},
                      {"page": 2, "text": "", "extraction": {"method": "ocr_service"}}]
        with patch("app.postgres_engine.extract_pages", return_value=self.pages):
            self.service.process(row["id"])
        return self.store.get(row["id"])

    def action(self, row, **changes):
        report = row["provenance"]["quality_report"]
        return QualityReview(expected_sha256=row["sha256"], expected_parsed_sha256=report["parsed_sha256"],
            expected_report_sha256=report["report_sha256"], decision="approve", reason="source_compared", verified_units=[0, 1]).model_copy(update=changes)

    def test_pending_content_not_embedded_until_exact_review_and_uses_reviewed_text_without_reocr(self):
        row = self.pending()
        self.assertEqual(row["state"], "quality_review")
        self.service.vectors.add_documents.assert_not_called()
        self.assertEqual(self.service.retrieve(query="金额", scope="all", top_k=5), [])
        for changes in [{"expected_parsed_sha256": "0" * 64}, {"expected_sha256": "0" * 64},
                        {"expected_report_sha256": "0" * 64}, {"verified_units": [0]}, {"verified_units": [0, 0]}, {"reason": "unreadable"}]:
            with self.assertRaises(DocumentConflict):
                self.store.review_quality(row["id"], self.action(row, **changes), REVIEWER)
        outsider = ReferencePrincipal("other", frozenset({"law"}), frozenset({"reviewer"}))
        with self.assertRaises(ReferenceForbidden):
            self.store.review_quality(row["id"], self.action(row), outsider)
        self.store.review_quality(row["id"], self.action(row), REVIEWER)
        with self.assertRaises(DocumentConflict):
            self.store.review_quality(row["id"], self.action(row), REVIEWER)
        def add_documents(chunks, ids):
            with self.engine.begin() as connection:
                connection.execute(self.chunks.insert(), [{"langchain_id": uuid.UUID(key), "content": item.page_content,
                    "document_id": row["id"], "scope": row["scope"], "embedding_model": settings.EMBEDDING_MODEL,
                    "searchable": False, "langchain_metadata": item.metadata} for key, item in zip(ids, chunks)])
        self.service.vectors.add_documents.side_effect = add_documents
        with patch("app.postgres_engine.extract_pages", side_effect=AssertionError("approved OCR must not run again")):
            self.service.process(row["id"])
        current = self.store.get(row["id"])
        self.assertEqual(current["state"], "ready")
        self.assertEqual(current["pages"], self.pages)
        self.assertEqual(current["provenance"]["quality_approval"]["reviewer"], REVIEWER.subject)
        self.assertEqual(len(self.service.retrieve(query="金额", scope="all", top_k=5)), 1)

    def test_invalid_text_and_changed_original_are_never_embedded_and_withdrawn_review_is_blocked(self):
        row = self.create()
        with patch("app.postgres_engine.extract_pages", return_value=[{"page": 1, "text": "500\x000\ufffd"}]):
            self.service.process(row["id"])
        current = self.store.get(row["id"])
        self.assertEqual(current["state"], "quarantined")
        self.assertEqual(current["pages"], [])
        self.assertEqual(current["provenance"]["quality_report"]["status"], "quarantined")
        self.service.vectors.add_documents.assert_not_called()
        self.store.original_path(row["id"]).write_bytes(b"changed source")
        self.service.process(row["id"])
        self.assertEqual(self.store.get(row["id"])["state"], "failed")
        self.assertIn("摘要不一致", self.store.get(row["id"])["error"])
        # Restore synthetic content to produce another deterministic pending run.
        self.store.original_path(row["id"]).write_bytes("金额有误须核对原始指令。".encode())
        pending = self.pending()
        self.service.withdraw(pending["id"], expected_sha256=pending["sha256"], reason="incorrect")
        with self.assertRaises(DocumentConflict):
            self.store.review_quality(pending["id"], self.action(pending), REVIEWER)

    def test_http_review_requires_separate_live_scope_bound_key_and_rejects_forged_identity(self):
        row = self.pending()
        key = "synthetic-quality-review-key-" + "q" * 32
        registry = Path(self.folder.name) / "quality-principals.json"
        entry = {"subject": REVIEWER.subject, "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
            "namespaces": ["business_rules"], "roles": ["reviewer"], "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
        registry.write_text(json.dumps({"principals": [entry]}), encoding="utf-8")
        self.service.executor = Mock()
        headers = {"Authorization": "Bearer synthetic-quality-service", "X-Document-Review-Key": key}
        with patch.object(settings, "SERVICE_TOKEN", "synthetic-quality-service"), \
             patch.object(settings, "RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE", str(registry)), \
             patch("app.backend_api.postgres_engine", return_value=self.service):
            client = TestClient(app)
            try:
                path = f'/api/v1/documents/{row["id"]}'
                self.assertEqual(client.get(path + "/quality").status_code, 401)
                self.assertEqual(client.get(path + "/quality", headers={"Authorization": headers["Authorization"]}).status_code, 401)
                result = client.get(path + "/quality", headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(result.json()["pages"], self.pages)
                payload = self.action(row).model_dump()
                self.assertEqual(client.post(path + "/quality-review", json={**payload, "reviewer": "admin"}, headers=headers).status_code, 422)
                registry.write_text(json.dumps({"principals": [{**entry, "namespaces": ["law"]}]}), encoding="utf-8")
                self.assertEqual(client.post(path + "/quality-review", json=payload, headers=headers).status_code, 403)
                registry.write_text(json.dumps({"principals": [entry]}), encoding="utf-8")
                self.assertEqual(client.post(path + "/quality-review", json=payload, headers=headers).status_code, 202)
                # The accepted job still owns the one queue slot in this fixture.
                self.assertEqual(client.post(path + "/quality-review", json=payload, headers=headers).status_code, 503)
                self.service.executor.submit.assert_called_once()
                registry.write_text(json.dumps({"principals": [{**entry, "valid_until": "2020-01-01T00:00:00Z"}]}), encoding="utf-8")
                self.assertEqual(client.get(path + "/quality", headers=headers).status_code, 401)
            finally:
                client.close()

    def test_changed_parsed_units_invalidate_approval_and_rejection_never_enqueues(self):
        row = self.pending()
        old_action = self.action(row)
        self.store.review_quality(row["id"], old_action, REVIEWER)
        self.store.set_stage(row["id"], "quality_approved", "synthetic changed parser snapshot", pages=[
            {"page": 1, "text": "金额变更为 500 USD。", "extraction": {"method": "ocr_service"}}])
        self.service.process(row["id"])
        changed = self.store.get(row["id"])
        self.assertEqual(changed["state"], "quality_review")
        self.assertNotIn("quality_approval", changed["provenance"])
        self.service.vectors.add_documents.assert_not_called()
        with self.assertRaises(DocumentConflict):
            self.store.review_quality(row["id"], old_action, REVIEWER)
        self.service.executor = Mock()
        self.service.review_quality(row["id"], self.action(changed, decision="reject", reason="incorrect", verified_units=[]), REVIEWER)
        self.assertEqual(self.store.get(row["id"])["state"], "failed")
        self.service.executor.submit.assert_not_called()

    def test_legacy_ready_sources_are_hidden_until_explicit_recheck_and_withdrawal_cannot_be_rechecked(self):
        row = self.create()
        self.store.set_stage(row["id"], "ready", "synthetic legacy ready", state="ready")
        key = uuid.uuid4()
        with self.engine.begin() as connection:
            connection.execute(self.chunks.insert().values(langchain_id=key, document_id=row["id"], content="金额5000",
                scope="business_rules", embedding_model=settings.EMBEDDING_MODEL, searchable=True, langchain_metadata={}))
        self.assertEqual(self.service.current_evidence([{"document_id": row["id"], "chunk_id": str(key)}]), [])
        self.service.executor = Mock()
        pending = self.service.recheck_quality(row["id"], row["sha256"], REVIEWER)
        self.assertEqual(pending["state"], "queued")
        with self.engine.connect() as connection:
            self.assertFalse(connection.execute(select(self.chunks.c.searchable)).scalar_one())
        self.service.withdraw(row["id"], expected_sha256=row["sha256"], reason="incorrect")
        # Simulate completion of the scheduled slot; the queue itself is not run.
        self.service.slots.release()
        with self.assertRaises(DocumentConflict):
            self.service.recheck_quality(row["id"], row["sha256"], REVIEWER)
