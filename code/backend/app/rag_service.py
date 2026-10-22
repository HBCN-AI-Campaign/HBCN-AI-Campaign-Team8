"""RAG 服务适配层：主项目调用独立 hbcn-rag-service 的 HTTP 客户端。

业务边界：
- 主项目通过本适配层访问独立的 `code/rag-service`（默认端口 8010），
  不直接接触检索引擎或存储，避免把内部鉴权与字段结构泄露给调用方。
- 本模块只做「服务鉴权 + scope 映射 + 证据透传」，不实现切片、向量或检索；
  检索引擎由独立服务维护，业务检索契约由 rag-service 定义。

scope 映射（主项目语义 → rag-service dataset scope）：

    knowledge_base -> business_rules + project_design（通用业务/方案知识，合并返回）
    task_documents  -> 暂不开放（需主项目 task_code 权限过滤后接入）
    law             -> 暂不开放（需商业法规 API 的 MCP 授权适配后接入）

未配置 RAG_BASE_URL 时抛 :class:`RAGServiceNotConfiguredError`，调用方应回退本地证据。
"""
from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import settings


class RAGServiceError(RuntimeError):
    """rag-service 调用失败或返回异常。"""


class RAGServiceNotConfiguredError(RAGServiceError):
    """RAG_BASE_URL 尚未配置。"""


class _RetrievedSource(BaseModel):
    model_config = ConfigDict(strict=True)

    content: str
    document_id: str
    document_name: str
    page: int | None = None
    score: float | None = None
    chunk_id: str | None = None
    source_url: str | None = None
    reader_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class _RetrievalPayload(BaseModel):
    """Consumer-owned projection: accept additive fields, reject broken v1 types."""
    model_config = ConfigDict(strict=True)

    sources: list[_RetrievedSource]
    evidence_status: Literal["sufficient", "insufficient", "clarification"]
    retrieval_rounds: int = Field(ge=0)
    stop_reason: str
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    source_status: dict[str, str] = Field(default_factory=dict)
    rerank_status: str = "not_run"
    context_coverage: dict[str, Any] = Field(default_factory=dict)
    legal_applicability: dict[str, Any] = Field(default_factory=dict)


def _truncate_utf16(text: str, limit: int) -> str:
    """Match the downstream JavaScript SDK's UTF-16 character budget."""
    encoded = text.encode("utf-16-le")
    return encoded[: limit * 2].decode("utf-16-le", errors="ignore")


# 主项目 scope -> rag-service dataset scope（见 code/rag-service/app/schemas.py）
_SCOPE_MAP: dict[str, tuple[str, ...]] = {
    "knowledge_base": ("business_rules", "project_design"),
    "task_documents": (),
    "law": (),
}

_UNSUPPORTED_SCOPE_NOTE = {
    "task_documents": "任务级文档检索暂未开放，已回退任务本地证据",
    "law": "法规检索暂未开放，等待商业法规 API 的 MCP 授权适配",
}


class RAGClient:
    """主项目侧 rag-service HTTP 客户端。

    ``query`` 的返回结构与 rag-service 的 QueryResponse 对齐：:

        {
            "evidence": [{"content", "document_id", "document_name", "page", "score", "metadata"}],
            "warnings": ["..."],
        }
    """

    def __init__(self) -> None:
        self.base_url = settings.RAG_BASE_URL.rstrip("/")
        self.token = settings.RAG_SERVICE_TOKEN
        self.timeout = settings.RAG_REQUEST_TIMEOUT

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _require_configured(self) -> None:
        if not self.base_url:
            raise RAGServiceNotConfiguredError("RAG_BASE_URL 尚未配置")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def query(
        self,
        *,
        query: str,
        scope: str = "knowledge_base",
        task_code: str | None = None,
        top_k: int = 6,
        agentic: bool = True,
        include_external_law: bool = False,
    ) -> dict[str, Any]:
        """检索知识库证据，返回 ``{"evidence": [...], "warnings": [...]}``。

        ``task_code`` / ``agentic`` 为上层契约占位：任务级权限过滤与 SDK 编排
        由调用方负责，当前适配层不消费；``include_external_law`` 在法规 MCP
        授权接入前只会附加提示，不发起法规检索。
        """
        del task_code, agentic
        self._require_configured()

        if scope == "law" or include_external_law:
            return {"evidence": [], "warnings": [_UNSUPPORTED_SCOPE_NOTE["law"]]}

        scopes = _SCOPE_MAP.get(scope)
        if not scopes:
            note = _UNSUPPORTED_SCOPE_NOTE.get(scope, f"范围 {scope} 暂未开放")
            return {"evidence": [], "warnings": [note]}

        evidence: list[dict[str, Any]] = []
        warnings: list[str] = []
        seen: set[tuple[str, str]] = set()
        for rag_scope in scopes:
            payload = self._post(
                "/api/v1/query",
                {"query": query, "scope": rag_scope, "top_k": top_k},
            )
            warnings.extend(warning for warning in payload.get("warnings") or [] if warning not in warnings)
            for item in payload.get("evidence") or []:
                if not isinstance(item, dict):
                    continue
                # 同一文档片段可能同时命中两个 dataset，按 (document_id, content) 去重。
                key = (str(item.get("document_id") or ""), str(item.get("content") or ""))
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(item)
        return {"evidence": evidence, "warnings": warnings}

    def retrieve(
        self,
        *,
        query: str,
        top_k: int = 6,
        conversation: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Use the enhanced evidence-only endpoint for Agent and assistant callers."""
        self._require_configured()
        bounded_conversation = []
        for item in conversation or []:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if isinstance(content, str) and content:
                bounded_conversation.append({
                    "role": item["role"],
                    "content": _truncate_utf16(content, 4_000),
                })
        bounded_conversation = bounded_conversation[-12:]
        payload = self._post(
            "/api/v1/retrievals",
            {
                "query": query,
                "scope": "all",
                "top_k": min(max(top_k, 1), 8),
                "sources": ["knowledge_base"],
                "purpose": "reference",
                "conversation": bounded_conversation,
            },
        )
        try:
            parsed = _RetrievalPayload.model_validate(payload)
        except ValidationError:
            # ValidationError contains rejected source values; do not propagate
            # that text into logs, execution steps, or model instructions.
            raise RAGServiceError("增强检索响应不符合 v1 契约") from None
        if parsed.evidence_status == "sufficient" and not any(
            item.content.strip() for item in parsed.sources
        ):
            raise RAGServiceError("增强检索充分性状态缺少原文依据")
        warnings = list(parsed.warnings)
        status = parsed.evidence_status
        if status in {"insufficient", "clarification"}:
            warning = "增强检索未确认充分依据；回答须说明缺口或请求澄清，不得把候选片段当作已核实结论。"
            if warning not in warnings:
                warnings.append(warning)
        result = parsed.model_dump()
        result["evidence"] = result.pop("sources")
        result["warnings"] = warnings
        return result

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise RAGServiceError(f"rag-service 请求失败：{exc}") from exc
        if response.status_code >= 400:
            raise RAGServiceError(f"rag-service 返回 {response.status_code}：{response.text[:200]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RAGServiceError("rag-service 返回了无效 JSON") from exc
        if not isinstance(data, dict):
            raise RAGServiceError("rag-service 响应格式错误")
        return data
