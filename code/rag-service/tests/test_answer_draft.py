import json
import unittest
from unittest.mock import Mock
from app.answer_draft import parse_draft
from app.answer_graph import build_answer_graph
from app.runtime_client import RuntimeErrorResponse


class DraftContractTests(unittest.TestCase):
    def draft(self, **extra):
        return {"statements": [{"text": "应暂停处理。", "supports": [{"citation": 1, "quote": "暂停处理"}]}], **extra}

    def parse(self, draft):
        return parse_draft(json.dumps(draft, ensure_ascii=False), [{"content": "金额不一致应暂停处理。"}])

    def test_server_renders_citation_after_factual_statement(self):
        text, _ = self.parse(self.draft())
        self.assertEqual(text, "应暂停处理。[1]")

    def test_extra_layout_or_source_explanation_is_not_accepted_as_extra_field(self):
        for draft in (self.draft(disclaimer="本答复不是审核结论"), {"statements": []}):
            with self.assertRaises(ValueError):
                self.parse(draft)

    def test_missing_quote_wrong_source_and_boolean_index_fail(self):
        for support in ({"citation": 1, "quote": "直接放行"}, {"citation": 2, "quote": "暂停处理"},
                        {"citation": True, "quote": "暂停处理"}):
            draft = self.draft()
            draft["statements"][0]["supports"] = [support]
            with self.assertRaises(ValueError):
                self.parse(draft)

    def test_no_embedded_citations_multisentence_or_newline(self):
        for text in ("应暂停。[9]", "应暂停。然后更正。", "标题\n应暂停"):
            draft = self.draft()
            draft["statements"][0]["text"] = text
            with self.assertRaises(ValueError):
                self.parse(draft)

    def test_failed_generation_retains_sources_and_explicit_failure_status(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [{"content": "金额不符须暂停处理", "document_id": "s", "chunk_id": "s1",
                                         "document_keyword": "synthetic.txt", "metadata": {}}]
        runtime.complete.side_effect = ['{"intent":"procedure","queries":[]}',
            '{"relevant":true,"sufficient":true,"selected":[1]}', RuntimeErrorResponse("safe timeout")]
        result = build_answer_graph(engine, runtime).invoke({"query": "金额不符怎么办？", "scope": "business_rules", "top_k": 5})["result"]
        self.assertEqual(result["answer_verification"]["status"], "generation_unavailable")
        self.assertEqual(result["grounding"], "insufficient")
        self.assertEqual(len(result["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
