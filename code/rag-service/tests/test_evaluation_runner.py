import unittest
import io
import json
import runpy
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch
from pydantic import SecretStr

from app.config import settings
from app.evaluation import EvaluationSet
from app.evaluation_runner import EvaluationRunError, collect_paired_rankings, validate_evaluation_preflight


def dataset(*, sources=None, scope="all", queries=None):
    query = "合成查询，不是真实业务金标"
    case = {"case_id": "EVAL-001", "group": "basic", "leakage_group_id": "LEAKAGE-00000001", "locale": "zh-CN",
            "query": query, "scope": scope, "sources": sources or ["knowledge_base"],
            "retrieval_queries": queries or [{"text": query, "family": "exact"}], "answerability": "answerable",
            "judgments": [{"evidence_id": "synthetic", "relevance": 3}], "expected_handling": "answer",
            "source_snapshot": "synthetic-v1", "reviewer_id": "synthetic-reviewer", "reviewed_at": "2026-10-22T00:00:00Z",
            "approved_for_evaluation": True}
    return EvaluationSet.model_validate({"dataset_id": "EVAL-SET", "version": "1.0.0", "planning_revision": "v3",
                                         "split": "development", "cases": [case]})


def evidence(name, relevance):
    return {"document_id": "doc-" + name, "chunk_id": name, "content": "synthetic evidence " + name,
            "document_keyword": name + ".txt", "similarity": relevance,
            "metadata": {"source_type": "knowledge_base", "version": "source-v1"}}


