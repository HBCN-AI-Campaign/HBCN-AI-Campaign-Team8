"""规则执行器：对一个任务的单据集合运行全部已注册规则。"""
from __future__ import annotations

from collections import defaultdict

from . import rules as _rules  # noqa: F401  触发 @register 注册
from .base import RULES, DocBundle, RuleResult, Status


def build_bundle(documents: list) -> DocBundle:
    """把 ORM Document 列表转成按 type_code 分组的 DocBundle。"""
    by_type: dict[str, list[dict]] = defaultdict(list)
    meta_by_type: dict[str, list[dict]] = defaultdict(list)
    for d in documents:
        type_code = d.type_code.value if hasattr(d.type_code, "value") else str(d.type_code)
        by_type[type_code].append(d.fields or {})
        meta_by_type[type_code].append({
            "doc_id": getattr(d, "id", None),
            "doc_code": getattr(d, "doc_code", None),
            "pdf_file": getattr(d, "pdf_file", None),
            "field_sources": getattr(d, "field_sources", None) or {},
        })
    return DocBundle(by_type=dict(by_type), meta_by_type=dict(meta_by_type))


def run_all(documents: list) -> list[RuleResult]:
    """按注册顺序执行所有规则，返回结果列表（SKIP 的也保留以便排查）。"""
    bundle = build_bundle(documents)
    results: list[RuleResult] = []
    for rule in RULES:
        results.append(rule.evaluate(bundle))
    return results


def summarize(results: list[RuleResult]) -> dict:
    counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
    for r in results:
        counts[r.status.value] += 1
    return counts
