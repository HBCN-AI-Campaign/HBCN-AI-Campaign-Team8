import json
import unittest
from itertools import chain, repeat
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.answer_graph import build_answer_graph
from app.config import settings
from app.main import app
from app.query_plan import SearchQuery, plan_question
from app.retrieval_fusion import fuse_query_results


def encoded_plan(*queries, **extra):
    return json.dumps({
        "intent": "discrepancy",
        "queries": [{"text": text, "family": family} for text, family in queries],
        "user_statements": [],
        "unknown_slots": ["document_type", "field", "discrepancy_type", "amount", "currency", "subject", "business_date", "jurisdiction"],
        **extra,
    }, ensure_ascii=False)


def assess(*, selected=(), rewrite="", missing=()):
    return json.dumps({"relevant": bool(selected), "sufficient": bool(selected) and not rewrite,
                       "selected": list(selected), "rewrite": rewrite, "missing": list(missing)}, ensure_ascii=False)


def evidence(key, content, **metadata):
    return {"document_id": "doc-" + key, "chunk_id": key, "document_keyword": key + ".txt",
            "content": content, "similarity": 0.8, "metadata": metadata}


class QueryPlanTests(unittest.TestCase):
    def test_amount_generalization_keeps_exact_question_and_english_variant(self):
        query = "支付指令的5000块金额不对怎么办？"
        runtime = Mock()
        runtime.complete.return_value = encoded_plan(
            ("支付指令金额错误的核查与更正流程", "general"),
            ("payment instruction amount discrepancy correction procedure", "translated"),
        )
        plan, warnings = plan_question(query, [], runtime)
        self.assertEqual(plan.queries[0].text, query)
        self.assertEqual({item.family for item in plan.queries}, {"exact", "general", "translated"})
        self.assertFalse(warnings)
        self.assertEqual(runtime.complete.call_args.kwargs["evidence"], [])

    def test_rewrites_cannot_invent_a_number_or_currency_even_without_spaces(self):
        for query, variant in [
            ("支付指令5000金额不对", "支付指令50000金额核查"),
            ("支付指令USD5000不对", "支付指令CNY5000不对"),
            ("支付指令5000块不对", "USD5000 payment instruction correction"),
            ("金额-5000不对", "金额5000核查"),
        ]:
            with self.subTest(query=query):
                runtime = Mock()
                runtime.complete.return_value = encoded_plan((variant, "general"))
                plan, warnings = plan_question(query, [], runtime)
                self.assertEqual([item.text for item in plan.queries], [query])
                self.assertTrue(warnings)

    def test_translation_is_not_displaced_by_earlier_synonyms(self):
        runtime = Mock()
        runtime.complete.return_value = encoded_plan(
            ("支付指令金额核查", "exact"), ("金额错误处理流程", "general"),
            ("款项数额差异处理", "general"), ("payment amount discrepancy", "translated"),
        )
        plan, _ = plan_question("支付指令5000金额不对怎么办", [], runtime, max_queries=4)
        self.assertEqual(len(plan.queries), 4)
        self.assertTrue(any(item.family == "translated" for item in plan.queries))

    def test_only_user_history_can_supply_numbers(self):
        runtime = Mock()
        runtime.complete.return_value = encoded_plan(("USD5000 payment instruction", "exact"))
        query = "这笔金额为什么不对？"
        for role, expected in [("assistant", 1), ("user", 2)]:
            plan, _ = plan_question(query, [{"role": role, "content": "支付指令USD5000"}], runtime)
            self.assertEqual(len(plan.queries), expected)

    def test_fact_slots_require_user_quotes_and_conflicts_remain_unknown(self):
        runtime = Mock()
        runtime.complete.return_value = encoded_plan(
            user_statements=[
                {"slot": "document_type", "value": "支付指令", "source": "user_history", "source_index": 0, "quote": "这是支付指令"},
                {"slot": "amount", "value": "5000", "source": "user_history", "source_index": 0, "quote": "金额是 USD 5000"},
                {"slot": "currency", "value": "USD", "source": "user_history", "source_index": 0, "quote": "金额是 USD 5000"},
                {"slot": "currency", "value": "HKD", "source": "user_history", "source_index": 1, "quote": "不是 USD，是 HKD"},
                {"slot": "subject", "value": "客户甲", "source": "user_history", "source_index": 0, "quote": "助手曾猜客户甲"},
            ],
            unknown_slots=["field", "discrepancy_type", "business_date", "jurisdiction"],
        )
        history = [
            {"role": "user", "content": "这是支付指令，金额是 USD 5000"},
            {"role": "assistant", "content": "我猜是客户甲"},
            {"role": "user", "content": "不是 USD，是 HKD"},
        ]

        plan, warnings = plan_question("这笔金额为什么不对？", history, runtime)

        self.assertEqual([item.slot for item in plan.user_statements], ["document_type", "amount", "currency", "currency"])
        self.assertEqual(plan.query_context.extraction_status, "partial")
        self.assertEqual(plan.query_context.ambiguous_slots, ["currency"])
        self.assertIn("currency", plan.query_context.unknown_slots)
        self.assertTrue(any("事实槽位无法与用户原文对应" in item for item in warnings))
        self.assertFalse(plan.needs_clarification)

    def test_missing_fact_slot_contract_is_visible_as_unavailable(self):
        runtime = Mock()
        runtime.complete.return_value = '{"intent":"rule","queries":[]}'

        plan, warnings = plan_question("金额不一致如何核查？", [], runtime)

        self.assertEqual(plan.query_context.extraction_status, "unavailable")
        self.assertTrue(any("未返回结构化事实槽位" in item for item in warnings))

    def test_plan_is_strict_bounded_and_original_question_is_not_truncated(self):
        runtime = Mock()
        query = "金额" * 1900
        runtime.complete.return_value = encoded_plan(("金额核查", "general"))
        plan, _ = plan_question(query, [], runtime, max_queries=1)
        self.assertEqual(plan.queries[0].text, query)
        for response in ['[]', '{"intent":"rule","queries":[],"tools":["delete"]}', 'not JSON']:
            runtime.complete.return_value = response
            plan, warnings = plan_question("支付指令金额错误", [], runtime)
            self.assertEqual(len(plan.queries), 1)
            self.assertTrue(warnings)

    def test_clarification_does_not_infer_a_document_from_bare_amount(self):
        runtime = Mock()
        runtime.complete.return_value = encoded_plan(needs_clarification=True, clarification_question="5000涉及哪份单据、哪个金额字段？")
        plan, warnings = plan_question("这5000为什么不对？", [], runtime)
        self.assertTrue(plan.needs_clarification)
        self.assertNotIn("支付指令", plan.clarification_question)
        self.assertFalse(warnings)


