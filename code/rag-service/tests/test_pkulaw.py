import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.answer_graph import build_answer_graph
from app.config import settings
from app.main import app
from app.pkulaw import CONTRACT, PkulawError, PkulawSource, schema_shape, source_url, verify_tools
from app.retrieval_fusion import evidence_key, fuse_sources


def record(*, article="本合成法规条文要求核对金额。", **extra):
    return {"gid": "synthetic-1", "title": "合成境外贷款规定", "article": article, "doc_no": "合成〔2026〕1号",
            "timeliness": "现行有效", "effectiveness": "部门规章", "issue_department": "合成机构",
            "issue_date": "2026-01-01", "implementation_date": "2026-02-01", "lib": "合成库",
            "url": "https://pkulaw.com/chl/synthetic.html", **extra}


def payload(value, *, error=False):
    return SimpleNamespace(is_error=error, structured_content=value, content=[])


def tools():
    return [SimpleNamespace(name=name, input_schema=contract["inputSchema"], output_schema=contract["outputSchema"])
            for name, contract in CONTRACT["tools"].items()]


@contextmanager
def transport(*results):
    client = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools())),
                             call_tool=AsyncMock(side_effect=list(results)))
    # Magic methods need to live on the context manager type, not a namespace.
    http_context = unittest.mock.MagicMock()
    http_context.__aenter__ = AsyncMock()
    http_context.__aexit__ = AsyncMock(return_value=False)
    client_context = unittest.mock.MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    with patch.object(settings, "PKULAW_MCP_ENABLED", True), patch.object(settings, "PKULAW_MCP_TOKEN", SecretStr("test-only")), \
            patch("app.pkulaw.httpx2.AsyncClient", return_value=http_context), patch("app.pkulaw.Client", return_value=client_context), \
            patch("app.pkulaw.streamable_http_client"):
        yield client


class PkulawContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_body_is_evidence_metadata_is_not_sufficient(self):
        with transport(payload({"result": [record(), record(article="", gid="empty")]})) as client:
            result = await PkulawSource().retrieve_async(query="境外贷款金额要求")
        self.assertEqual(client.call_tool.await_count, 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["metadata"]["applicability"], "unverified")
        self.assertEqual(result["items"][0]["metadata"]["timeliness"], "现行有效")
        self.assertTrue(result["warnings"])

    async def test_fetch_only_uses_an_article_number_present_in_question(self):
        with transport(payload({"result": [record(article="")]}), payload(record(article="第十二条 合成条文。"))) as client:
            result = await PkulawSource().retrieve_async(query="合成境外贷款规定第十二条的要求")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.call_tool.await_args_list[1].args,
                         ("get_article", {"title": "合成境外贷款规定", "number": "第十二条"}))

    async def test_same_body_with_changed_legal_status_is_not_deduplicated(self):
        with transport(payload({"result": [record(), record(timeliness="已被修改")]})):
            result = await PkulawSource().retrieve_async(query="境外贷款规定")
        self.assertEqual(len(result["items"]), 2)
        self.assertNotEqual(evidence_key(result["items"][0]), evidence_key(result["items"][1]))

    async def test_unrelated_fetch_cannot_replace_a_missing_body(self):
        with transport(payload({"result": [record(article="")]}), payload(record(gid="other"))):
            result = await PkulawSource().retrieve_async(query="合成规定第一条")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["status"], "partial")

    async def test_different_law_version_cannot_replace_missing_body(self):
        with transport(payload({"result": [record(article="")]}), payload(record(timeliness="已被修改"))):
            result = await PkulawSource().retrieve_async(query="合成规定第一条")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["status"], "partial")

    async def test_schema_change_is_rejected_before_tool_call(self):
        with transport() as client:
            altered = copy.deepcopy(tools())
            altered[0].input_schema["required"].append("new_field")
            client.list_tools.return_value = SimpleNamespace(tools=altered)
            with self.assertRaises(PkulawError):
                await PkulawSource().retrieve_async(query="境外贷款要求")
            client.call_tool.assert_not_called()

    async def test_paginated_discovery_is_bounded_and_follows_cursor(self):
        with transport(payload({"result": [record()]})) as client:
            listing = tools()
            client.list_tools.side_effect = [SimpleNamespace(tools=listing[:1], next_cursor="page2"),
                                             SimpleNamespace(tools=listing[1:], next_cursor=None)]
            result = await PkulawSource().retrieve_async(query="境外贷款")
            self.assertEqual(result["status"], "ok")
            client.list_tools.assert_awaited_with(cursor="page2")
        with transport() as client:
            client.list_tools.return_value = SimpleNamespace(tools=[], next_cursor="same")
            with self.assertRaises(PkulawError):
                await PkulawSource().retrieve_async(query="境外贷款")
            self.assertEqual(client.list_tools.await_count, 2)
            client.call_tool.assert_not_called()

    async def test_tool_errors_and_invalid_output_never_leak_payloads(self):
        for value in (payload({"secret": "must-not-appear"}, error=True), payload({"result": [{"secret": "must-not-appear"}]})):
            with transport(value), self.assertRaises(PkulawError) as caught:
                await PkulawSource().retrieve_async(query="境外贷款")
            self.assertNotIn("must-not-appear", str(caught.exception))
        with transport() as client:
            client.call_tool.side_effect = TimeoutError("secret-header-value")
            with self.assertRaises(PkulawError) as caught:
                await PkulawSource().retrieve_async(query="境外贷款")
            self.assertNotIn("secret-header-value", str(caught.exception))

    async def test_server_and_source_urls_are_constrained(self):
        for url in ("http://pkulaw.com/a", "https://pkulaw.com.evil.test/a", "https://u:p@pkulaw.com/a", "https://pkulaw.com:444/a", "javascript:alert(1)"):
            self.assertIsNone(source_url(url))
        with transport() as client, patch.object(settings, "PKULAW_MCP_LAW_SEARCH_URL", "http://127.0.0.1/private"):
            with self.assertRaises(PkulawError):
                await PkulawSource().retrieve_async(query="境外贷款")
            client.call_tool.assert_not_called()
        self.assertEqual(source_url("https://www.pkulaw.com/a"), "https://www.pkulaw.com/a")

    async def test_disabled_source_never_connects(self):
        with patch.object(settings, "PKULAW_MCP_ENABLED", False), patch("app.pkulaw.Client") as client:
            with self.assertRaises(PkulawError):
                await PkulawSource().retrieve_async(query="境外贷款")
            client.assert_not_called()


