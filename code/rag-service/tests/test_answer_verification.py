import json
import unittest
from unittest.mock import Mock

from app.answer_graph import build_answer_graph
from app.answer_verification import answer_segments, verify_answer
from app.runtime_client import RuntimeErrorResponse


def evidence(text="金额不符时须暂停处理并更正后重新提交。", key="A"):
    return {"content": text, "document_keyword": "synthetic.txt", "document_id": key, "chunk_id": key, "metadata": {}}


def check(*, segment=1, citation=1, quote="须暂停处理", verdict="supported"):
    return {"segment": segment, "verdict": verdict, "supports": [{"citation": citation, "quote": quote}], "reason": "合成核对说明"}


def response(*checks):
    return json.dumps({"checks": list(checks)}, ensure_ascii=False)


class AnswerVerificationTests(unittest.TestCase):
    def verify(self, answer, reply, *, sources=None):
        complete = Mock(return_value=reply)
        report = verify_answer(answer=answer, query="金额不符怎么办？", evidence=sources or [evidence()], complete=complete)
        return report, complete

    def test_exact_quote_has_traceable_anchor(self):
        report, complete = self.verify("应暂停处理。[1]", response(check()))
        self.assertEqual(report["status"], "supported_by_model")
        anchor = report["checks"][0]["supports"][0]
        self.assertEqual(evidence()["content"][anchor["start_char"]:anchor["end_char"]], anchor["quote"])
        self.assertEqual(complete.call_args.kwargs["conversation"], [])

    def test_each_segment_and_every_citation_must_be_checked(self):
        report, _ = self.verify("须暂停。[1]须更正。[1]", response(check()))
        self.assertEqual(report["status"], "invalid_verification")
        report, _ = self.verify("须暂停。[1][2]", response(check()), sources=[evidence(), evidence(key="B")])
        self.assertEqual(report["status"], "invalid_verification")

    def test_quote_offsets_map_back_to_parent_window(self):
        item = evidence()
        item["metadata"]["excerpt"] = {"parent_chunk_id": "parent", "start_char": 8000,
                                       "end_char": 8000 + len(item["content"]), "parent_chars": 10000,
                                       "parent_content_sha256": "parent-hash"}
        report, _ = self.verify("应暂停处理。[1]", response(check()), sources=[item])
        anchor = report["checks"][0]["supports"][0]
        self.assertEqual(anchor["parent_start_char"], 8000 + anchor["start_char"])
        self.assertEqual(anchor["parent_content_sha256"], "parent-hash")

    def test_citation_after_sentence_punctuation_is_in_same_segment(self):
        self.assertEqual(answer_segments("先核查。[1]\n再更正。[2]"), ["先核查。[1]", "再更正。[2]"])

    def test_fabricated_quote_or_cross_source_quote_is_rejected(self):
        for reply in [response(check(quote="金额不符可以放行")), response(check(citation=2))]:
            report, _ = self.verify("应暂停。[1]", reply, sources=[evidence(), evidence(key="B")])
            self.assertEqual(report["status"], "invalid_verification")

    def test_duplicate_segment_and_boolean_index_are_rejected(self):
        for reply in [response(check(), check()), response(check(segment=True)), response(check(citation=True))]:
            report, _ = self.verify("应暂停。[1]", reply)
            self.assertEqual(report["status"], "invalid_verification")

    def test_uncertain_or_unsupported_is_not_accepted(self):
        for verdict in ("unsupported", "uncertain"):
            report, _ = self.verify("可以直接放行。[1]", response(check(verdict=verdict)))
            self.assertEqual(report["status"], "unsupported")

    def test_uncited_text_is_not_ignored_as_a_heading(self):
        report, complete = self.verify("确定通过\n应暂停。[1]", response(check()))
        self.assertEqual(report["status"], "invalid_citations")
        complete.assert_not_called()

    def test_timeout_and_oversized_answer_fail_explicitly(self):
        complete = Mock(side_effect=RuntimeErrorResponse("safe timeout"))
        report = verify_answer(answer="须暂停。[1]", query="q", evidence=[evidence()], complete=complete)
        self.assertEqual(report["status"], "verification_unavailable")
        report, _ = self.verify("长" * 10001 + "[1]", response(check()))
        self.assertEqual(report["status"], "invalid_verification")

    def test_graph_hides_answer_with_valid_citation_but_no_support(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [evidence()]
        runtime.complete.side_effect = ['{"intent":"procedure","queries":[]}',
            '{"relevant":true,"sufficient":true,"selected":[1]}', '{"statements": [{"text": "可以直接放行。", "supports": [{"citation": 1, "quote": "须暂停处理"}]}]}', response(check(verdict="unsupported"))]
        result = build_answer_graph(engine, runtime).invoke({"query": "金额不符怎么办？", "scope": "business_rules", "top_k": 5})["result"]
        self.assertNotIn("可以直接放行", result["answer"])
        self.assertEqual(result["grounding"], "insufficient")
        self.assertEqual(result["answer_verification"]["status"], "unsupported")
        self.assertEqual(len(result["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