class FusionTests(unittest.TestCase):
    def test_synonym_count_does_not_manufacture_extra_votes(self):
        first = evidence("A", "金额错误需核查")
        second = evidence("B", "payment amount discrepancy")
        base = [(SearchQuery(text="金额错误", family="general"), [first]),
                (SearchQuery(text="amount discrepancy", family="translated"), [second])]
        expanded = [*base, (SearchQuery(text="数额不符", family="general"), [first, first])]
        before = fuse_query_results(base, top_k=5)
        after = fuse_query_results(expanded, top_k=5)
        self.assertEqual([item["chunk_id"] for item in before], [item["chunk_id"] for item in after])
        self.assertEqual([item["metadata"]["retrieval"]["fusion_score"] for item in before],
                         [item["metadata"]["retrieval"]["fusion_score"] for item in after])
        self.assertIsNone(after[0]["similarity"])

    def test_reversed_source_arrival_is_deterministic_and_versions_do_not_merge(self):
        old, current = evidence("A", "旧条文", version="old"), evidence("A", "新条文", version="new")
        batches = [(SearchQuery(text="a", family="exact"), [old]), (SearchQuery(text="b", family="general"), [current])]
        result = fuse_query_results(batches, top_k=5)
        reverse = fuse_query_results(batches[::-1], top_k=5)
        self.assertEqual([item["content"] for item in result], [item["content"] for item in reverse])
        self.assertEqual(len(result), 2)


