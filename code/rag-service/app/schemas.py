from typing import Literal

from pydantic import BaseModel, Field


KnowledgeScope = Literal["business_rules", "project_design", "task_documents", "law"]


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: KnowledgeScope = "business_rules"
    top_k: int = Field(default=8, ge=1, le=20)


class Evidence(BaseModel):
    content: str
    document_id: str | None = None
    document_name: str | None = None
    page: int | None = None
    score: float | None = None
    metadata: dict = Field(default_factory=dict)


class QueryResponse(BaseModel):
    query: str
    scope: KnowledgeScope
    evidence: list[Evidence]
    warnings: list[str] = Field(default_factory=list)


class Capabilities(BaseModel):
    service: str = "hbcn-rag-service"
    engine: str = "none"
    retrieval: bool
    document_ingestion: bool
    agentic_orchestration: bool = False
    external_law_mcp: bool = False
    supported_scopes: list[str]


class IndexResponse(BaseModel):
    status: str
    scope: KnowledgeScope
    document_ids: list[str]
    message: str
