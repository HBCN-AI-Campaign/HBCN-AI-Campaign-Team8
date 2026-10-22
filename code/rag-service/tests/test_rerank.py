import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
from pydantic import SecretStr

from app.answer_graph import build_answer_graph
from app.config import settings
from app.rerank import HTTPReranker, RerankError


def evidence(key):
    return {"content": "synthetic " + key, "document_id": key, "document_keyword": key,
            "chunk_id": key, "similarity": None, "metadata": {"source_fusion": {"score_type": "rrf"}}}


@contextmanager
def enabled():
    with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
            patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1:9876/v2/rerank"), \
            patch.object(settings, "RAG_RERANK_MODEL", "synthetic-model"), \
            patch.object(settings, "RAG_RERANK_TOKEN", SecretStr("test-only")):
        yield


def reranker(handler):
    return HTTPReranker(client_factory=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


class DedicatedRerankTests(unittest.TestCase):
    def test_protocol_maps_scores_to_original_evidence_without_losing_provenance(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["documents"], ["synthetic A", "synthetic B"])
            self.assertEqual(body["top_n"], 2)
            self.assertEqual(body["max_tokens_per_doc"], 4096)
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]})
        with enabled():
            result, status = reranker(handler).rerank(query="question", evidence=[evidence("A"), evidence("B")])
        self.assertEqual(status, "ok")
        self.assertEqual([item["document_id"] for item in result], ["B", "A"])
        self.assertEqual(result[0]["metadata"]["source_fusion"]["score_type"], "rrf")
        self.assertEqual(result[0]["metadata"]["rerank"]["model_revision"], "unverified")
        self.assertIsNone(result[0]["similarity"])

    def test_invalid_indexes_duplicate_scores_and_nan_are_rejected(self):
        rows = [
            [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.9}],
            [{"index": 0, "relevance_score": 0.5}, {"index": 2, "relevance_score": 0.9}],
            [{"index": False, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.9}],
            [{"index": 0, "relevance_score": float("nan")}, {"index": 1, "relevance_score": 0.9}],
        ]
        for results in rows:
            def handler(request):
                return httpx.Response(200, content=json.dumps({"results": results}))
            with self.subTest(results=results), enabled(), self.assertRaises(RerankError):
                reranker(handler).rerank(query="question", evidence=[evidence("A"), evidence("B")])

    def test_remote_dataflow_requires_explicit_server_configuration(self):
        factory = Mock()
        with enabled(), patch.object(settings, "RAG_RERANK_URL", "https://reranker.example/v2/rerank"), \
                patch.object(settings, "RAG_RERANK_ALLOW_EXTERNAL", False), self.assertRaises(RerankError):
            HTTPReranker(client_factory=factory).rerank(query="question", evidence=[evidence("A")])
        factory.assert_not_called()

    def test_disabled_and_empty_do_not_call_provider(self):
        factory = Mock()
        with patch.object(settings, "RAG_RERANK_PROVIDER", "disabled"):
            self.assertEqual(HTTPReranker(client_factory=factory).rerank(query="q", evidence=[]), ([], "disabled"))
        with enabled():
            self.assertEqual(HTTPReranker(client_factory=factory).rerank(query="q", evidence=[]), ([], "no_candidates"))
        factory.assert_not_called()

    def test_errors_are_safe_and_do_not_become_scores(self):
        for response in (httpx.Response(401, text="secret-provider-body"), httpx.Response(302, headers={"Location": "https://other.example"})):
            with enabled(), self.assertRaises(RerankError) as caught:
                reranker(lambda request: response).rerank(query="q", evidence=[evidence("A")])
            self.assertNotIn("secret-provider-body", str(caught.exception))

    def test_configured_failed_rerank_prevents_claiming_sufficient_evidence(self):
        engine, runtime, ranker = Mock(), Mock(), Mock()
        engine.retrieve.return_value = [evidence("A")]
        ranker.rerank.side_effect = RerankError("重排服务暂不可用")
        runtime.complete.side_effect = ['{"intent":"rule","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        result = build_answer_graph(engine, runtime, generate_answer=False, reranker=ranker).invoke(
            {"query": "question", "scope": "law", "top_k": 5})["result"]
        self.assertEqual(result["rerank_status"], "unavailable")
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertTrue(result["missing"])


if __name__ == "__main__":
    unittest.main()