class RetrievalGraphTests(unittest.TestCase):
    def state(self, **extra):
        return {"query": "支付指令金额错误如何核查和更正？", "scope": "business_rules", "top_k": 5, **extra}

    def test_empty_first_round_recovers_and_evidence_only_does_not_generate(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.side_effect = [[], [evidence("procedure", "核查金额并按更正流程重新提交")]]
        runtime.complete.side_effect = [encoded_plan(), assess(rewrite="支付指令金额更正流程"), assess(selected=[1])]
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state())["result"]
        self.assertEqual(result["evidence_status"], "sufficient")
        self.assertEqual(result["retrieval_rounds"], 2)
        self.assertEqual(result["sources"][0]["content"], "核查金额并按更正流程重新提交")
        self.assertNotIn("answer", result)
        self.assertNotIn("grounding", result)
        self.assertEqual(runtime.complete.call_count, 3)

    def test_cross_round_candidates_are_preserved_to_cover_both_parts(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.side_effect = [[evidence("check", "先比对支付指令与支持单据金额")],
                                       [evidence("correct", "金额错误须更正并重新提交")]]
        runtime.complete.side_effect = [encoded_plan(), assess(rewrite="金额错误更正重新提交流程"), assess(selected=[1, 2])]
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state())["result"]
        self.assertEqual({item["document_name"] for item in result["sources"]}, {"check.txt", "correct.txt"})

    def test_ambiguous_question_skips_retrieval_and_returns_clarification(self):
        engine, runtime = Mock(), Mock()
        runtime.complete.return_value = encoded_plan(needs_clarification=True, clarification_question="请说明是哪份单据的哪个金额字段？")
        result = build_answer_graph(engine, runtime).invoke(self.state(query="这5000为什么不对？"))["result"]
        engine.retrieve.assert_not_called()
        self.assertEqual(result["stop_reason"], "clarification")
        self.assertEqual(result["retrieval_rounds"], 0)
        self.assertTrue(result["clarification_question"])

    def test_repeated_query_stops_without_repeating_a_database_call(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = []
        question = self.state()["query"]
        runtime.complete.side_effect = [encoded_plan(), assess(rewrite=question), assess(rewrite=question)]
        result = build_answer_graph(engine, runtime).invoke(self.state())["result"]
        self.assertEqual(engine.retrieve.call_count, 1)
        self.assertEqual(result["stop_reason"], "repeated_query")
        self.assertEqual(result["grounding"], "insufficient")

    def test_query_budget_and_invalid_model_selection_fail_explicitly(self):
        for response in ['{"relevant":true,"sufficient":true,"selected":[99]}',
                         '{"relevant":true,"sufficient":true,"selected":[true]}']:
            engine, runtime = Mock(), Mock()
            engine.retrieve.return_value = [evidence("A", "金额核查")]
            runtime.complete.side_effect = [encoded_plan(("payment instruction amendment", "translated")), response]
            with patch.object(settings, "RAG_MAX_RETRIEVAL_QUERIES", 1):
                result = build_answer_graph(engine, runtime).invoke(self.state())["result"]
            self.assertEqual(engine.retrieve.call_count, 1)
            self.assertEqual(result["grounding"], "insufficient")
            self.assertEqual(result["stop_reason"], "invalid_assessment")

    def test_claimed_sufficiency_with_a_missing_requirement_cannot_pass(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [evidence("A", "金额核查")]
        runtime.complete.side_effect = [encoded_plan(),
            '{"relevant":true,"sufficient":true,"selected":[1],"missing":["更正流程"]}']
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state())["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["missing"], ["更正流程"])
        self.assertEqual(result["sources"][0]["content"], "金额核查")

    def test_evidence_budget_keeps_partial_support_and_reports_gap(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [evidence("A", "金额核查"), evidence("B", "更正流程")]
        runtime.complete.side_effect = [encoded_plan(), assess(selected=[1, 2])]
        result = build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state(top_k=1))["result"]
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertEqual(result["stop_reason"], "evidence_budget")
        self.assertEqual(len(result["sources"]), 1)
        self.assertTrue(result["missing"])

    def test_request_deadline_stops_before_database_access(self):
        engine, runtime = Mock(), Mock()
        runtime.complete.return_value = encoded_plan()
        # The start receives 100; all subsequent clock reads have exhausted the budget.
        with patch("app.answer_graph.time.monotonic", side_effect=chain([100, 100], repeat(500))):
            result = build_answer_graph(engine, runtime).invoke(self.state())["result"]
        engine.retrieve.assert_not_called()
        self.assertEqual(result["stop_reason"], "time_budget")

    def test_authenticated_enhanced_endpoint_has_no_generated_answer(self):
        engine, runtime = Mock(), Mock()
        engine.retrieve.return_value = [evidence("A", "金额错误需重新提交")]
        runtime.complete.side_effect = [
            encoded_plan(user_statements=[{
                "slot": "document_type", "value": "支付指令", "source": "current_query",
                "source_index": None, "quote": "支付指令",
            }]),
            assess(selected=[1]),
        ]
        with patch.object(settings, "SERVICE_TOKEN", "test-only"), patch("app.backend_api.postgres_engine", return_value=engine), patch("app.answer_graph.SDKRuntime", return_value=runtime):
            response = TestClient(app).post("/api/v1/retrievals", headers={"Authorization": "Bearer test-only"}, json={"query": "支付指令金额错误如何处理"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("answer", response.json())
        self.assertEqual(response.json()["sources"][0]["content"], "金额错误需重新提交")
        self.assertEqual(response.json()["query_context"]["extraction_status"], "provenance_checked")
        statement = response.json()["query_context"]["user_statements"][0]
        self.assertEqual(statement["source"], "current_query")
        self.assertIsNone(statement["source_index"])
        self.assertEqual(statement["quote"], "支付指令")


if __name__ == "__main__":
    unittest.main()
