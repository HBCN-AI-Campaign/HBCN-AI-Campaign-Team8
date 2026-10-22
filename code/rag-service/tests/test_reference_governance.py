import hashlib
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import sql_engine
from app.main import app
from app.reference_contracts import ReferenceCandidate, ReferenceReview, ReferenceSearch, ReferenceWithdrawal
from app.reference_security import ReferenceForbidden, ReferencePrincipal
from app.reference_store import ReferenceConflict, ReferenceStore, get_reference_store


AUTHOR = ReferencePrincipal("synthetic-author", frozenset({"team_alpha"}), frozenset({"author", "reader"}))
REVIEWER = ReferencePrincipal("synthetic-reviewer", frozenset({"team_alpha"}), frozenset({"reviewer", "reader"}))
OTHER = ReferencePrincipal("synthetic-other", frozenset({"team_beta"}), frozenset({"reviewer", "reader", "author"}))


def candidate(now, logical_id="CASE-001", **overrides):
    payload = {"namespace": "team_alpha", "logical_id": logical_id, "kind": "case_reference", "product": "synthetic-loan",
        "jurisdiction": "synthetic-jurisdiction", "issue_type": "payment_amount", "policy_version": "synthetic-policy-v1",
        "business_date": (now - timedelta(days=10)).date(), "source_reviewed_at": now - timedelta(days=1),
        "retain_until": now + timedelta(days=10), "facts_summary": "合成案例的支付指令金额有误，不是真实业务资料。",
        "handling": "合成处理步骤：先核对支持资料，再按对应政策处理。", "conclusion_status": "confirmed",
        "evidence": [{"source_id": "synthetic-source", "source_version": "v1", "content_sha256": "a" * 64, "relation": "supporting"}],
        "redaction_confirmed": True, "sharing_authorized": True, "leakage_group_id": "SYNTHETIC-GROUP-" + logical_id,
        **overrides}
    return ReferenceCandidate.model_validate(payload)


def review(row):
    return ReferenceReview(expected_revision=row["revision"], content_sha256=row["content_sha256"])


def search(**overrides):
    return ReferenceSearch(namespace="team_alpha", kind="case_reference", query="支付指令金额", product="synthetic-loan",
        jurisdiction="synthetic-jurisdiction", issue_type="payment_amount", policy_version="synthetic-policy-v1", **overrides)


class ReferenceGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.time = self.now
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.store = ReferenceStore(self.engine, clock=lambda: self.time)
        self.store.apply_schema()

    def tearDown(self):
        self.engine.dispose()

    def published(self, logical_id="CASE-001", **overrides):
        draft = self.store.create(AUTHOR, candidate(self.now, logical_id, **overrides))
        return self.store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))

    def memory(self):
        first, second = self.published(), self.published("CASE-002")
        draft = self.store.create(AUTHOR, candidate(self.now, "MEMORY-001", kind="experience_memory", memory_type="checklist",
            parent_version_ids=[first["id"], second["id"]]))
        return first, second, self.store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))

    def test_unreviewed_private_and_cross_policy_references_do_not_leak(self):
        draft = self.store.create(AUTHOR, candidate(self.now))
        self.assertEqual(self.store.search(AUTHOR, search()), [])
        with self.assertRaises(LookupError):
            self.store.get(AUTHOR, "team_alpha", draft["id"])
        with self.assertRaises(ReferenceForbidden):
            self.store.get(OTHER, "team_alpha", draft["id"], inspect_candidate=True)
        row = self.store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))
        self.assertEqual(self.store.search(AUTHOR, search())[0]["id"], row["id"])
        query = search().model_copy(update={"policy_version": "synthetic-policy-v2"})
        self.assertEqual(self.store.search(AUTHOR, query), [])
        self.assertIn("not a rule", row["use_limit"])
        with self.assertRaises(ReferenceForbidden):
            self.store.create(OTHER, candidate(self.now, "CASE-003"))

    def test_four_eyes_hash_binding_roles_and_unknown_scope_are_required(self):
        draft = self.store.create(AUTHOR, candidate(self.now))
        same_person = ReferencePrincipal(AUTHOR.subject, AUTHOR.namespaces, frozenset({"reviewer"}))
        with self.assertRaises(ReferenceConflict):
            self.store.approve(same_person, "team_alpha", draft["id"], review(draft))
        with self.assertRaises(ReferenceForbidden):
            self.store.approve(AUTHOR, "team_alpha", draft["id"], review(draft))
        with self.assertRaises(ReferenceConflict):
            self.store.approve(REVIEWER, "team_alpha", draft["id"], ReferenceReview(expected_revision=1, content_sha256="b" * 64))
        for field, value in (("redaction_confirmed", False), ("sharing_authorized", False), ("evaluation_only", True),
                             ("conclusion_status", "disputed"), ("policy_version", "unknown")):
            with self.subTest(field=field):
                draft = self.store.create(AUTHOR, candidate(self.now, "CASE-" + field.upper(), **{field: value}))
                with self.assertRaises(ReferenceConflict):
                    self.store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))

    def test_memory_requires_distinct_current_matching_sources_and_bounded_retention(self):
        first, second = self.published(), self.published("CASE-002")
        for changes in ({"policy_version": "other"}, {"retain_until": self.now + timedelta(days=11)},
                        {"parent_version_ids": [first["id"], str(uuid4())]}):
            payload = {"kind": "experience_memory", "memory_type": "query_strategy", "parent_version_ids": [first["id"], second["id"]], **changes}
            with self.subTest(changes=changes), self.assertRaises((ReferenceConflict, LookupError)):
                self.store.create(AUTHOR, candidate(self.now, "MEMORY-001", **payload))
        with self.engine.connect() as connection:
            self.assertEqual(len(connection.execute(select(self.store.versions)).all()), 2)
            self.assertEqual(len(connection.execute(select(self.store.dependencies)).all()), 0)

    def test_revoking_source_synchronously_invalidates_derived_memory_and_stale_approvals(self):
        first, _, memory = self.memory()
        memory_query = search().model_copy(update={"kind": "experience_memory"})
        self.assertEqual(self.store.search(AUTHOR, memory_query)[0]["id"], memory["id"])
        self.store.withdraw(REVIEWER, "team_alpha", first["id"], ReferenceWithdrawal(**review(first).model_dump(), reason="permission_changed"))
        self.assertEqual(self.store.search(AUTHOR, memory_query), [])
        with self.assertRaises(LookupError):
            self.store.get(AUTHOR, "team_alpha", memory["id"])
        with self.assertRaises(ReferenceConflict):
            self.store.approve(REVIEWER, "team_alpha", memory["id"], review(memory))
        events = self.store.audit(REVIEWER, "team_alpha")
        self.assertIn("source_invalidated", [event["action"] for event in events])
        self.assertNotIn("合成案例", json.dumps(events, default=str))

    def test_new_version_supersedes_old_and_invalidates_old_derived_experience(self):
        first, _, memory = self.memory()
        replacement = self.published("CASE-001", handling="合成的新政策处理流程，必须重新复核后才能发布。")
        self.assertEqual(replacement["version"], 2)
        self.assertEqual(self.store.get(REVIEWER, "team_alpha", first["id"], inspect_candidate=True)["state"], "superseded")
        self.assertEqual(self.store.get(REVIEWER, "team_alpha", memory["id"], inspect_candidate=True)["state"], "withdrawn")
        with self.assertRaises(LookupError):
            self.store.get(AUTHOR, "team_alpha", first["id"])

    def test_expiry_blocks_reads_and_purge_erases_text_preserving_monotonic_audit_versions(self):
        first, _, memory = self.memory()
        self.time += timedelta(days=11)
        self.assertEqual(self.store.search(AUTHOR, search()), [])
        with self.assertRaises(LookupError):
            self.store.get(REVIEWER, "team_alpha", first["id"], inspect_candidate=True)
        result = self.store.purge_expired(REVIEWER, "team_alpha")
        self.assertEqual(result["erased_versions"], 3)
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.store.versions)).mappings().all()
        self.assertTrue(all(row["payload"] == {} and not row["search_text"] and row["state"] == "expired" for row in rows))
        self.assertTrue(all(row["revision"] >= 3 for row in rows))
        self.assertEqual(self.store.purge_expired(REVIEWER, "team_alpha")["erased_versions"], 0)
        self.assertTrue(self.store.audit(REVIEWER, "team_alpha"))

    def test_holdout_exclusion_also_excludes_memories_derived_from_the_case(self):
        first, second, _ = self.memory()
        group = first["content"]["leakage_group_id"]
        self.assertEqual([row["id"] for row in self.store.search(AUTHOR, search(excluded_leakage_groups=[group]))], [second["id"]])
        query = search(excluded_leakage_groups=[group]).model_copy(update={"kind": "experience_memory"})
        self.assertEqual(self.store.search(AUTHOR, query), [])


