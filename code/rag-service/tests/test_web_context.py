import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.answer_graph import build_answer_graph
from app.backend_api import AnswerRequest, answer_state
from app.config import settings
from app.evidence_context import evidence_source, prepare_windows
from app.main import app
from app.runtime_client import RuntimeErrorResponse
from app.web_context import WebContextError, WebContextSource, WebSnapshot


KEY = "synthetic-web-context-test-credential-only-0001"


def snapshot(**changes):
    return {"url": "https://docs.example.com/rules#amount", "title": "合成网页上下文",
        "text": "页面声称需核对 USD5000 / 金额 discrepancy；不是核实结果。",
        "captured_at": datetime.now(timezone.utc).isoformat(), "scope": "business_rules",
        "completeness": "selection", "processing_authorized": True, **changes}


class WebContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = Path(self.temp.name) / "principals.json"
        self.write_registry()
        for name, value in {"SERVICE_TOKEN": "synthetic-service-token", "RAG_WEB_CONTEXT_ENABLED": True,
                            "RAG_WEB_CONTEXT_PRINCIPALS_FILE": str(self.registry),
                            "RAG_WEB_CONTEXT_ALLOWED_HOSTS": "docs.example.com", "RAG_WEB_CONTEXT_MAX_AGE_SECONDS": 900}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_registry(self, **changes):
        self.registry.write_text(json.dumps({"principals": [{"subject": "synthetic-capture-service",
            "key_sha256": hashlib.sha256(KEY.encode()).hexdigest(), "namespaces": ["business_rules"],
            "roles": ["reader"], "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            **changes}]}), encoding="utf-8")

    def source(self, *rows, scope="all"):
        return WebContextSource([WebSnapshot.model_validate(row) for row in rows or (snapshot(),)], scope=scope, key=KEY)

    def state(self, **extra):
        return {"query": "页面对金额核查说了什么？", "scope": "all", "top_k": 4,
                "sources": ["knowledge_base", "web_context"], **extra}

    def runtime(self, selected=1):
        runtime = Mock()
        def complete(**kwargs):
            if "检查检索原文" in kwargs["instructions"]:
                return json.dumps({"relevant": True, "sufficient": True, "selected": [selected], "missing": [], "rewrite": ""})
            return json.dumps({"intent": "rule", "queries": []})
        runtime.complete.side_effect = complete
        return runtime

    def test_snapshot_schema_rejects_unusable_text_unsafe_urls_and_forged_metadata(self):
        urls = ["http://docs.example.com/rules", "https://user:password@docs.example.com/rules",
                "https://docs.example.com/rules?token=secret", "https://127.0.0.1/x", "https://169.254.169.254/x",
                "https://host.local/x", "https://docs.example.com:8443/x", "https://docs.example.com/\nsecret",
                "https://docs.example.com\\@evil.example/x"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                WebSnapshot.model_validate(snapshot(url=url))
        for changes in ({"text": "\x00"}, {"text": "\ufffd"}, {"text": "\ud800"}, {"text": "  "},
                        {"processing_authorized": False}, {"processing_authorized": 1}, {"captured_at": "2026-01-01"},
                        {"verified": True}, {"reviewer": "forged"}):
            with self.subTest(changes=repr(changes)), self.assertRaises(ValidationError):
                WebSnapshot.model_validate(snapshot(**changes))
        text = snapshot()
        for data in ({"sources": ["web_context"]}, {"web_context": [text]},
                     {"sources": ["web_context"], "web_context": [text, text]},
                     {"sources": ["web_context"], "web_context": [snapshot(text="中" * 40000, url=f"https://docs.example.com/{i}") for i in range(2)]}):
            with self.assertRaises(ValidationError):
                AnswerRequest(query="test", **data)

    def test_authorization_before_database_for_json_and_sse_and_no_secret_in_state(self):
        payload = {"query": "test", "sources": ["web_context"], "web_context": [snapshot()]}
        client = TestClient(app)
        headers = {"Authorization": "Bearer synthetic-service-token"}
        with patch("app.backend_api.postgres_engine") as engine:
            for route in ("retrievals", "answers", "answers/stream"):
                response = client.post("/api/v1/" + route, json=payload, headers=headers)
                self.assertEqual(response.status_code, 401)
            engine.assert_not_called()
        with patch.object(settings, "RAG_WEB_CONTEXT_ENABLED", False):
            self.assertEqual(client.post("/api/v1/retrievals", json=payload, headers={**headers, "X-Web-Context-Key": KEY}).status_code, 404)
        with patch.object(settings, "RAG_WEB_CONTEXT_ALLOWED_HOSTS", ""):
            self.assertEqual(client.post("/api/v1/retrievals", json=payload, headers={**headers, "X-Web-Context-Key": KEY}).status_code, 503)
        state = answer_state(AnswerRequest.model_validate(payload))
        self.assertNotIn("web_context", state)
        self.assertNotIn(KEY, json.dumps(state))

    def test_exact_scope_host_freshness_role_and_live_registry_revocation(self):
        for changes, scope, status in [({"scope": "law"}, "all", 403), ({}, "law", 403),
            ({"url": "https://docs.example.com.evil.example/rules"}, "all", 403),
            ({"captured_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}, "all", 409),
            ({"captured_at": (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()}, "all", 409)]:
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as error:
                self.source(snapshot(**changes), scope=scope)
            self.assertEqual(error.exception.status_code, status)
        source = self.source()
        self.write_registry(roles=["author"])
        with self.assertRaises(WebContextError):
            source.candidates()
        self.write_registry(valid_until=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        with self.assertRaises(HTTPException) as error:
            self.source()
        self.assertEqual(error.exception.status_code, 401)

    def test_authorized_actual_http_graph_and_sse_return_request_snapshot_only(self):
        row = snapshot()
        payload = {"query": "页面对金额核查说了什么？", "sources": ["web_context"], "web_context": [row]}
        client = TestClient(app)
        headers = {"Authorization": "Bearer synthetic-service-token", "X-Web-Context-Key": KEY}
        engine = Mock()
        with patch("app.backend_api.postgres_engine", return_value=engine), patch("app.answer_graph.SDKRuntime", return_value=self.runtime()):
            for route in ("retrievals", "answers", "answers/stream"):
                response = client.post("/api/v1/" + route, headers=headers, json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                result = response.json() if route != "answers/stream" else next(
                    json.loads(part.split("data: ", 1)[1]) for part in response.text.split("\n\n") if part.startswith("event: result"))
                self.assertEqual(result["sources"][0]["content"], row["text"])
                self.assertEqual(result["sources"][0]["source_url"], row["url"])
                self.assertEqual(result["sources"][0]["metadata"]["verification"], "caller_supplied_unverified")
                self.assertNotIn(KEY, response.text)
        engine.retrieve.assert_not_called()

    def test_immutable_original_windows_and_different_snapshots_are_not_merged(self):
        text = "合成金额 USD5000；" * 650 + "末尾须核对币种。"
        source = self.source(snapshot(text=text), snapshot(text="另一版本 CNY5000 不得混合。"))
        items = source.candidates()
        self.assertNotEqual(items[0]["document_id"], items[1]["document_id"])
        windows, total = prepare_windows(items, max_windows=80)
        self.assertGreater(total, 2)
        self.assertEqual(source.current_evidence(windows), windows)
        for field, value in [("content", "伪造金额"), ("source_url", "https://evil.example/"), ("document_keyword", "法规已确认")]:
            changed = copy.deepcopy(windows[0]); changed[field] = value
            self.assertEqual(source.current_evidence([changed]), [])
        changed = copy.deepcopy(windows[0]); changed["metadata"]["captured_at"] = "forged"
        self.assertEqual(source.current_evidence([changed]), [])
        items[0]["content"] = "mutated"
        self.assertEqual(source.candidates()[0]["content"], text)

    def test_web_and_knowledge_candidates_jointly_reranked_without_fake_rrf_votes(self):
        engine = Mock()
        engine.retrieve.return_value = [{"content": "知识库原文", "document_id": "kb", "chunk_id": "kb1",
            "document_keyword": "合成规则", "metadata": {}, "similarity": 0.8}]
        ranker = Mock()
        ranker.rerank.side_effect = lambda **kw: (list(reversed(kw["evidence"])), "ok")
        runtime = self.runtime()
        result = build_answer_graph(engine, runtime, generate_answer=False, web_source=self.source(), reranker=ranker).invoke(self.state())["result"]
        self.assertEqual(result["evidence_status"], "sufficient")
        self.assertEqual(result["source_status"]["web_context"], "provided_unverified")
        self.assertEqual(result["sources"][0]["metadata"]["source_type"], "web_context")
        mixed = ranker.rerank.call_args.kwargs["evidence"]
        self.assertEqual(len(mixed), 2)
        web = mixed[-1]
        self.assertNotIn("source_fusion", web["metadata"])
        self.assertEqual(web["metadata"]["retrieval"]["score_type"], "unranked_context")
        self.assertTrue(evidence_source(web).startswith("未核实网页上下文"))
        self.assertIsNone(web["similarity"])
        self.assertEqual(len(runtime.complete.call_args_list), 2)
        self.assertNotIn(KEY, json.dumps(result))

    def test_web_only_returns_reference_but_never_case_approval_or_missing_adapter_success(self):
        source = self.source()
        engine = Mock()
        for purpose, expected in [("reference", "sufficient"), ("case_assessment", "insufficient")]:
            result = build_answer_graph(engine, self.runtime(), generate_answer=False, web_source=source).invoke(
                self.state(sources=["web_context"], purpose=purpose))["result"]
            self.assertEqual(result["evidence_status"], expected)
            if purpose == "case_assessment":
                self.assertEqual(result["legal_applicability"]["status"], "blocked")
                self.assertTrue(result["missing"])
        engine.retrieve.assert_not_called()
        result = build_answer_graph(engine, self.runtime(), generate_answer=False).invoke(
            self.state(sources=["web_context"]))["result"]
        self.assertEqual(result["evidence_status"], "insufficient")

    def test_revocation_during_assessment_prevents_final_publication(self):
        source, runtime = self.source(), self.runtime()
        original = runtime.complete.side_effect
        def complete(**kwargs):
            result = original(**kwargs)
            if "检查检索原文" in kwargs["instructions"]:
                self.registry.unlink()
            return result
        runtime.complete.side_effect = complete
        with self.assertRaises(RuntimeErrorResponse) as error:
            build_answer_graph(Mock(), runtime, generate_answer=False, web_source=source).invoke(self.state(sources=["web_context"]))
        self.assertNotIn(KEY, str(error.exception))
