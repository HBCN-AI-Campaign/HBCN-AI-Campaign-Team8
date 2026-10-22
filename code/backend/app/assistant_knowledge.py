"""Reviewer-assistant adapter to the existing RAG query contract.

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
    document_id: str | None = None
    document_name: str | None = None
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class _KnowledgeResponse(BaseModel):
    scope: Literal['business_rules']
    evidence: list[_KnowledgeEvidence]
    warnings: list[str] = Field(default_factory=list)


def query_business_knowledge(query: str, *, top_k: int = 6) -> dict:
    """Query shared business rules only; reject malformed or widened scope.

    No task_code/user JWT is sent to a shared knowledge endpoint. The API has
    already resolved task fields separately; no project-design/law fallback.
    """
    if not settings.RAG_BASE_URL or not settings.RAG_SERVICE_TOKEN:
        raise RuntimeError('Assistant knowledge service is not configured')
    response = httpx.post(
        settings.RAG_BASE_URL.rstrip('/') + '/api/v1/query',
        json={'query': query, 'scope': 'business_rules', 'top_k': top_k},
        headers={'Authorization': f'Bearer {settings.RAG_SERVICE_TOKEN}', 'Accept': 'application/json'},
        timeout=settings.RAG_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = _KnowledgeResponse.model_validate(response.json())
    for item in payload.evidence:
        source_scope = item.metadata.get('scope')
        if source_scope is not None and source_scope != 'business_rules':
            raise ValueError('Knowledge evidence scope does not match business rules')
    # Preserve chunk IDs and locator fields while enforcing the total budget.
    result = payload.model_dump()
    if len(result['evidence']) > top_k:
        result['warnings'].append('知识库返回的候选数量超过本轮预算，已限制数量')
        result['evidence'] = result['evidence'][:top_k]
    return result
