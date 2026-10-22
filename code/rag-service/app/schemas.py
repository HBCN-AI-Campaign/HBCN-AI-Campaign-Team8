from typing import Literal

from pydantic import BaseModel, Field

from .query_plan import QueryContext


KnowledgeScope = Literal["business_rules", "project_design", "task_documents", "law", "all"]


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: KnowledgeScope = "all"     # all = business_rules + project_design 合并去重
    top_k: int = Field(default=5, ge=1, le=20)


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
    workbench_contract_version: int = 0
    service: str = "hbcn-rag-service"
    engine: str = "none"
    retrieval: bool
    document_ingestion: bool
    agentic_orchestration: bool = False
    answer_generation: bool = False
    document_source: bool = False
    external_law_mcp: bool = False
    enhanced_retrieval: bool = False
    dedicated_reranking: bool = False
    web_context: bool = False
    document_quality_review_scopes: list[str] = Field(default_factory=list)
    document_quality_review_subject: str | None = None
    supported_scopes: list[str]
    max_upload_bytes: int = 50 * 1024 * 1024
    upload_timeout_seconds: int = 900
    supported_file_extensions: list[str] = Field(default_factory=list)


class IndexResponse(BaseModel):
    status: str
    scope: KnowledgeScope
    document_ids: list[str]
    message: str


class AnswerSource(BaseModel):
    citation: int
    content: str
    document_id: str
    document_name: str
    page: int | None = None
    score: float | None = None
    chunk_id: str | None = None
    source_url: str | None = None
    reader_url: str | None = None
    metadata: dict = Field(default_factory=dict)


class AnswerResponse(BaseModel):
    query: str
    scope: KnowledgeScope
    answer: str
    sources: list[AnswerSource]
    warnings: list[str] = Field(default_factory=list)
    retrieval_rounds: int
    grounding: Literal["cited", "insufficient"]
    stop_reason: str | None = None
    clarification_question: str | None = None
    source_status: dict[str, str] = Field(default_factory=dict)
    rerank_status: str = "not_run"
    context_coverage: dict = Field(default_factory=dict)
    answer_verification: dict = Field(default_factory=dict)
    legal_applicability: dict = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class RetrievalResponse(BaseModel):
    query: str
    scope: KnowledgeScope
    sources: list[AnswerSource]
    warnings: list[str] = Field(default_factory=list)
    retrieval_rounds: int
    evidence_status: Literal["sufficient", "insufficient", "clarification"]
    stop_reason: str
    clarification_question: str | None = None
    missing: list[str] = Field(default_factory=list)
    source_status: dict[str, str] = Field(default_factory=dict)
    rerank_status: str = "not_run"
    context_coverage: dict = Field(default_factory=dict)
    legal_applicability: dict = Field(default_factory=dict)
    query_context: QueryContext = Field(default_factory=QueryContext)