class LiveRetrievalEvaluationTests(unittest.TestCase):
    def test_real_retrieval_adapter_pairs_rrf_and_reranker_on_same_candidates(self):
        first, second = evidence("first", 0.9), evidence("second", 0.5)
        engine, reranker = Mock(), Mock()
        engine.retrieve.side_effect = [[first, second], [second, first]]
        reranker.rerank.return_value = ([second, first], "ok")
        variants = [{"text": "合成查询，不是真实业务金标", "family": "exact"}, {"text": "payment discrepancy", "family": "translated"}]
        with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic-reranker"), \
                patch.object(settings, "RAG_RERANK_REVISION", "test-revision"), \
                patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1:1234/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1:5678/rerank"):
            baseline, candidate, report = collect_paired_rankings(dataset(queries=variants), engine=engine, reranker=reranker)
        self.assertEqual(engine.retrieve.call_count, 2)
        self.assertTrue(all(call.kwargs["top_k"] == 20 for call in engine.retrieve.call_args_list))
        self.assertEqual(set(baseline.rankings["EVAL-001"]), set(candidate.rankings["EVAL-001"]))
        self.assertEqual(baseline.comparison_id, candidate.comparison_id)
        self.assertEqual(baseline.candidate_set_sha256, report["candidate_set_sha256"])
        self.assertEqual(candidate.rankings["EVAL-001"][0], baseline.rankings["EVAL-001"][1])
        self.assertNotIn("synthetic evidence", str(report))

    def test_remote_source_requires_explicit_enablement_before_calls(self):
        law = Mock(configured=True)
        engine, reranker = Mock(), Mock()
        with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1:1234/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1:5678/rerank"):
            with self.assertRaisesRegex(EvaluationRunError, "显式启用"):
                collect_paired_rankings(dataset(sources=["knowledge_base", "pkulaw"], scope="law"),
                                        engine=engine, reranker=reranker, law_source=law)
        engine.retrieve.assert_not_called()
        law.retrieve.assert_not_called()

    def test_partial_external_results_abort_the_comparison(self):
        law = Mock(configured=True)
        law.retrieve.return_value = {"status": "partial", "items": [evidence("law", 1.0)], "warnings": ["truncated"]}
        engine, reranker = Mock(), Mock()
        engine.retrieve.return_value = [evidence("kb", 1.0)]
        with patch.object(settings, "PKULAW_MCP_ENABLED", True), patch.object(settings, "PKULAW_MCP_TOKEN", SecretStr("synthetic-token")), \
                patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1:1234/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1:5678/rerank"):
            with self.assertRaisesRegex(EvaluationRunError, "未完整返回"):
                collect_paired_rankings(dataset(sources=["knowledge_base", "pkulaw"], scope="law"), engine=engine,
                                        reranker=reranker, law_source=law, allow_external_sources=True, external_call_budget=1)
        reranker.rerank.assert_not_called()

    def test_missing_reranker_cannot_emit_a_fake_candidate_comparison(self):
        with patch.object(settings, "RAG_RERANK_PROVIDER", "disabled"), patch.object(settings, "RAG_RERANK_MODEL", ""):
            with self.assertRaisesRegex(EvaluationRunError, "未配置"):
                collect_paired_rankings(dataset(), engine=Mock(), reranker=Mock())

    def test_case_and_external_call_budgets_are_checked_before_work(self):
        engine, law = Mock(), Mock(configured=True)
        with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), patch.object(settings, "RAG_RERANK_MODEL", "synthetic"):
            with self.assertRaisesRegex(EvaluationRunError, "运行预算"):
                collect_paired_rankings(dataset(), engine=engine, max_cases=0)
            with self.assertRaisesRegex(EvaluationRunError, "外部查询预算"):
                collect_paired_rankings(dataset(sources=["knowledge_base", "pkulaw"], scope="law"), engine=engine,
                                        law_source=law, allow_external_sources=True, external_call_budget=0)
        engine.retrieve.assert_not_called()
        law.retrieve.assert_not_called()

    def test_remote_embedding_and_reranker_dataflows_require_explicit_flags(self):
        engine = Mock()
        with patch.object(settings, "PKULAW_MCP_ENABLED", True), patch.object(settings, "PKULAW_MCP_TOKEN", SecretStr("synthetic-token")), \
                patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                patch.object(settings, "BAILIAN_BASE_URL", "https://embedding.example/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "https://ranker.example/v2/rerank"):
            with self.assertRaisesRegex(EvaluationRunError, "远程 Embedding"):
                collect_paired_rankings(dataset(), engine=engine, reranker=Mock())
            with self.assertRaisesRegex(EvaluationRunError, "远程重排器"):
                collect_paired_rankings(dataset(), engine=engine, reranker=Mock(), allow_embedding_dataflow=True)
        engine.retrieve.assert_not_called()

    def test_ranker_timeout_aborts_all_paired_outputs(self):
        engine, reranker = Mock(), Mock()
        engine.retrieve.return_value = [evidence("kb", 1.0)]
        reranker.rerank.return_value = ([evidence("kb", 1.0)], "unavailable")
        with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1:1234/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1:5678/rerank"):
            with self.assertRaisesRegex(EvaluationRunError, "未完成"):
                collect_paired_rankings(dataset(), engine=engine, reranker=reranker)

    def test_preflight_rejects_unapproved_spend_and_dataflows_without_constructing_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            cases = folder / "cases.json"
            cases.write_text(dataset().model_dump_json(), encoding="utf-8")
            argv = ["run-retrieval-evaluation.py", "--cases", str(cases), "--baseline-output", str(folder / "base.json"),
                    "--candidate-output", str(folder / "candidate.json"), "--report-output", str(folder / "report.json")]
            with patch.object(sys, "argv", argv), patch("app.engine.engine_kind", return_value="postgres"), \
                    patch("app.engine.get_engine") as initialize_engine, \
                    patch.object(settings, "RAG_RERANK_PROVIDER", "disabled"), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runpy.run_path(str(Path(__file__).parents[1] / "scripts/run-retrieval-evaluation.py"), run_name="__main__")
            self.assertEqual(error.exception.code, 2)
            initialize_engine.assert_not_called()
            self.assertFalse((folder / "report.json").exists())

    def test_twenty_candidates_are_retained_for_recall_at_twenty(self):
        items = [evidence(f"item-{index:02d}", 1.0) for index in range(20)]
        engine, reranker = Mock(), Mock()
        engine.retrieve.return_value = items
        reranker.rerank.side_effect = lambda **kwargs: (list(reversed(kwargs["evidence"])), "ok")
        with patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1/v1"), \
                patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1/rerank"):
            baseline, candidate, report = collect_paired_rankings(dataset(), engine=engine, reranker=reranker)
        self.assertEqual(len(baseline.rankings["EVAL-001"]), 20)
        self.assertEqual(candidate.rankings["EVAL-001"], list(reversed(baseline.rankings["EVAL-001"])))
        self.assertTrue(all(identifier.startswith("ev1:") for identifier in baseline.rankings["EVAL-001"]))

    def test_collection_cli_writes_all_three_matching_outputs(self):
        from app.evaluation import load_ranking
        from app.evaluation_runner import evaluation_evidence_id
        items = [evidence("first", 0.9), evidence("second", 0.5)]
        engine = Mock()
        engine.retrieve.return_value = items
        reranker = Mock()
        reranker.rerank.side_effect = lambda **kwargs: (list(reversed(kwargs["evidence"])), "ok")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            cases = folder / "cases.json"
            cases.write_text(dataset().model_dump_json(), encoding="utf-8")
            argv = ["run-retrieval-evaluation.py", "--cases", str(cases), "--baseline-output", str(folder / "base.json"),
                    "--candidate-output", str(folder / "candidate.json"), "--report-output", str(folder / "report.json")]
            with patch.object(sys, "argv", argv), patch("app.engine.engine_kind", return_value="postgres"), \
                    patch("app.engine.get_engine", return_value=engine), patch("app.evaluation_runner.HTTPReranker", return_value=reranker), \
                    patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                    patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                    patch.object(settings, "BAILIAN_BASE_URL", "http://127.0.0.1/v1"), \
                    patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1/rerank"), redirect_stdout(io.StringIO()):
                runpy.run_path(str(Path(__file__).parents[1] / "scripts/run-retrieval-evaluation.py"), run_name="__main__")
            baseline, candidate = load_ranking(folder / "base.json"), load_ranking(folder / "candidate.json")
            report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(baseline.comparison_id, candidate.comparison_id)
            self.assertEqual(report["comparison_id"], baseline.comparison_id)
            self.assertEqual(candidate.rankings["EVAL-001"], list(reversed(baseline.rankings["EVAL-001"])))
            self.assertEqual(set(baseline.candidate_ids["EVAL-001"]), {evaluation_evidence_id(item) for item in items})
            self.assertNotIn("synthetic evidence", (folder / "base.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
