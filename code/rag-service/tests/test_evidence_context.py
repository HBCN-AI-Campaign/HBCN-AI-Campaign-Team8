import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from app.answer_graph import build_answer_graph
from app.config import settings
from app.evidence_assessment import assess_context
from app.evidence_context import pack_batches, payload_bytes, prepare_windows, runtime_payload, utf16_units
from app.main import app
from app.runtime_client import RuntimeErrorResponse, SDKRuntime


def evidence(key, content):
    return {"content": content, "document_id": "doc", "document_keyword": "synthetic.txt", "chunk_id": key,
            "reader_url": "/api/v1/documents/doc/content?chunk_id=" + key, "similarity": None, "metadata": {"scope": "law"}}


def assessment(selected=(), *, sufficient=False):
    return json.dumps({"relevant": bool(selected), "sufficient": sufficient, "selected": list(selected), "missing": []})


class EvidenceWindowTests(unittest.TestCase):
    def test_windows_are_exact_source_spans_and_cover_tail_and_repeated_paragraphs(self):
        text = ("合成条款：应核对支付指令金额。\n" * 900) + "例外：金额不符时须更正，不得直接放行。"
        original = evidence("parent", text)
        windows, total = prepare_windows([original], max_windows=200)
        self.assertEqual(len(windows), total)
        end = 0
        for window in windows:
            span = window["metadata"]["excerpt"]
            self.assertEqual(window["content"], text[span["start_char"]:span["end_char"]])
            self.assertLessEqual(span["start_char"], end)
            end = max(end, span["end_char"])
            self.assertEqual(window["reader_url"], original["reader_url"])
            self.assertEqual(window["chunk_id"], "parent")
            self.assertEqual(span["parent_content_sha256"], hashlib.sha256(text.encode()).hexdigest())
            self.assertLessEqual(utf16_units(window["content"]), 4000)
        self.assertEqual(end, len(text))
        self.assertIn("不得直接放行", windows[-1]["content"])

    def test_supplementary_characters_use_the_javascript_limit(self):
        text = "🧾" * 5000 + "末尾例外"
        windows, total = prepare_windows([evidence("emoji", text)], max_windows=20)
        self.assertEqual(total, len(windows))
        self.assertTrue(all(utf16_units(item["content"]) <= 4000 for item in windows))
        self.assertIn("末尾例外", windows[-1]["content"])

    def test_byte_packing_matches_httpx_and_preserves_all_candidates(self):
        items = [evidence(str(index), "金额" * 2000) for index in range(20)]
        history = [{"role": "user", "content": "上下文" * 1200} for _ in range(12)]
        batches = pack_batches(items, message="问题", instructions="要求", conversation=history)
        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(map(len, batches)), 20)
        for batch in batches:
            payload = runtime_payload(message="问题", instructions="要求", evidence=batch, conversation=history)
            encoded = httpx.Request("POST", "http://runtime/runs", json=payload).content
            self.assertEqual(payload_bytes(payload), len(encoded))
            self.assertLessEqual(len(encoded), 220_000)

    def test_runtime_rejects_oversized_text_and_body_before_sending(self):
        with patch.object(settings, "ASSISTANT_RUNTIME_URL", "http://runtime"), patch("app.runtime_client.runtime_token", return_value="test"), \
                patch("app.runtime_client.httpx.AsyncClient") as send:
            with self.assertRaises(RuntimeErrorResponse):
                SDKRuntime().complete(message="q", instructions="i", evidence=[evidence("emoji", "🧾" * 2001)])
            with self.assertRaises(RuntimeErrorResponse):
                SDKRuntime().complete(message="q", instructions="i", evidence=[evidence(str(index), "金" * 4000) for index in range(20)],
                                      conversation=[{"role": "user", "content": "金" * 4000} for _ in range(12)])
            send.assert_not_called()

    def test_http_history_cannot_be_silently_dropped_by_javascript_filter(self):
        with patch.object(settings, "SERVICE_TOKEN", "test"):
            response = TestClient(app).post("/api/v1/retrievals", headers={"Authorization": "Bearer test"},
                json={"query": "问题", "conversation": [{"role": "user", "content": "🧾" * 2001}]})
        self.assertEqual(response.status_code, 422)