class ReferenceAPITests(unittest.TestCase):
    def setUp(self):
        ReferenceGovernanceTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Path(self.temp.name) / "principals.json"
        self.author_key, self.reviewer_key = "synthetic-author-key-" + "a" * 32, "synthetic-reviewer-key-" + "b" * 32
        self.entries = [{"subject": principal.subject, "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                         "namespaces": list(principal.namespaces), "roles": list(principal.roles),
                         "valid_until": (self.now + timedelta(days=1)).isoformat()}
                        for principal, key in ((AUTHOR, self.author_key), (REVIEWER, self.reviewer_key))]
        self.registry.write_text(json.dumps({"principals": self.entries}), encoding="utf-8")
        self.patches = [patch.object(settings, "SERVICE_TOKEN", "synthetic-service"),
                        patch.object(settings, "RAG_REFERENCES_ENABLED", True),
                        patch.object(settings, "RAG_REFERENCE_PRINCIPALS_FILE", str(self.registry))]
        for item in self.patches:
            item.start()
        app.dependency_overrides[get_reference_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_reference_store, None)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()
        ReferenceGovernanceTests.tearDown(self)

    def headers(self, key=None):
        result = {"Authorization": "Bearer synthetic-service"}
        if key:
            result["X-Reference-Key"] = key
        return result

    def test_service_token_alone_never_grants_case_or_memory_access(self):
        with patch.object(settings, "RAG_REFERENCES_ENABLED", False):
            self.assertEqual(self.client.post("/api/v1/references/search", json=search().model_dump(), headers=self.headers(self.author_key)).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/references/search", json=search().model_dump(), headers=self.headers()).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/references/search", json=search().model_dump(), headers={"X-Reference-Key": self.author_key}).status_code, 401)

    def test_api_candidate_review_search_content_and_registry_revocation(self):
        response = self.client.post("/api/v1/references/candidates", json=candidate(self.now).model_dump(mode="json"), headers=self.headers(self.author_key))
        self.assertEqual(response.status_code, 201, response.text)
        draft = response.json()
        path = f'/api/v1/references/versions/{draft["id"]}'
        inspect_result = self.client.get(path, params={"namespace": "team_alpha", "inspect_candidate": True}, headers=self.headers(self.reviewer_key))
        self.assertEqual(inspect_result.status_code, 200)
        denied = self.client.post(path + "/approve", params={"namespace": "team_alpha"}, json=review(draft).model_dump(), headers=self.headers(self.author_key))
        self.assertEqual(denied.status_code, 403)
        approved = self.client.post(path + "/approve", params={"namespace": "team_alpha"}, json=review(draft).model_dump(), headers=self.headers(self.reviewer_key))
        self.assertEqual(approved.status_code, 200, approved.text)
        found = self.client.post("/api/v1/references/search", json=search().model_dump(), headers=self.headers(self.author_key))
        self.assertEqual(len(found.json()["references"]), 1)
        self.assertFalse(found.json()["normative_evidence"])
        self.assertEqual(found.headers["cache-control"], "no-store")
        cross = self.client.get(path, params={"namespace": "team_beta"}, headers=self.headers(self.author_key))
        self.assertEqual(cross.status_code, 403)
        body = {**candidate(self.now, "CASE-002").model_dump(mode="json"), "reviewer": "forged"}
        self.assertEqual(self.client.post("/api/v1/references/candidates", json=body, headers=self.headers(self.author_key)).status_code, 422)
        self.registry.write_text(json.dumps({"principals": [self.entries[1]]}), encoding="utf-8")
        self.assertEqual(self.client.get(path, params={"namespace": "team_alpha"}, headers=self.headers(self.author_key)).status_code, 401)
        expired = {**self.entries[1], "valid_until": (self.now - timedelta(seconds=1)).isoformat()}
        self.registry.write_text(json.dumps({"principals": [expired]}), encoding="utf-8")
        self.assertEqual(self.client.get(path, params={"namespace": "team_alpha"}, headers=self.headers(self.reviewer_key)).status_code, 401)
        self.registry.write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(path, params={"namespace": "team_alpha"}, headers=self.headers(self.reviewer_key)).status_code, 503)


