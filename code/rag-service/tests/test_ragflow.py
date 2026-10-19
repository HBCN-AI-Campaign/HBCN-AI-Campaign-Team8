import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.config import settings
from app.manifest import manifest_paths
from app.ragflow import RAGFlowClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class RAGFlowClientTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "RAGFLOW_BASE_URL": settings.RAGFLOW_BASE_URL,
            "RAGFLOW_API_KEY": settings.RAGFLOW_API_KEY,
            "RAGFLOW_BUSINESS_RULES_DATASET_ID": settings.RAGFLOW_BUSINESS_RULES_DATASET_ID,
            "RAGFLOW_PROJECT_DESIGN_DATASET_ID": settings.RAGFLOW_PROJECT_DESIGN_DATASET_ID,
            "BUSINESS_SOURCE_ROOT": settings.BUSINESS_SOURCE_ROOT,
        }
        settings.RAGFLOW_BASE_URL = "http://ragflow.test"
        settings.RAGFLOW_API_KEY = "test-key"
        settings.RAGFLOW_BUSINESS_RULES_DATASET_ID = "rules-id"
        settings.RAGFLOW_PROJECT_DESIGN_DATASET_ID = "design-id"

    def tearDown(self):
        for key, value in self.values.items():
            setattr(settings, key, value)

    @patch("app.ragflow.httpx.request")
    def test_retrieve_uses_official_hybrid_retrieval_payload(self, request):
        request.return_value = FakeResponse(
            {
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "content": "提款用途证明",
                            "document_id": "doc-1",
                            "document_keyword": "rules.xlsx",
                            "similarity": 0.91,
                        }
                    ]
                },
            }
        )

        chunks = RAGFlowClient().retrieve(query="提款用途", scope="business_rules", top_k=8)

        self.assertEqual(chunks[0]["document_id"], "doc-1")
        request.assert_called_once()
        call = request.call_args
        self.assertEqual(call.args[:2], ("POST", "http://ragflow.test/api/v1/retrieval"))
        self.assertEqual(call.kwargs["json"]["dataset_ids"], ["rules-id"])
        self.assertTrue(call.kwargs["json"]["keyword"])

    @patch("app.ragflow.httpx.post")
    @patch("app.ragflow.httpx.request")
    def test_upload_triggers_parse_and_waits_until_done(self, request, post):
        post.return_value = FakeResponse(
            {"code": 0, "data": [{"id": "doc-1", "name": "rules.txt"}]}
        )
        request.side_effect = [
            FakeResponse({"code": 0, "data": {"id": "job-1"}}),
            FakeResponse({"code": 0, "data": {"docs": [{"id": "doc-1", "run": "DONE"}]}}),
        ]

        client = RAGFlowClient()
        document_ids = client.upload(
            scope="business_rules",
            dataset_id="rules-id",
            filename="rules.txt",
            content=b"rules",
            content_type="text/plain",
        )
        parsed = client.wait_for_documents(
            scope="business_rules",
            dataset_id="rules-id",
            document_ids=document_ids,
        )

        self.assertEqual(document_ids, ["doc-1"])
        self.assertEqual(parsed[0]["run"], "DONE")
        self.assertEqual(request.call_args.args[:2], ("GET", "http://ragflow.test/api/v1/datasets/rules-id/documents"))

    @patch("app.ragflow.httpx.post")
    @patch("app.ragflow.httpx.request")
    def test_upload_writes_document_metadata(self, request, post):
        post.return_value = FakeResponse(
            {"code": 0, "data": [{"id": "doc-1", "name": "rules.txt"}]}
        )
        request.return_value = FakeResponse({"code": 0, "data": {}})

        RAGFlowClient().upload(
            scope="business_rules",
            dataset_id="rules-id",
            filename="rules.txt",
            content=b"rules",
            content_type="text/plain",
            metadata={"knowledge_scope": "business_rules"},
        )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs["json"]["selector"]["document_ids"], ["doc-1"])
        self.assertEqual(request.call_args.kwargs["json"]["updates"][0]["key"], "knowledge_scope")

    def test_manifest_contains_only_existing_safe_files(self):
        root = Path(os.environ["HBCN_TEST_SOURCE_ROOT"])
        files = manifest_paths(root)
        self.assertEqual(len(files), 11)
        self.assertTrue(all("04设备API等文件" not in path.parts for _, path in files))


if __name__ == "__main__":
    unittest.main()
