"""Leakage-aware, content-free retrieval quality evaluation contracts."""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


GROUPS = ("basic", "cross_language", "multi_source_law", "historical_case", "no_answer_conflict", "permission_attack")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Judgment(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    relevance: int = Field(ge=0, le=3)


class QueryVariant(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    family: Literal["exact", "general", "translated"]


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._:-]{2,79}$")
    group: Literal["basic", "cross_language", "multi_source_law", "historical_case", "no_answer_conflict", "permission_attack"]
    leakage_group_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._:-]{7,99}$")
    locale: Literal["zh-CN", "en", "mixed", "other"]
    query: str = Field(min_length=1, max_length=4000)
    scope: Literal["all", "business_rules", "project_design", "law"]
    sources: list[Literal["knowledge_base", "pkulaw"]] = Field(min_length=1, max_length=2)
    retrieval_queries: list[QueryVariant] = Field(min_length=1, max_length=6)
    answerability: Literal["answerable", "no_answer", "insufficient"]
    judgments: list[Judgment] = Field(max_length=500)
    expected_handling: Literal["answer", "refuse", "qualify", "clarify", "manual_review"]
    source_snapshot: str = Field(min_length=1, max_length=200)
    reviewer_id: str = Field(min_length=3, max_length=100)
    reviewed_at: str = Field(min_length=20, max_length=40)
    approved_for_evaluation: bool

    @field_validator("reviewed_at")
    @classmethod
    def timezone_aware_review_time(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("reviewed_at must be ISO-8601") from None
        if parsed.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_labels(self):
        ids = [item.evidence_id for item in self.judgments]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence judgments must be unique")
        relevant = [item for item in self.judgments if item.relevance > 0]
        if self.answerability == "answerable" and not relevant:
            raise ValueError("answerable cases require at least one relevant evidence judgment")
        if self.answerability == "no_answer" and relevant:
            raise ValueError("no_answer cases cannot label evidence as relevant")
        allowed = {"answerable": {"answer", "manual_review"}, "no_answer": {"refuse", "clarify"},
                   "insufficient": {"qualify", "clarify", "manual_review"}}[self.answerability]
        if self.expected_handling not in allowed:
            raise ValueError("expected handling conflicts with answerability label")
        if not self.approved_for_evaluation:
            raise ValueError("only individually reviewed cases may enter an evaluation run")
        if len(self.sources) != len(set(self.sources)) or "knowledge_base" not in self.sources:
            raise ValueError("evaluation sources must be unique and include the knowledge base")
        if "pkulaw" in self.sources and self.scope not in {"all", "law"}:
            raise ValueError("Pkulaw evaluation requires the law or all knowledge scope")
        if self.retrieval_queries[0].text != self.query or self.retrieval_queries[0].family != "exact":
            raise ValueError("the first retrieval query must preserve the exact original question")
        if len({item.text for item in self.retrieval_queries}) != len(self.retrieval_queries):
            raise ValueError("retrieval query variants must be unique")
        return self


class EvaluationSet(StrictModel):
    dataset_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._:-]{2,99}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    planning_revision: str = Field(min_length=1, max_length=100)
    split: Literal["development", "holdout"]
    cases: list[EvaluationCase] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_set(self):
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique within a set")
        if self.split == "holdout":
            counts = Counter(item.group for item in self.cases)
            missing = {group: counts[group] for group in GROUPS if counts[group] < 20}
            if missing:
                raise ValueError(f"frozen holdout requires at least 20 reviewed cases per group: {missing}")
        return self


def validate_split_isolation(development: EvaluationSet, holdout: EvaluationSet):
    """Reject case/document-family overlap before revealing holdout metrics."""
    if development.split != "development" or holdout.split != "holdout":
        raise ValueError("split isolation requires development and holdout datasets")
    if (development.dataset_id, development.planning_revision) != (holdout.dataset_id, holdout.planning_revision):
        raise ValueError("development and holdout must share dataset identity and planning revision")
    dev_cases = {case.case_id for case in development.cases}
    dev_groups = {case.leakage_group_id for case in development.cases}
    holdout_cases = {case.case_id for case in holdout.cases}
    holdout_groups = {case.leakage_group_id for case in holdout.cases}
    if dev_cases & holdout_cases or dev_groups & holdout_groups:
        raise ValueError("development and holdout overlap by case or leakage group")
    return True