def item(key, source="knowledge_base"):
    return {"content": "合成证据" + key, "document_id": key, "chunk_id": key, "document_keyword": key,
            "metadata": {"source_type": source, "scope": "law"}, "similarity": None}


class MultiSourceGraphTests(unittest.TestCase):
    def test_default_request_does_not_forward_question_to_external_source(self):
        engine, runtime, law = Mock(), Mock(), Mock()
        engine.retrieve.return_value = [item("kb")]
        runtime.complete.side_effect = ['{"intent":"law","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1]}']
        result = build_answer_graph(engine, runtime, generate_answer=False, law_source=law).invoke(
            {"query": "境外贷款要求", "scope": "law", "top_k": 5})["result"]
        law.retrieve.assert_not_called()
        self.assertEqual(result["source_status"], {"knowledge_base": "ok"})

    def test_source_fusion_retains_both_sources_and_is_order_independent(self):
        pools = {"knowledge_base": [item(str(index)) for index in range(20)], "pkulaw": [item("law", "pkulaw")]}
        forward = fuse_sources(pools, top_k=3)
        backward = fuse_sources(dict(reversed(list(pools.items()))), top_k=3)
        self.assertEqual(forward, backward)
        self.assertIn("law", [value["document_id"] for value in forward])

    def test_external_partial_result_cannot_be_claimed_sufficient(self):
        engine, runtime, law = Mock(), Mock(), Mock()
        engine.retrieve.return_value = [item("kb")]
        law.retrieve.return_value = {"items": [item("law", "pkulaw")], "status": "partial", "warnings": ["有命中缺正文"]}
        runtime.complete.side_effect = ['{"intent":"law","queries":[]}', '{"relevant":true,"sufficient":true,"selected":[1,2]}']
        result = build_answer_graph(engine, runtime, generate_answer=False, law_source=law).invoke(
            {"query": "境外贷款要求", "scope": "law", "top_k": 5, "sources": ["knowledge_base", "pkulaw"]})["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["source_status"]["pkulaw"], "partial")
        self.assertEqual(len(result["sources"]), 2)
        self.assertTrue(result["missing"])

    def test_external_only_and_unavailable_are_explicit(self):
        for unavailable in (False, True):
            engine, runtime, law = Mock(), Mock(), Mock()
            law.retrieve.side_effect = PkulawError("服务不可用") if unavailable else None
            law.retrieve.return_value = {"items": [item("law", "pkulaw")], "status": "ok", "warnings": []}
            runtime.complete.side_effect = ['{"intent":"law","queries":[]}',
                '{"relevant":false,"sufficient":false}' if unavailable else '{"relevant":true,"sufficient":true,"selected":[1]}']
            result = build_answer_graph(engine, runtime, generate_answer=False, law_source=law).invoke(
                {"query": "境外贷款要求", "scope": "law", "top_k": 5, "sources": ["pkulaw"]})["result"]
            engine.retrieve.assert_not_called()
            self.assertEqual(result["source_status"]["pkulaw"], "unavailable" if unavailable else "ok")
            self.assertEqual(result["evidence_status"], "insufficient" if unavailable else "sufficient")

    def test_http_source_scope_cannot_expand_authorized_range(self):
        with patch.object(settings, "SERVICE_TOKEN", "test-only"):
            response = TestClient(app).post("/api/v1/retrievals", headers={"Authorization": "Bearer test-only"},
                json={"query": "境外贷款", "scope": "project_design", "sources": ["pkulaw"]})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
