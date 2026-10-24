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
    pending=[]
    for d in documents:
        parsing=(d.fields or {}).get("_parsing") or {}
        edited=any((d.fields or {}).get(key)!=audit.get("final_value")
                   for key,audit in parsing.get("fields",{}).items())
        if parsing.get("unresolved_required") or parsing.get("unresolved_fields") or parsing.get("document_errors") or edited:
            pending.append(getattr(d,"doc_code","未命名单据"))
    if pending:
        return [RuleResult("PARSING_READY","原件识别待核实","F",Status.WARN,
            why="以下单据存在未决识别字段或不完整页面："+"、".join(pending),
            suggestion="先核实识别问题或补充原件，再运行规则；未核实金额不得当作0。")]
    bundle = build_bundle(documents)
    # Only the receipt-bound structure contract enables this association path;
    # legacy/manual documents do not acquire trusted limits by matching text.
    if any('borrowers' in ((d.fields or {}).get('_parsing') or {}).get('fields',{}) for d in documents):
        from ..parsing.facility import analyze_facility,saved_selection,verified_dtos
        stored=[((d.fields or {}).get('_parsing') or {}).get('facility_context') for d in documents]
        stored=[c for c in stored if c]
        try:
            context=analyze_facility(verified_dtos(documents),saved_selection(documents),
                stored[0].get('task_request') if stored else None)
        except ValueError:
            context={'status':'needs_review','issues':[{'message':'授信关联候选已变化，请重新核对并确认。'}]}
        if context['status']!='ready':
            return [RuleResult('FACILITY_APPLICABILITY','本次提款与授信关联待核实','A',Status.WARN,
                why='；'.join(i['message'] for i in context['issues']),
                suggestion='对照提款指令及FOL核实主体、授信品种、组额度和币种；不能使用集团总额度或静态限额推定可用余额。')]
        # Projection exists only for this run; immutable extracted fields remain.
        fol=bundle.by_type.get('FACILITY_LETTER',[{}])[0]
        bundle.by_type['FACILITY_LETTER'][0]={**fol,'_facility_context':context}
    results: list[RuleResult] = []
    for rule in RULES:
        results.append(rule.evaluate(bundle))
    return results


def summarize(results: list[RuleResult]) -> dict:
    counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
    for r in results:
        counts[r.status.value] += 1
    return counts