class RankingRun(StrictModel):
    dataset_id: str
    dataset_version: str
    split: Literal["development", "holdout"]
    ranker_revision: str
    comparison_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    candidate_set_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_ids: dict[str, list[str]]
    rankings: dict[str, list[str]]

    @model_validator(mode="after")
    def complete_unique_rankings(self):
        if set(self.candidate_ids) != set(self.rankings):
            raise ValueError("candidate evidence must cover every ranked case")
        for case_id, items in self.candidate_ids.items():
            ranked = self.rankings[case_id]
            if len(items) > 1000 or len(items) != len(set(items)):
                raise ValueError("invalid candidate evidence")
            if len(ranked) != len(items) or set(ranked) != set(items):
                raise ValueError("rankings must contain every candidate exactly once")
        canonical = {case_id: sorted(items) for case_id, items in sorted(self.candidate_ids.items())}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if digest != self.candidate_set_sha256:
            raise ValueError("candidate set digest does not match its contents")
        return self


def load_set(path: str | Path) -> EvaluationSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return EvaluationSet.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("evaluation set is missing, invalid or contains unreviewed cases") from exc


def load_ranking(path: str | Path) -> RankingRun:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        run = RankingRun.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("ranking run is missing or invalid") from exc
    return run


def recall_at(case: EvaluationCase, ranked: list[str], k=20) -> float | None:
    relevant = {item.evidence_id for item in case.judgments if item.relevance > 0}
    if not relevant:
        return None
    return len(relevant.intersection(ranked[:k])) / len(relevant)


def ndcg_at(case: EvaluationCase, ranked: list[str], k=10) -> float | None:
    grades = {item.evidence_id: item.relevance for item in case.judgments}
    if not any(grades.values()):
        return None

    def dcg(values):
        return sum((2 ** grades.get(identifier, 0) - 1) / math.log2(position + 2)
                   for position, identifier in enumerate(values[:k]))

    ideal = sorted(grades, key=lambda identifier: (-grades[identifier], identifier))[:k]
    best = dcg(ideal)
    return dcg(ranked) / best if best else None


def _mean(values):
    return sum(values) / len(values) if values else None


def _bootstrap_cluster_interval(cluster_differences, *, seed, iterations=2000):
    if len(cluster_differences) < 2:
        return None
    rng = random.Random(seed)
    n = len(cluster_differences)
    samples = []
    for _ in range(iterations):
        draw = [cluster_differences[rng.randrange(n)] for _ in range(n)]
        samples.append(sum(total for total, count in draw) / sum(count for total, count in draw))
    samples.sort()
    return [samples[math.floor(0.025 * (iterations - 1))], samples[math.ceil(0.975 * (iterations - 1))]]