@unittest.skipUnless(os.environ.get("HBCN_TEST_POSTGRES") == "1", "explicit opt-in required for isolated PostgreSQL reference schema")
class ReferencePostgresTests(unittest.TestCase):
    def test_real_fts_transactions_publication_race_and_source_revocation(self):
        engine, schema = sql_engine(), "rag_ref_test_" + uuid4().hex
        self.assertRegex(schema, r"^rag_ref_test_[0-9a-f]{32}$")
        now = datetime.now(timezone.utc)
        store = ReferenceStore(engine, schema=schema, clock=lambda: now)
        try:
            with engine.begin() as connection:
                connection.execute(CreateSchema(schema))
            store.apply_schema()
            store.require_ready()
            self.assertIn("reference_fts_v1", {item["name"] for item in inspect(engine).get_indexes(store.versions.name, schema=schema)})
            def publish(logical_id):
                draft = store.create(AUTHOR, candidate(now, logical_id))
                return store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))
            first, second = publish("CASE-001"), publish("CASE-002")
            self.assertEqual(len(store.search(AUTHOR, search())), 2)
            approved_memory = store.create(AUTHOR, candidate(now, "MEMORY-APPROVED", kind="experience_memory", memory_type="checklist",
                parent_version_ids=[first["id"], second["id"]]))
            store.approve(REVIEWER, "team_alpha", approved_memory["id"], review(approved_memory))
            self.assertEqual(len(store.search(AUTHOR, search().model_copy(update={"kind": "experience_memory"}))), 1)
            group = first["content"]["leakage_group_id"]
            excluded = search(excluded_leakage_groups=[group]).model_copy(update={"kind": "experience_memory"})
            self.assertEqual(store.search(AUTHOR, excluded), [])
            with tempfile.TemporaryDirectory() as folder:
                key = "synthetic-pg-reader-key-" + "r" * 32
                registry = Path(folder) / "principals.json"
                registry.write_text(json.dumps({"principals": [{"subject": AUTHOR.subject, "namespaces": ["team_alpha"],
                    "roles": ["reader"], "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                    "valid_until": (now + timedelta(days=1)).isoformat()}]}), encoding="utf-8")
                app.dependency_overrides[get_reference_store] = lambda: store
                try:
                    with patch.object(settings, "SERVICE_TOKEN", "synthetic-pg-service"), \
                            patch.object(settings, "RAG_REFERENCES_ENABLED", True), \
                            patch.object(settings, "RAG_REFERENCE_PRINCIPALS_FILE", str(registry)):
                        # No lifespan context: do not initialize/recover the shared KB.
                        client = TestClient(app)
                        try:
                            response = client.post("/api/v1/references/search", json=search().model_dump(),
                                headers={"Authorization": "Bearer synthetic-pg-service", "X-Reference-Key": key})
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(len(response.json()["references"]), 2)
                        finally:
                            client.close()
                finally:
                    app.dependency_overrides.pop(get_reference_store, None)
            draft = store.create(AUTHOR, candidate(now, "MEMORY-001", kind="experience_memory", memory_type="checklist",
                parent_version_ids=[first["id"], second["id"]]))
            barrier = threading.Barrier(2)
            def approve_memory():
                barrier.wait(timeout=10)
                try:
                    return store.approve(REVIEWER, "team_alpha", draft["id"], review(draft))["state"]
                except ReferenceConflict:
                    return "rejected"
            def revoke_source():
                barrier.wait(timeout=10)
                return store.withdraw(REVIEWER, "team_alpha", first["id"], ReferenceWithdrawal(**review(first).model_dump(), reason="revoked"))["state"]
            with ThreadPoolExecutor(max_workers=2) as workers:
                pending = [workers.submit(approve_memory), workers.submit(revoke_source)]
                results = [future.result(timeout=25) for future in pending]
            self.assertIn(results[0], {"approved", "rejected"})
            self.assertEqual(results[1], "withdrawn")
            query = search().model_copy(update={"kind": "experience_memory"})
            self.assertEqual(store.search(AUTHOR, query), [])
            self.assertEqual(store.get(REVIEWER, "team_alpha", draft["id"], inspect_candidate=True)["state"], "withdrawn")
            with self.assertRaises(LookupError):
                store.get(AUTHOR, "team_alpha", first["id"])
        finally:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))


if __name__ == "__main__":
    unittest.main()
