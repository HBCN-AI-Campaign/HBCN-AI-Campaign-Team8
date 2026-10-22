import json
import hashlib
import math
import io
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.evaluation import EvaluationCase, EvaluationSet, RankingRun, evaluate, load_set, ndcg_at, recall_at, validate_split_isolation


def case(case_id="BAS-001", *, group="basic", answerability="answerable", judgments=None, leakage=None):
    return EvaluationCase.model_validate({
        "case_id": case_id, "group": group, "leakage_group_id": leakage or "CASE-GROUP-0001", "locale": "zh-CN",
        "query": "合成占位问题，不是业务金标", "scope": "all", "sources": ["knowledge_base"],
        "retrieval_queries": [{"text": "合成占位问题，不是业务金标", "family": "exact"}], "answerability": answerability,
        "judgments": judgments if judgments is not None else [{"evidence_id": "law:v1:clause1", "relevance": 3}],
        "expected_handling": "answer" if answerability == "answerable" else "refuse",
        "source_snapshot": "synthetic-snapshot-v1", "reviewer_id": "synthetic-reviewer",
        "reviewed_at": "2026-10-22T00:00:00Z", "approved_for_evaluation": True,
    })


class EvaluationContractTests(unittest.TestCase):
    def test_unreviewed_duplicate_and_invalid_gold_labels_fail_closed(self):
        raw = case().model_dump()
        for changed in ({"approved_for_evaluation": False},
                        {"judgments": [{"evidence_id": "x", "relevance": 1}, {"evidence_id": "x", "relevance": 2}]},
                        {"answerability": "no_answer", "expected_handling": "refuse", "judgments": [{"evidence_id": "x", "relevance": 1}]}):
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                case_raw = {**raw, **changed}
                EvaluationCase.model_validate(case_raw)

    def test_holdout_requires_six_groups_and_at_least_twenty_each(self):
        with self.assertRaises(ValidationError):
            EvaluationSet.model_validate({"dataset_id": "RAG-HOLDOUT", "version": "1.0.0", "planning_revision": "v3",
                                          "split": "holdout", "cases": [case().model_dump()]})
        ids, cases = 1, []
        for group in ("basic", "cross_language", "multi_source_law", "historical_case", "no_answer_conflict", "permission_attack"):
            for _ in range(20):
                cases.append(case(f"CASE-{ids:03d}", group=group, leakage=f"LEAKAGE-{ids:08d}").model_dump())
                ids += 1
        dataset = EvaluationSet.model_validate({"dataset_id": "RAG-HOLDOUT", "version": "1.0.0", "planning_revision": "v3",
                                                "split": "holdout", "cases": cases})
        self.assertEqual(len(dataset.cases), 120)

    def test_rank_metrics_and_paired_bootstrap_are_deterministic(self):
        item = case(judgments=[{"evidence_id": "a", "relevance": 3}, {"evidence_id": "b", "relevance": 1}])
        self.assertEqual(recall_at(item, ["a"]), 0.5)
        self.assertEqual(ndcg_at(item, ["a", "b"]), 1.0)
        dataset = EvaluationSet.model_validate({"dataset_id": "RAG-DEV", "version": "1.0.0", "planning_revision": "v3",
                                                "split": "development", "cases": [item.model_dump()]})
        run_id, candidate_hash = "12345678-1234-5678-1234-567812345678", hashlib.sha256(json.dumps({"BAS-001": ["a", "b"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        base = RankingRun.model_validate({"dataset_id": "RAG-DEV", "dataset_version": "1.0.0", "split": "development",
                                          "ranker_revision": "rrf-v1", "comparison_id": run_id,
                                          "candidate_set_sha256": candidate_hash, "candidate_ids": {"BAS-001": ["a", "b"]},
                                          "rankings": {"BAS-001": ["b", "a"]}})
        new = RankingRun.model_validate({"dataset_id": "RAG-DEV", "dataset_version": "1.0.0", "split": "development",
                                         "ranker_revision": "reranker-v1", "comparison_id": run_id,
                                         "candidate_set_sha256": candidate_hash, "candidate_ids": {"BAS-001": ["a", "b"]},
                                         "rankings": {"BAS-001": ["a", "b"]}})
        first, second = evaluate(dataset, base, new), evaluate(dataset, base, new)
        self.assertEqual(first, second)
        self.assertEqual(first["overall"]["ndcg_at_10"]["candidate"], 1.0)
        self.assertAlmostEqual(first["overall"]["ndcg_at_10"]["paired_delta"], 0.2901902586031345)
        self.assertIn("does not measure answer correctness", first["metric_scope"])
        self.assertIsNone(first["overall"]["ndcg_at_10"]["cluster_bootstrap_delta_ci_95"])

    def test_runner_requires_exact_dataset_revision_and_case_coverage(self):
        item = case()
        dataset = EvaluationSet.model_validate({"dataset_id": "RAG-DEV", "version": "1.0.0", "planning_revision": "v3",
                                                "split": "development", "cases": [item.model_dump()]})
        run_id, candidate_hash = "12345678-1234-5678-1234-567812345678", hashlib.sha256(json.dumps({"BAS-001": ["law:v1:clause1"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        base = RankingRun.model_validate({"dataset_id": "RAG-DEV", "dataset_version": "1.0.0", "split": "development",
                                          "ranker_revision": "base", "comparison_id": run_id,
                                          "candidate_set_sha256": candidate_hash, "candidate_ids": {"BAS-001": ["law:v1:clause1"]},
                                          "rankings": {"BAS-001": ["law:v1:clause1"]}})
        wrong = RankingRun.model_validate({"dataset_id": "RAG-DEV", "dataset_version": "2.0.0", "split": "development",
                                           "ranker_revision": "candidate", "comparison_id": run_id,
                                           "candidate_set_sha256": candidate_hash, "candidate_ids": {"BAS-001": ["law:v1:clause1"]},
                                           "rankings": {"BAS-001": ["law:v1:clause1"]}})
        with self.assertRaisesRegex(ValueError, "exact dataset revision"):
            evaluate(dataset, base, wrong)
        different_candidates = RankingRun.model_validate({**base.model_dump(), "candidate_set_sha256": hashlib.sha256(json.dumps({"BAS-001": ["other"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), "candidate_ids": {"BAS-001": ["other"]},
                                                           "rankings": {"BAS-001": ["other"]}})
        with self.assertRaisesRegex(ValueError, "same retrieval run|same candidate evidence|one retrieval run"):
            evaluate(dataset, base, different_candidates)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dataset.json"
            path.write_text(json.dumps({"dataset_id": "RAG-DEV", "version": "1.0.0", "planning_revision": "v3",
                                        "split": "development", "cases": [{**item.model_dump(), "approved_for_evaluation": False}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreviewed"):
                load_set(path)

    def test_development_and_holdout_must_be_case_group_disjoint(self):
        development = EvaluationSet.model_validate({"dataset_id": "RAG-SET", "version": "1.0.0", "planning_revision": "v3",
            "split": "development", "cases": [case("DEV-001", leakage="SHARED-GROUP-0001").model_dump()]})
        holdout_rows, index = [], 0
        for group in ("basic", "cross_language", "multi_source_law", "historical_case", "no_answer_conflict", "permission_attack"):
            for _ in range(20):
                index += 1
                holdout_rows.append(case(f"HOLD-{index:03d}", group=group, leakage=f"HOLD-GROUP-{index:08d}").model_dump())
        holdout = EvaluationSet.model_validate({"dataset_id": "RAG-SET", "version": "1.0.0", "planning_revision": "v3",
            "split": "holdout", "cases": holdout_rows})
        self.assertTrue(validate_split_isolation(development, holdout))
        holdout_rows[0]["leakage_group_id"] = "SHARED-GROUP-0001"
        leaked = EvaluationSet.model_validate({"dataset_id": "RAG-SET", "version": "1.0.0", "planning_revision": "v3",
            "split": "holdout", "cases": holdout_rows})
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_split_isolation(development, leaked)

    def test_cli_writes_versioned_report_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            item = case()
            dataset = {"dataset_id": "RAG-DEV", "version": "1.0.0", "planning_revision": "v3", "split": "development",
                       "cases": [item.model_dump()]}
            run = {"dataset_id": "RAG-DEV", "dataset_version": "1.0.0", "split": "development", "ranker_revision": "rrf-v1",
                   "comparison_id": "12345678-1234-5678-1234-567812345678", "candidate_set_sha256": hashlib.sha256(json.dumps({"BAS-001": ["law:v1:clause1"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                   "candidate_ids": {"BAS-001": ["law:v1:clause1"]},
                   "rankings": {"BAS-001": ["law:v1:clause1"]}}
            for name, value in (("cases.json", dataset), ("baseline.json", run), ("candidate.json", {**run, "ranker_revision": "rerank-v1"})):
                (folder / name).write_text(json.dumps(value), encoding="utf-8")
            output = folder / "report.json"
            argv = ["evaluate-retrieval-quality.py", "--cases", str(folder / "cases.json"), "--baseline", str(folder / "baseline.json"),
                    "--candidate", str(folder / "candidate.json"), "--output", str(output)]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                runpy.run_path(str(Path(__file__).parents[1] / "scripts/evaluate-retrieval-quality.py"), run_name="__main__")
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(report["report_sha256"]), 64)
            self.assertEqual(report["candidate_revision"], "rerank-v1")
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError):
                runpy.run_path(str(Path(__file__).parents[1] / "scripts/evaluate-retrieval-quality.py"), run_name="__main__")

    def test_cli_refuses_holdout_without_development_set(self):
        groups = ("basic", "cross_language", "multi_source_law", "historical_case", "no_answer_conflict", "permission_attack")
        holdout, index = [], 0
        for group in groups:
            for _ in range(20):
                index += 1
                holdout.append(case(f"HOLD-{index:03d}", group=group, leakage=f"LEAKAGE-{index:08d}").model_dump())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "holdout.json"
            path.write_text(json.dumps({"dataset_id": "RAG-HOLDOUT", "version": "1.0.0", "planning_revision": "v3",
                                        "split": "holdout", "cases": holdout}), encoding="utf-8")
            argv = ["evaluate-retrieval-quality.py", "--cases", str(path), "--baseline", "unused", "--candidate", "unused", "--output", str(Path(folder) / "report.json")]
            with patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runpy.run_path(str(Path(__file__).parents[1] / "scripts/evaluate-retrieval-quality.py"), run_name="__main__")
            self.assertEqual(error.exception.code, 2)

    def test_both_clis_reject_invalid_data_without_printing_sensitive_validation_input(self):
        marker = "SYNTHETIC-PRIVATE-QUERY-DO-NOT-LOG"
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "cases.json"
            raw_case = {**case().model_dump(), "query": marker, "approved_for_evaluation": False}
            source.write_text(json.dumps({"dataset_id": "RAG-DEV", "version": "1.0.0", "planning_revision": "v3",
                                          "split": "development", "cases": [raw_case]}), encoding="utf-8")
            commands = (
                ("evaluate-retrieval-quality.py", ["--baseline", "unused", "--candidate", "unused", "--output", str(folder / "report.json")]),
                ("run-retrieval-evaluation.py", ["--baseline-output", str(folder / "base.json"), "--candidate-output", str(folder / "new.json"), "--report-output", str(folder / "report.json")]),
            )
            for script, flags in commands:
                stderr = io.StringIO()
                with self.subTest(script=script), patch.object(sys, "argv", [script, "--cases", str(source), *flags]), \
                        redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(Path(__file__).parents[1] / "scripts" / script), run_name="__main__")
                self.assertEqual(error.exception.code, 2)
                self.assertNotIn(marker, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(list(folder.glob("*.json")), [source])

    def test_cluster_interval_uses_case_families_and_rejects_forged_candidate_hash(self):
        cases = [case("BAS-001", leakage="FAMILY-0001"), case("BAS-002", leakage="FAMILY-0001"),
                 case("BAS-003", leakage="FAMILY-0002")]
        dataset = EvaluationSet(dataset_id="RAG-DEV", version="1.0.0", planning_revision="v3", split="development", cases=cases)
        pool = {item.case_id: ["law:v1:clause1", "unrelated"] for item in cases}
        digest = hashlib.sha256(json.dumps(pool, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        common = {"dataset_id": "RAG-DEV", "dataset_version": "1.0.0", "split": "development", "ranker_revision": "test",
                  "comparison_id": "12345678-1234-5678-1234-567812345678", "candidate_set_sha256": digest, "candidate_ids": pool}
        candidate_rankings = {**pool, "BAS-003": list(reversed(pool["BAS-003"]))}
        baseline_rankings = {key: list(reversed(value)) for key, value in pool.items()}
        baseline_rankings["BAS-003"] = pool["BAS-003"]
        baseline = RankingRun.model_validate({**common, "rankings": baseline_rankings})
        candidate = RankingRun.model_validate({**common, "rankings": candidate_rankings})
        result = evaluate(dataset, baseline, candidate)
        self.assertEqual(result["overall"]["n_independent_groups_ndcg"], 2)
        gain = 1 - 1 / math.log2(3)
        self.assertAlmostEqual(result["overall"]["ndcg_at_10"]["paired_delta"], gain / 3)
        bounds = result["overall"]["ndcg_at_10"]["cluster_bootstrap_delta_ci_95"]
        self.assertAlmostEqual(bounds[0], -gain)
        self.assertAlmostEqual(bounds[1], gain)
        self.assertEqual(result["overall"]["recall_at_20"]["paired_delta"], 0)
        self.assertIn("Recall@20 is unchanged", result["recall_interpretation"])
        with self.assertRaises(ValidationError):
            RankingRun.model_validate({**candidate.model_dump(), "candidate_set_sha256": "f" * 64})


if __name__ == "__main__":
    unittest.main()