class BatchedCoverageTests(unittest.TestCase):
    def test_joint_check_receives_conflict_original_and_gap_checklist(self):
        items = [evidence(str(index), "普通背景") for index in range(21)]
        items[0]["content"] = "一般要求：可以处理。"
        items[-1]["content"] = "例外：金额不符不得处理。"
        calls = []
        def complete(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return '{"relevant":true,"sufficient":false,"selected":[1],"missing":["须核对金额不符的例外"]}'
            if len(calls) == 2:
                return assessment([1])
            return '{"relevant":true,"sufficient":false,"selected":[1,2],"missing":["业务金额尚未确认"]}'
        result = assess_context(complete=complete, query="是否可处理？", candidates=items, conversation=[])
        self.assertIn("须核对金额不符的例外", calls[-1]["instructions"])
        self.assertIn("金额不符不得处理", calls[-1]["evidence"][1]["content"])
        self.assertFalse(result.assessment.sufficient)
        self.assertEqual(len(result.selected), 2)

    def test_separate_relevant_batches_require_joint_original_evidence_check(self):
        items = [evidence(str(index), "无关背景") for index in range(21)]
        items[0]["content"] = "核查金额"
        items[-1]["content"] = "更正流程"
        calls = []
        def complete(**kwargs):
            texts = [item["content"] for item in kwargs["evidence"]]
            calls.append(texts)
            selected = [index for index, text in enumerate(texts, 1) if text in {"核查金额", "更正流程"}]
            return assessment(selected, sufficient=True)
        result = assess_context(complete=complete, query="核查与更正如何处理？", candidates=items, conversation=[])
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(calls[-1]), {"核查金额", "更正流程"})
        self.assertTrue(result.coverage["input_complete"])
        self.assertTrue(result.coverage["selection_checked"])
        self.assertEqual(result.coverage["presented_windows"], 21)

    def test_window_budget_cannot_pass_even_if_model_claims_sufficient(self):
        text = "背景材料。" * 20000 + "末尾关键限制"
        with patch.object(settings, "RAG_MAX_CONTEXT_WINDOWS", 20):
            result = assess_context(complete=lambda **kwargs: assessment([1], sufficient=True), query="限制条件？",
                                    candidates=[evidence("long", text)], conversation=[])
        self.assertFalse(result.assessment.sufficient)
        self.assertEqual(result.stop_reason, "context_budget")
        self.assertFalse(result.coverage["input_complete"])
        self.assertTrue(result.selected)

    def test_failure_after_first_batch_preserves_partial_support(self):
        complete = Mock(side_effect=[assessment([1]), RuntimeErrorResponse("safe failure")])
        result = assess_context(complete=complete, query="q", candidates=[evidence(str(index), "body") for index in range(21)], conversation=[])
        self.assertEqual(len(result.selected), 1)
        self.assertEqual(result.stop_reason, "assessment_unavailable")
        self.assertFalse(result.coverage["input_complete"])

    def test_graph_returns_tail_window_with_parent_location(self):
        engine, runtime = Mock(), Mock()
        original = evidence("long", "背景。" * 4000 + "末尾关键限制：须更正金额。")
        engine.retrieve.return_value = [original]
        def complete(**kwargs):
            if not kwargs["evidence"]:
                return '{"intent":"procedure","queries":[]}'
            indexes = [index for index, value in enumerate(kwargs["evidence"], 1) if "末尾关键限制" in value["content"]]
            return assessment(indexes, sufficient=True)
        runtime.complete.side_effect = complete
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(
            {"query": "金额不符如何处理？", "scope": "business_rules", "top_k": 5})["result"]
        self.assertEqual(result["evidence_status"], "sufficient")
        self.assertTrue(result["context_coverage"]["input_complete"])
        self.assertIn("末尾关键限制", result["sources"][0]["content"])
        self.assertEqual(result["sources"][0]["metadata"]["excerpt"]["end_char"], len(original["content"]))

    def test_answer_generation_reads_exactly_the_selected_original_windows(self):
        engine, runtime = Mock(), Mock()
        original = evidence("long", "背景。" * 3000 + "末尾要求：须更正金额。")
        engine.retrieve.return_value = [original]
        generated_inputs = []
        def complete(**kwargs):
            if not kwargs["evidence"]:
                return '{"intent":"procedure","queries":[]}'
            if kwargs["instructions"].startswith("你是境外贷款业务知识助手"):
                generated_inputs.extend(kwargs["evidence"])
                return '{"statements": [{"text": "须更正金额。", "supports": [{"citation": 1, "quote": "须更正金额"}]}]}'
            if kwargs["instructions"].startswith("你是回答依据复核员"):
                return '{"checks":[{"segment":1,"verdict":"supported","supports":[{"citation":1,"quote":"须更正金额"}],"reason":"原文有此要求"}]}'
            selected = [index for index, item in enumerate(kwargs["evidence"], 1) if "末尾要求" in item["content"]]
            return assessment(selected, sufficient=True)
        runtime.complete.side_effect = complete
        result = build_answer_graph(engine, runtime).invoke(
            {"query": "金额不符如何处理？", "scope": "business_rules", "top_k": 5})["result"]
        self.assertEqual(result["grounding"], "cited")
        self.assertEqual(len(generated_inputs), 1)
        self.assertEqual(generated_inputs[0]["content"], result["sources"][0]["content"])
        self.assertLess(len(generated_inputs[0]["content"]), len(original["content"]))


if __name__ == "__main__":
    unittest.main()
