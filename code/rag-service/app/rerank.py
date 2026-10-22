"""Adapter for the documented Cohere-compatible dedicated rerank API.

No LLM approximation or silent fallback. A configured, failed reranker is
reported to the graph; scores never represent approval or legal applicability.
"""
from __future__ import annotations

import json
import asyncio
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import settings
from .request_control import check_cancelled, run_async


class RerankError(RuntimeError):
    pass


class RankedItem(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    index: int = Field(ge=0)
    relevance_score: float = Field(ge=0, le=1)


def validate_endpoint(value):
    try:
        endpoint = urlsplit(value)
        local = endpoint.hostname in {"127.0.0.1", "localhost", "::1"}
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or not endpoint.hostname:
            raise ValueError
        if endpoint.scheme != "https" and not (local and endpoint.scheme == "http"):
            raise ValueError
        if not local and not settings.RAG_RERANK_ALLOW_EXTERNAL:
            raise RerankError("远程重排数据流尚未显式允许，请确认部署与资料授权边界")
        return value
    except ValueError:
        raise RerankError("重排地址无效，仅支持 HTTPS 或本机 HTTP，凭证须放在服务端请求头") from None


class HTTPReranker:
    def __init__(self, *, client_factory=httpx.AsyncClient):
        self.client_factory = client_factory

    def rerank(self, *, query, evidence, timeout_seconds=None):
        check_cancelled()
        if settings.RAG_RERANK_PROVIDER == "disabled":
            return evidence, "disabled"
        if not evidence:
            return [], "no_candidates"
        if not settings.RAG_RERANK_MODEL or len(evidence) > 20:
            raise RerankError("专用重排模型未配置或候选超过 20 条预算")
        endpoint = validate_endpoint(settings.RAG_RERANK_URL)
        duration = min(settings.RAG_RERANK_TIMEOUT_SECONDS, timeout_seconds) if timeout_seconds is not None else settings.RAG_RERANK_TIMEOUT_SECONDS
        if duration <= 0:
            raise RerankError("重排调用预算已耗尽")
        token = settings.RAG_RERANK_TOKEN.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = {"model": settings.RAG_RERANK_MODEL, "query": query,
                   "documents": [item["content"] for item in evidence], "top_n": len(evidence), "max_tokens_per_doc": 4096}
        payload = run_async(lambda: self._request(endpoint, request, headers, duration))
        try:
            results = [RankedItem.model_validate(row) for row in payload["results"]]
            if len(results) != len(evidence) or {row.index for row in results} != set(range(len(evidence))):
                raise ValueError("invalid candidate mapping")
        except RerankError:
            raise
        except (ValueError, TypeError, KeyError, ValidationError, httpx.HTTPError):
            raise RerankError("重排连接或候选映射校验失败，未采用该排序") from None
        ranked = []
        for row in sorted(results, key=lambda row: (-row.relevance_score, row.index)):
            item = dict(evidence[row.index])
            metadata = dict(item.get("metadata") or {})
            metadata["rerank"] = {"provider": settings.RAG_RERANK_PROVIDER, "model": settings.RAG_RERANK_MODEL,
                                  "model_revision": settings.RAG_RERANK_REVISION or "unverified", "score_type": "relevance_score",
                                  "score": row.relevance_score, "input_chars": len(item["content"]),
                                  "max_tokens_per_doc": 4096, "truncation_status": "not_verified"}
            item.update(metadata=metadata, similarity=None)
            ranked.append(item)
        return ranked, "ok"

    async def _request(self, endpoint, request, headers, duration):
        try:
            async with asyncio.timeout(duration):
                async with self.client_factory(timeout=httpx.Timeout(duration, connect=min(10, duration)), follow_redirects=False) as client:
                    async with client.stream("POST", endpoint, headers=headers, json=request) as response:
                        if not response.is_success:
                            raise RerankError(f"专用重排服务暂不可用（HTTP {response.status_code}）")
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > 1_048_576:
                                raise RerankError("重排响应超过大小预算")
                        return json.loads(body)
        except TimeoutError:
            raise RerankError("专用重排达到时间预算") from None
        except (ValueError, httpx.HTTPError):
            raise RerankError("重排连接或候选映射校验失败，未采用该排序") from None
