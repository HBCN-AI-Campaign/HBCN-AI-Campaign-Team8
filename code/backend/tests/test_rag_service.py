"""RAG 服务适配层与助手证据组合的单元测试（不依赖真实 rag-service）。"""
import unittest
from unittest.mock import patch

import httpx

from app.assistant_service import _rag_search
from app.config import settings
from app.rag_service import RAGClient, RAGServiceError, RAGServiceNotConfiguredError


class RAGClientTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "RAG_BASE_URL": settings.RAG_BASE_URL,
            "RAG_SERVICE_TOKEN": settings.RAG_SERVICE_TOKEN,
            "RAG_REQUEST_TIMEOUT": settings.RAG_REQUEST_TIMEOUT,
        }
        settings.RAG_BASE_URL = "http://rag-service.test"
        settings.RAG_SERVICE_TOKEN = "service-token"
        settings.RAG_REQUEST_TIMEOUT = 10.0

    def tearDown(self):
        for key, value in self.values.items():
            setattr(settings, key, value)

    def test_not_configured_raises(self):
        settings.RAG_BASE_URL = ""
        with self.assertRaises(RAGServiceNotConfiguredError):
            RAGClient().query(query="提款用途")

    def test_configured_flag(self):
        settings.RAG_BASE_URL = ""
        self.assertFalse(RAGClient().configured)
        settings.RAG_BASE_URL = "http://rag-service.test"
        self.assertTrue(RAGClient().configured)

    def test_knowledge_base_maps_to_two_scopes_and_merges(self):
        calls = []

        def fake_post(path, payload):
            calls.append((path, payload))
            if payload["scope"] == "business_rules":
                return {"evidence": [{"content": "业务规则片段", "document_name": "rules.xlsx"}], "warnings": []}
            return {"evidence": [{"content": "方案片段", "document_name": "design.docx"}], "warnings": ["w1"]}

        with patch.object(RAGClient, "_post", side_effect=fake_post):
            result = RAGClient().query(query="提款用途", scope="knowledge_base", top_k=6)

        self.assertEqual([c[1]["scope"] for c in calls], ["business_rules", "project_design"])
        self.assertEqual(len(result["evidence"]), 2)
        self.assertEqual(result["evidence"][0]["document_name"], "rules.xlsx")
        self.assertEqual(result["warnings"], ["w1"])

    def test_duplicate_evidence_deduped_across_scopes(self):
        shared = {"content": "同一片段", "document_id": "doc-1", "document_name": "x"}

        def fake_post(path, payload):
            return {"evidence": [dict(shared)], "warnings": []}

        with patch.object(RAGClient, "_post", side_effect=fake_post):
            result = RAGClient().query(query="q", scope="knowledge_base")

        self.assertEqual(len(result["evidence"]), 1)

    def test_task_documents_returns_empty_without_http_call(self):
        with patch.object(RAGClient, "_post", side_effect=AssertionError("不应发起 HTTP")):
            result = RAGClient().query(query="q", scope="task_documents")
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["warnings"])

    def test_http_error_wraps_as_rag_service_error(self):
        with patch("app.rag_service.httpx.post", side_effect=httpx.ConnectError("boom")):
            with self.assertRaises(RAGServiceError):
                RAGClient().query(query="q")

    def test_retrieve_calls_agentic_evidence_endpoint(self):
        response = {
            "query": "提款用途",
            "scope": "all",
            "sources": [{"content": "业务规则片段", "document_id": "doc-1", "document_name": "rules.pdf"}],
            "warnings": [],
            "retrieval_rounds": 2,
            "evidence_status": "sufficient",
            "stop_reason": "sufficient",
            "source_status": {"knowledge_base": "ok"},
            "rerank_status": "not_run",
            "context_coverage": {},
            "legal_applicability": {},
        }
        calls = []

        def fake_post(path, payload):
            calls.append((path, payload))
            return response

        with patch.object(RAGClient, "_post", side_effect=fake_post):
            result = RAGClient().retrieve(query="提款用途")

        self.assertEqual(calls[0][0], "/api/v1/retrievals")
        self.assertEqual(calls[0][1]["sources"], ["knowledge_base"])
        self.assertEqual(result["evidence"][0]["document_id"], "doc-1")
        self.assertEqual(result["evidence_status"], "sufficient")


class RagSearchMergeTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "RAG_BASE_URL": settings.RAG_BASE_URL,
            "RAG_SERVICE_TOKEN": settings.RAG_SERVICE_TOKEN,
        }
        settings.RAG_SERVICE_TOKEN = "service-token"

    def tearDown(self):
        for key, value in self.values.items():
            setattr(settings, key, value)

    def test_returns_local_only_when_rag_not_configured(self):
        settings.RAG_BASE_URL = ""
        context = {
            "results": [{"rule_id": "R04", "rule_name": "币种", "status": "fail", "why": "币种不符", "suggestion": ""}],
            "documents": [],
        }
        hits = _rag_search(context, "币种")
        self.assertEqual([h["type"] for h in hits], ["rule"])

    def test_merges_local_and_rag_evidence_when_configured(self):
        settings.RAG_BASE_URL = "http://rag-service.test"
        context = {
            "task": {"task_code": "T1"},
            "results": [{"rule_id": "R04", "rule_name": "币种", "status": "fail", "why": "币种不符", "suggestion": ""}],
            "documents": [],
        }
        with patch(
            "app.rag_service.RAGClient.retrieve",
            return_value={
                "evidence": [{"content": "规则片段", "document_id": "doc-1", "document_name": "rules.xlsx", "page": 3}],
                "warnings": [],
            },
        ):
            hits = _rag_search(context, "币种")

        types = [h["type"] for h in hits]
        self.assertIn("rule", types)
        self.assertIn("knowledge", types)
        knowledge = next(h for h in hits if h["type"] == "knowledge")
        self.assertEqual(knowledge["source"], "rules.xlsx")
        self.assertEqual(knowledge["page"], 3)

    def test_rag_failure_falls_back_to_local(self):
        settings.RAG_BASE_URL = "http://rag-service.test"
        context = {
            "results": [{"rule_id": "R04", "rule_name": "币种", "status": "fail", "why": "币种不符", "suggestion": ""}],
            "documents": [],
        }
        with patch("app.rag_service.RAGClient.retrieve", side_effect=RuntimeError("down")):
            hits = _rag_search(context, "币种")
        self.assertEqual([h["type"] for h in hits], ["rule"])


if __name__ == "__main__":
    unittest.main()
