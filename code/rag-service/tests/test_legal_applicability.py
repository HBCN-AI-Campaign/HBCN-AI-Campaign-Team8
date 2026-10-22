import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.answer_graph import build_answer_graph
from app.config import settings
from app.legal_applicability import LegalContext, check_legal_applicability
from app.main import app


CONTEXT = {"business_date": "2024-06-01", "jurisdiction": "CN", "subject_type": "commercial_bank", "business_type": "overseas_loan"}


def item():
    return {"document_id": "synthetic-law", "chunk_id": "clause1", "document_keyword": "synthetic-law.txt",
            "content": "合成条款：贷款须核对支持单据金额。", "metadata": {"scope": "law", "jurisdiction": "CN", "timeliness": "现行有效"}}


def review(**extra):
    value = {"review_id": "synthetic-review", "document_id": "synthetic-law", "chunk_id": "clause1",
             "content_sha256": hashlib.sha256(item()["content"].encode()).hexdigest(), "source_version": None, "state": "approved",
             "reviewed_by": "synthetic-curator", "reviewed_at": "2020-01-01T00:00:00Z", "review_expires_on": "2099-12-31",
             "valid_from": "2024-01-01", "valid_to_exclusive": "2025-01-01", "jurisdictions": ["CN"],
             "subject_types": ["commercial_bank"], "business_types": ["overseas_loan"],
             "authority_url": "https://example.test/synthetic-only"}
    return {**value, **extra}