def evaluate(dataset: EvaluationSet, baseline: RankingRun, candidate: RankingRun):
    expected = {case.case_id for case in dataset.cases}
    for run in (baseline, candidate):
        if (run.dataset_id, run.dataset_version, run.split) != (dataset.dataset_id, dataset.version, dataset.split):
            raise ValueError("ranking run does not match the exact dataset revision and split")
        if set(run.rankings) != expected:
            raise ValueError("every and only dataset case must have one ranking result")
    if baseline.comparison_id != candidate.comparison_id or baseline.candidate_set_sha256 != candidate.candidate_set_sha256:
        raise ValueError("baseline and candidate must share one retrieval run and candidate set")
    if baseline.candidate_ids != candidate.candidate_ids:
        raise ValueError("ranker comparison must use the same candidate evidence per case")
    for run in (baseline, candidate):
        if any(not set(run.rankings[case_id]).issubset(run.candidate_ids[case_id]) for case_id in expected):
            raise ValueError("ranked evidence is outside the candidate set")

    rows = []
    for case in dataset.cases:
        if case.answerability == "no_answer":
            continue
        before, after = baseline.rankings[case.case_id], candidate.rankings[case.case_id]
        recall_before, recall_after = recall_at(case, before), recall_at(case, after)
        ndcg_before, ndcg_after = ndcg_at(case, before), ndcg_at(case, after)
        rows.append({"case_id": case.case_id, "group": case.group,
                     "baseline_recall_at_20": recall_before, "candidate_recall_at_20": recall_after,
                     "baseline_ndcg_at_10": ndcg_before, "candidate_ndcg_at_10": ndcg_after,
                     "recall_delta": (recall_after - recall_before) if recall_before is not None else None,
                     "ndcg_delta": (ndcg_after - ndcg_before) if ndcg_before is not None else None})

    groups = sorted({row["group"] for row in rows})
    leakage_groups = {case.case_id: case.leakage_group_id for case in dataset.cases}

    def summary(subset):
        recall_before = [row["baseline_recall_at_20"] for row in subset if row["baseline_recall_at_20"] is not None]
        recall_after = [row["candidate_recall_at_20"] for row in subset if row["candidate_recall_at_20"] is not None]
        ndcg_before = [row["baseline_ndcg_at_10"] for row in subset if row["baseline_ndcg_at_10"] is not None]
        ndcg_after = [row["candidate_ndcg_at_10"] for row in subset if row["candidate_ndcg_at_10"] is not None]
        recall_diff = [row["candidate_recall_at_20"] - row["baseline_recall_at_20"] for row in subset if row["baseline_recall_at_20"] is not None]
        ndcg_diff = [row["candidate_ndcg_at_10"] - row["baseline_ndcg_at_10"] for row in subset if row["baseline_ndcg_at_10"] is not None]
        def cluster_differences(key):
            clusters = {}
            for row in subset:
                if row[key] is not None:
                    clusters.setdefault(leakage_groups[row["case_id"]], []).append(row[key])
            return [(sum(values), len(values)) for values in clusters.values()]

        recall_clusters = cluster_differences("recall_delta")
        ndcg_clusters = cluster_differences("ndcg_delta")
        return {"n": len(subset), "n_recall": len(recall_diff), "n_ndcg": len(ndcg_diff),
                "n_independent_groups_recall": len(recall_clusters), "n_independent_groups_ndcg": len(ndcg_clusters),
                "recall_at_20": {"baseline": _mean(recall_before), "candidate": _mean(recall_after),
                "paired_delta": _mean(recall_diff), "cluster_bootstrap_delta_ci_95": _bootstrap_cluster_interval(recall_clusters, seed=20)},
                "ndcg_at_10": {"baseline": _mean(ndcg_before), "candidate": _mean(ndcg_after),
                "paired_delta": _mean(ndcg_diff), "cluster_bootstrap_delta_ci_95": _bootstrap_cluster_interval(ndcg_clusters, seed=10)}}

    report = {"dataset": {"id": dataset.dataset_id, "version": dataset.version, "split": dataset.split,
                          "planning_revision": dataset.planning_revision},
              "comparison_id": baseline.comparison_id, "candidate_set_sha256": baseline.candidate_set_sha256,
              "baseline_revision": baseline.ranker_revision, "candidate_revision": candidate.ranker_revision,
              "metric_scope": "retrieval ranking only; does not measure answer correctness, ACL, legal applicability or refusal quality",
              "comparison_design": "paired reranking of identical candidate sets",
              "recall_interpretation": "Recall@20 is unchanged when both rankings contain the same pool of at most 20 candidates; use nDCG@10 for reranker gains and a separate retrieval experiment for recall gains",
              "interval_method": "paired leakage-group cluster bootstrap, 2000 draws; sample whole groups and compute per-question mean delta; fewer than two groups has no interval",
              "excluded_no_answer_cases": sum(case.answerability == "no_answer" for case in dataset.cases),
              "overall": summary(rows), "by_group": {group: summary([row for row in rows if row["group"] == group]) for group in groups}}
    report["report_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return report
