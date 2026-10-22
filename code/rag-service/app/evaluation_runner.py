"""Collect paired rankings from the configured RAG retrieval stack.

The reviewed query variants are frozen inputs: the collector calls real
PostgreSQL/Embedding retrieval and optional reranking, but no answer LLM. Both
rankers receive one shared candidate set collected during this invocation.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from urllib.parse import urlsplit

from .config import settings
from .evaluation import EvaluationSet, RankingRun, evaluate
from .retrieval_fusion import evidence_key, fuse_query_results, fuse_sources
from .query_plan import SearchQuery
from .rerank import HTTPReranker


class EvaluationRunError(RuntimeError):
    pass


def evaluation_evidence_id(item):
    """Snapshot-bound opaque reference; no source text or paths in run files."""
    return "ev1:" + hashlib.sha256(evidence_key(item).encode("utf-8")).hexdigest()


def is_local_endpoint(url):
    try:
        return urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def validate_evaluation_preflight(dataset: EvaluationSet, *, allow_external_sources=False,
                                 allow_embedding_dataflow=False, allow_reranker_dataflow=False,
                                 max_cases=120, external_call_budget=None, law_source=None):
    if not 1 <= max_cases <= 500 or len(dataset.cases) > max_cases:
        raise EvaluationRunError(f"题数超过本次显式运行预算 {max_cases}")
    has_external = any("pkulaw" in case.sources for case in dataset.cases)
    external_case_count = sum("pkulaw" in case.sources for case in dataset.cases)
    if has_external and not allow_external_sources:
        raise EvaluationRunError("题集包含北大法宝；须显式启用外部来源及其费用/授权审查")
    if has_external and (external_call_budget is None or external_case_count > external_call_budget):
        raise EvaluationRunError(f"外部查询预算不足：需要 {external_case_count} 次，本次预算 {external_call_budget}")
    if has_external:
        if not settings.PKULAW_MCP_ENABLED or not settings.PKULAW_MCP_TOKEN.get_secret_value():
            raise EvaluationRunError("北大法宝检索及服务端凭证未配置")
        if law_source is not None and not law_source.configured:
            raise EvaluationRunError("题集要求北大法宝，但服务端来源未配置")
    if settings.RAG_RERANK_PROVIDER == "disabled" or not settings.RAG_RERANK_MODEL or not settings.RAG_RERANK_URL:
        raise EvaluationRunError("专用重排器未配置；无法生成有效候选重排对照")
    for case in dataset.cases:
        if len(case.retrieval_queries) > min(settings.RAG_MAX_RETRIEVAL_QUERIES, settings.RAG_MAX_QUERY_VARIANTS):
            raise EvaluationRunError("单题冻结检索表达超过服务调用预算")
    embedding_remote = bool(settings.BAILIAN_BASE_URL and not is_local_endpoint(settings.BAILIAN_BASE_URL))
    reranker_remote = not is_local_endpoint(settings.RAG_RERANK_URL)
    if embedding_remote and not allow_embedding_dataflow:
        raise EvaluationRunError("本次查询将发送到远程 Embedding；须先审核并显式允许数据流")
    if reranker_remote and not allow_reranker_dataflow:
        raise EvaluationRunError("本次候选正文将发送到远程重排器；须先审核并显式允许数据流")
    return {"has_external": has_external, "external_case_count": external_case_count,
            "embedding_remote": embedding_remote, "reranker_remote": reranker_remote}


def collect_paired_rankings(dataset: EvaluationSet, *, engine, reranker=None, law_source=None,
                            allow_external_sources=False, allow_embedding_dataflow=False,
                            allow_reranker_dataflow=False, max_cases=120, external_call_budget=None):
    reranker = reranker or HTTPReranker()
    preflight = validate_evaluation_preflight(dataset, allow_external_sources=allow_external_sources,
        allow_embedding_dataflow=allow_embedding_dataflow, allow_reranker_dataflow=allow_reranker_dataflow,
        max_cases=max_cases, external_call_budget=external_call_budget, law_source=law_source)
    has_external, external_case_count = preflight["has_external"], preflight["external_case_count"]
    if has_external and law_source is None:
        from .pkulaw import PkulawSource
        law_source = PkulawSource()
    embedding_remote, reranker_remote = preflight["embedding_remote"], preflight["reranker_remote"]

    baseline_rankings, candidate_rankings, candidate_ids = {}, {}, {}
    for case in dataset.cases:
        variants = [SearchQuery.model_validate(item.model_dump()) for item in case.retrieval_queries]
        if len(variants) > min(settings.RAG_MAX_RETRIEVAL_QUERIES, settings.RAG_MAX_QUERY_VARIANTS):
            raise EvaluationRunError("单题冻结检索表达超过服务调用预算")
        kb_batches = []
        for query in variants:
            items = engine.retrieve(query=query.text, scope=case.scope, top_k=20)
            kb_batches.append((query, items))
        pools = {"knowledge_base": fuse_query_results(kb_batches, top_k=20)}

        if "pkulaw" in case.sources:
            query = next((item for item in variants if item.family == "general"), variants[0])
            result = law_source.retrieve(query=query.text, top_k=3, timeout_seconds=settings.PKULAW_MCP_TIMEOUT_SECONDS)
            if result.get("status") != "ok":
                raise EvaluationRunError("法宝来源未完整返回；本次评测中止，不以部分结果形成排名")
            pools["pkulaw"] = fuse_query_results([(query, result["items"])], top_k=20)

        fused = fuse_sources(pools, top_k=20) if len(pools) > 1 else pools["knowledge_base"]
        candidate_ids[case.case_id] = [evaluation_evidence_id(item) for item in fused]
        baseline_rankings[case.case_id] = list(candidate_ids[case.case_id])
        if fused:
            ranked, status = reranker.rerank(query=case.query, evidence=fused, timeout_seconds=settings.RAG_RERANK_TIMEOUT_SECONDS)
            if status != "ok":
                raise EvaluationRunError("专用重排本次未完成；不生成不完整质量对照")
        else:
            ranked = []
        candidate_rankings[case.case_id] = [evaluation_evidence_id(item) for item in ranked]
        if len(candidate_rankings[case.case_id]) != len(fused) or set(candidate_rankings[case.case_id]) != set(candidate_ids[case.case_id]):
            raise EvaluationRunError("重排改变了候选集合；本次比较中止")

    if baseline_rankings.keys() != candidate_rankings.keys():
        raise EvaluationRunError("内部错误：paired rankings 不覆盖同一组题目")
    candidate_union = {case_id: sorted(set(candidate_ids[case_id])) for case_id in sorted(candidate_ids)}
    candidate_digest = hashlib.sha256(json.dumps(candidate_union, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    comparison_id = str(uuid.uuid4())
    common = {"dataset_id": dataset.dataset_id, "dataset_version": dataset.version, "split": dataset.split,
              "comparison_id": comparison_id, "candidate_set_sha256": candidate_digest}
    baseline = RankingRun.model_validate({**common, "ranker_revision": "family-normalized-rrf", "candidate_ids": candidate_ids,
                                          "rankings": baseline_rankings})
    candidate = RankingRun.model_validate({**common, "ranker_revision": f"{settings.RAG_RERANK_MODEL}@{settings.RAG_RERANK_REVISION or 'unverified'}",
                                           "candidate_ids": candidate_ids, "rankings": candidate_rankings})
    report = evaluate(dataset, baseline, candidate)
    report["collection"] = {"mode": "live-rag-retrieval", "engine": "postgres", "search_mode": settings.RAG_SEARCH_MODE,
                             "embedding_model": settings.EMBEDDING_MODEL, "rerank_provider": settings.RAG_RERANK_PROVIDER,
                             "rerank_model": settings.RAG_RERANK_MODEL, "external_sources_included": has_external,
                             "case_count": len(dataset.cases), "pkulaw_source_queries": external_case_count,
                             "pkulaw_tool_calls_upper_bound": 3 * external_case_count,
                             "retrieved_pool_per_case_max": 20, "reranked_candidates_per_case_max": 20,
                             "embedding_dataflow": "remote" if embedding_remote else "local_or_unconfigured",
                             "reranker_dataflow": "remote" if reranker_remote else "local_or_unconfigured",
                             "llm_query_rewrite": "not_used; reviewed variants frozen in evaluation set",
                             "candidate_set_sha256": candidate_digest,
                             "notice": "Candidate IDs share one collection run. Source snapshot identity is not independently attested by this runner."}
    report["report_sha256"] = hashlib.sha256(json.dumps({key: value for key, value in report.items() if key != "report_sha256"},
                                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return baseline, candidate, report
