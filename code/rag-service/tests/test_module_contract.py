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
                self.assertEqual(health.json()["api_contract_version"], "1.3.3")
                rejected = client.get("/api/v1/capabilities")
                self.assertEqual(rejected.status_code, 401)
                self.assertEqual(rejected.headers["x-rag-contract-version"], "1.3.3")
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
                        self.assertNotIn("synthetic-session", response.text)
                        self.assertNotIn("synthetic-request", response.text)
                        detail = response.json()["detail"]
                        self.assertEqual({item["category"] for item in detail}, {"extra_forbidden"})
                        self.assertTrue(all("msg" not in item and "input" not in item for item in detail))
        finally:
            client.close()

    def test_validation_errors_never_echo_query_values_or_unknown_field_names(self):
        client = TestClient(app)
        headers = {"Authorization": "Bearer synthetic-service-token"}
        query_marker = "SENSITIVE-QUERY-MARKER"
        field_marker = "SENSITIVE-FIELD-NAME-MARKER"
        value_marker = "SENSITIVE-SESSION-VALUE-MARKER"
        try:
            with patch.object(settings, "SERVICE_TOKEN", "synthetic-service-token"):
                response = client.post("/api/v1/retrievals", headers=headers, json={
                    "query": query_marker + ("x" * 4000), field_marker: value_marker,
                })
                self.assertEqual(response.status_code, 422)
                for marker in (query_marker, field_marker, value_marker):
                    self.assertNotIn(marker, response.text)
                details = response.json()["detail"]
                self.assertEqual({item["category"] for item in details}, {"extra_forbidden", "string_too_long"})
                self.assertTrue(all("msg" not in item and "input" not in item and "ctx" not in item for item in details))
                self.assertTrue(any("<unknown_field>" in item["loc"] for item in details))
                schema = app.openapi()
                response_model_ref = "#/components/schemas/RequestValidationResponse"
                issue_schema = schema["components"]["schemas"]["RequestValidationIssue"]
                self.assertEqual(set(issue_schema["properties"]), {"loc", "category"})
                for path in ("/api/v1/answers", "/api/v1/answers/stream", "/api/v1/retrievals"):
                    response_schema = schema["paths"][path]["post"]["responses"]["422"]["content"]["application/json"]["schema"]
                    self.assertEqual(response_schema["$ref"], response_model_ref)
                runtime_keys = set(details[0])
                self.assertTrue(runtime_keys <= set(issue_schema["properties"]))
                self.assertFalse(any(
                    response.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
                    == "#/components/schemas/HTTPValidationError"
                    for path_item in schema["paths"].values()
                    for operation in path_item.values() if isinstance(operation, dict)
                    for response in operation.get("responses", {}).values()
                ))
                self.assertNotIn("HTTPValidationError", schema["components"]["schemas"])
                self.assertNotIn("ValidationError", schema["components"]["schemas"])
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
