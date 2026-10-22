"""Reviewer-assistant adapter to the RAG v1 enhanced-retrieval contract.

Owns only the business evidence policy. RAG indexing, retrieval and deployment
remain in the RAG module; task documents are supplied by the authorized API.
"""
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import settings


class _KnowledgeEvidence(BaseModel):
    model_config = ConfigDict(extra='allow')
    content: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_name: str = Field(min_length=1)
    page: int | None = None
    score: float | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class _RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    scope: Literal['business_rules']
    sources: list[_KnowledgeEvidence]
    evidence_status: Literal['sufficient', 'insufficient', 'clarification']
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    stop_reason: str = ''
    source_status: dict[str, str] = Field(default_factory=dict)
    rerank_status: str = 'not_run'
    context_coverage: dict[str, Any] = Field(default_factory=dict)
    legal_applicability: dict[str, Any] = Field(default_factory=dict)


def query_business_knowledge(query: str, *, top_k: int = 6) -> dict:
    """Use RAG's enhanced evidence retrieval for business rules only.

    No task_code/user JWT is sent to a shared knowledge endpoint. The API has
    already resolved task fields separately; no project-design/law fallback.
    Insufficiency/clarification is carried back as an explicit user-visible
    warning; retrieval candidates never become a final approval conclusion.
    """
    if not settings.RAG_BASE_URL or not settings.RAG_SERVICE_TOKEN:
        raise RuntimeError('Assistant knowledge service is not configured')
    response = httpx.post(
        settings.RAG_BASE_URL.rstrip('/') + '/api/v1/retrievals',
        json={
            'query': query,
            'scope': 'business_rules',
            'top_k': min(max(int(top_k), 1), 8),
            'sources': ['knowledge_base'],
            'purpose': 'reference',
        },
        headers={'Authorization': f'Bearer {settings.RAG_SERVICE_TOKEN}', 'Accept': 'application/json'},
        timeout=settings.ASSISTANT_RAG_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = _RetrievalResponse.model_validate(response.json())
    for item in payload.sources:
        source_scope = item.metadata.get('scope')
        if source_scope is not None and source_scope != 'business_rules':
            raise ValueError('Knowledge evidence scope does not match business rules')
    # Keep the assistant's stable internal shape while preserving RAG citation
    # locators and exposing retrieval gaps instead of implying complete coverage.
    limit = min(max(int(top_k), 1), 8)
    warnings = list(dict.fromkeys(payload.warnings))
    if payload.evidence_status != 'sufficient':
        if payload.evidence_status == 'clarification' and payload.clarification_question:
            warnings.append(f"知识库需要补充条件：{payload.clarification_question[:500]}")
        else:
            warnings.append('知识库证据不足，当前建议需由审核人员补充核实。')
        if payload.missing:
            warnings.append('检索缺口：' + '；'.join(value[:160] for value in payload.missing[:4]))
        stop_reason = {
            'time_budget': '知识库检索达到时限，证据覆盖可能不完整。',
            'query_budget': '知识库检索达到查询预算，证据覆盖可能不完整。',
            'evidence_budget': '知识库检索达到证据预算，证据覆盖可能不完整。',
            'context_budget': '问题上下文超出检索预算，证据覆盖可能不完整。',
            'source_withdrawn': '检索期间参考来源发生变化，当前结果需重新核实。',
        }.get(payload.stop_reason)
        if stop_reason:
            warnings.append(stop_reason)
    degraded_sources = [name for name, status in payload.source_status.items()
                        if status not in {'ok', 'ready', 'available', 'not_requested'}]
    if degraded_sources:
        warnings.append('部分知识来源未能完整提供：' + '、'.join(degraded_sources[:4]) + '。')
    if payload.rerank_status == 'unavailable':
        warnings.append('知识库排序能力不可用；请人工检查返回的依据顺序和覆盖范围。')
    coverage = payload.context_coverage
    if coverage.get('input_complete') is False or coverage.get('requires_reassessment') is True:
        warnings.append('知识库未能确认本轮证据上下文完整，需由审核人员复核。')
    if payload.legal_applicability.get('requires_review') is True:
        warnings.append('检索服务提示法规适用性需要专项复核；本次助手查询不作法规结论。')
    if not payload.sources and payload.evidence_status == 'sufficient':
        warnings.append('知识库未返回可引用的原文片段，本轮不将其视为已提供审核依据。')
    evidence = []
    for item in payload.sources[:limit]:
        metadata = dict(item.metadata)
        metadata['scope'] = 'business_rules'
        evidence.append({
            'content': item.content,
            'document_id': item.document_id,
            'document_name': item.document_name,
            'page': item.page,
            'score': item.score,
            'chunk_id': item.chunk_id,
            'metadata': metadata,
        })
    if len(payload.sources) > limit:
        warnings.append('知识库返回候选超过本轮输入预算，已限制数量。')
    return {'scope': payload.scope, 'evidence': evidence, 'warnings': list(dict.fromkeys(warnings))}