class ApplicabilityTests(unittest.TestCase):
    def run_check(self, reviews, *, evidence=None, context=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reviews.json"
            path.write_text(json.dumps({"version": 1, "reviews": reviews}), encoding="utf-8")
            with patch.object(settings, "RAG_LEGAL_REVIEW_FILE", str(path)):
                return check_legal_applicability(evidence or [item()], purpose="case_assessment", context=context or CONTEXT, today="2026-10-22")

    def test_general_reference_is_not_case_approval(self):
        report, gaps = check_legal_applicability([item()])
        self.assertEqual(report["status"], "reference_only")
        self.assertEqual(report["evidence"][0]["status"], "unverified")
        self.assertFalse(gaps)

    def test_explicit_context_and_separate_review_are_required(self):
        report, gaps = check_legal_applicability([item()], purpose="case_assessment")
        self.assertEqual(report["status"], "context_required")
        self.assertTrue(gaps)
        value = item()
        value["metadata"].update(legal_review="approved", verified=True)
        with patch.object(settings, "RAG_LEGAL_REVIEW_FILE", ""):
            report, gaps = check_legal_applicability([value], purpose="case_assessment", context=CONTEXT)
        self.assertEqual(report["status"], "review_required")

    def test_date_jurisdiction_subject_business_and_revocation_gates(self):
        for changed in ({"business_date": "2023-12-31"}, {"business_date": "2025-01-01"},
                        {"jurisdiction": "HK"}, {"subject_type": "consumer"}, {"business_type": "consumer_loan"}):
            with self.subTest(changed=changed):
                report, gaps = self.run_check([review()], context={**CONTEXT, **changed})
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(gaps)
        for changed in ({"state": "revoked"}, {"review_expires_on": "2021-01-01"}):
            report, gaps = self.run_check([review(**changed)])
            self.assertEqual(report["status"], "blocked")

    def test_matching_historical_interval_can_pass_without_assuming_current_law(self):
        report, gaps = self.run_check([review()])
        self.assertEqual(report["status"], "reviewed_constraints_match")
        self.assertFalse(gaps)
        report, gaps = self.run_check([review()], context={**CONTEXT, "business_date": "2024-01-01"})
        self.assertFalse(gaps)  # inclusive start, exclusive end

    def test_hash_change_and_conflicting_reviews_block(self):
        changed = item()
        changed["content"] += "新增例外"
        for reviews, evidence in (([review()], [changed]), ([review(), review(review_id="conflict")], [item()])):
            report, gaps = self.run_check(reviews, evidence=evidence)
            self.assertEqual(report["status"], "blocked")

    def test_window_uses_parent_hash_binding(self):
        value = item()
        parent_hash = hashlib.sha256(value["content"].encode()).hexdigest()
        value["content"] = "贷款须核对"
        value["metadata"]["excerpt"] = {"parent_chunk_id": "clause1", "parent_content_sha256": parent_hash}
        report, gaps = self.run_check([review()], evidence=[value])
        self.assertFalse(gaps)

    def test_unknown_dates_or_bad_registry_do_not_mean_open_ended(self):
        value = review()
        del value["valid_to_exclusive"]
        report, gaps = self.run_check([value])
        self.assertEqual(report["status"], "review_required")
        report, gaps = self.run_check([review(valid_to_exclusive=None)])
        self.assertFalse(gaps)
        with self.assertRaises(ValueError):
            LegalContext.model_validate({**CONTEXT, "business_date": "2024-02-31"})

    def test_case_graph_keeps_partial_law_evidence_but_not_sufficient(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [item()]
        runtime.complete.side_effect = ['{"intent":"law","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        with patch.object(settings, "RAG_LEGAL_REVIEW_FILE", ""):
            result = build_answer_graph(engine, runtime, generate_answer=False).invoke(
                {"query": "本案是否可用该规定？", "scope": "law", "top_k": 5, "purpose": "case_assessment", "legal_context": CONTEXT})["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["legal_applicability"]["status"], "review_required")
        self.assertTrue(result["sources"])
        self.assertTrue(result["missing"])

    def test_http_rejects_impossible_context_and_approval_override(self):
        with patch.object(settings, "SERVICE_TOKEN", "test"):
            for context in ({**CONTEXT, "business_date": "2024-02-31"}, {**CONTEXT, "approved": True}):
                response = TestClient(app).post("/api/v1/retrievals", headers={"Authorization": "Bearer test"},
                    json={"query": "本案法规", "purpose": "case_assessment", "legal_context": context})
                self.assertEqual(response.status_code, 422)

    def test_law_case_cannot_skip_legal_evidence_by_selecting_other_sources(self):
        other = item()
        other["metadata"] = {"scope": "business_rules"}
        report, gaps = check_legal_applicability([other], purpose="case_assessment", context=CONTEXT, require_legal=True)
        self.assertEqual(report["status"], "legal_evidence_required")
        self.assertTrue(gaps)
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [other]
        runtime.complete.side_effect = ['{"intent":"law","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(
            {"query": "本案法规", "scope": "law", "top_k": 5, "purpose": "case_assessment", "legal_context": CONTEXT})["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["legal_applicability"]["status"], "legal_evidence_required")
        for call in runtime.complete.call_args_list:
            self.assertIn("2024-06-01", call.kwargs["instructions"])
            self.assertIn("commercial_bank", call.kwargs["instructions"])

    def test_registry_revocation_is_not_hidden_by_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reviews.json"
            with patch.object(settings, "RAG_LEGAL_REVIEW_FILE", str(path)):
                for state, expected in (("approved", "reviewed_constraints_match"), ("revoked", "blocked")):
                    path.write_text(json.dumps({"version": 1, "reviews": [review(state=state)]}), encoding="utf-8")
                    report, _ = check_legal_applicability([item()], purpose="case_assessment", context=CONTEXT)
                    self.assertEqual(report["status"], expected)

    def test_provider_status_version_change_invalidates_same_body_review(self):
        value = item()
        value["metadata"]["version"] = "provider-metadata:current"
        report, gaps = self.run_check([review(source_version="provider-metadata:current")], evidence=[value])
        self.assertFalse(gaps)
        value["metadata"]["version"] = "provider-metadata:repealed"
        report, gaps = self.run_check([review(source_version="provider-metadata:current")], evidence=[value])
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(gaps)

    def test_answer_preserves_partial_reference_without_generating_case_conclusion(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [item()]
        runtime.complete.side_effect = ['{"intent":"law","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        with patch.object(settings, "RAG_LEGAL_REVIEW_FILE", ""):
            result = build_answer_graph(engine, runtime).invoke(
                {"query": "本案法规", "scope": "law", "top_k": 5, "purpose": "case_assessment", "legal_context": CONTEXT})["result"]
        self.assertEqual(runtime.complete.call_count, 2)
        self.assertEqual(result["grounding"], "insufficient")
        self.assertTrue(result["sources"])
        self.assertTrue(result["missing"])
        self.assertEqual(result["answer_verification"]["status"], "not_run")

    def test_explicit_case_purpose_requires_legal_evidence_even_when_planner_calls_it_rule(self):
        other = item()
        other["metadata"] = {"scope": "business_rules"}
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [other]
        runtime.complete.side_effect = ['{"intent":"rule","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(
            {"query": "本案判断", "scope": "all", "top_k": 5, "purpose": "case_assessment", "legal_context": CONTEXT})["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["legal_applicability"]["status"], "legal_evidence_required")


if __name__ == "__main__":
    unittest.main()
