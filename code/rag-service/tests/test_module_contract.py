import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.ragflow import RAGFlowError


class ModuleContractTests(unittest.TestCase):
    def test_service_identity_is_available_on_health_and_rejected_requests(self):
        client = TestClient(app)
        try:
            with patch.object(settings, "SERVICE_TOKEN", "synthetic-service-token"):
                health = client.get("/health")
                self.assertEqual(health.json()["api_contract_version"], "1.3.2")
                rejected = client.get("/api/v1/capabilities")
                self.assertEqual(rejected.status_code, 401)
                self.assertEqual(rejected.headers["x-rag-contract-version"], "1.3.2")
                self.assertEqual(health.headers["x-rag-service-version"], health.json()["service_version"])
                self.assertNotIn("synthetic-service-token", health.text + rejected.text)
        finally:
            client.close()

    def test_answer_and_retrieval_requests_reject_implicit_session_identity(self):
        client = TestClient(app)
        headers = {"Authorization": "Bearer synthetic-service-token"}
        try:
            with patch.object(settings, "SERVICE_TOKEN", "synthetic-service-token"):
                for path in ("/api/v1/answers", "/api/v1/answers/stream", "/api/v1/retrievals"):
                    with self.subTest(path=path):
                        response = client.post(path, headers=headers, json={
                            "query": "合成查询", "session_id": "synthetic-session",
                            "request_id": "synthetic-request",
                        })
                        self.assertEqual(response.status_code, 422)
                        self.assertIn("session_id", response.text)
                        self.assertIn("request_id", response.text)
        finally:
            client.close()

    def test_existing_query_consumers_keep_original_evidence_shape_and_safe_errors(self):
        client = TestClient(app)
        headers = {"Authorization": "Bearer synthetic-service-token"}
        try:
            with patch.object(settings, "SERVICE_TOKEN", "synthetic-service-token"), patch("app.main._retrieve_evidence") as retrieve:
                retrieve.return_value = [{"content": "支付指令 5000 元金额待核对；合成资料。", "document_id": "synthetic-id",
                    "document_keyword": "synthetic.txt", "page_num": None, "similarity": None}]
                response = client.post("/api/v1/query", json={"query": "金额有误", "scope": "business_rules", "top_k": 5}, headers=headers)
                self.assertEqual(response.status_code, 200)
                item = response.json()["evidence"][0]
                self.assertEqual(item["document_id"], "synthetic-id")
                self.assertIn("5000", item["content"])
                self.assertIsNone(item["page"])
                self.assertIsNone(item["score"])
                retrieve.side_effect = RAGFlowError("SYNTHETIC-UPSTREAM-SECRET-MUST-NOT-ESCAPE")
                failure = client.post("/api/v1/query", json={"query": "金额有误", "scope": "business_rules"}, headers=headers)
                self.assertEqual(failure.status_code, 502)
                self.assertIsInstance(failure.json()["detail"], str)
                self.assertNotIn("SYNTHETIC-UPSTREAM-SECRET", failure.text)
        finally:
            client.close()
