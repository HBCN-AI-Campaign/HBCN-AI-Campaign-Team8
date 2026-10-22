"""Read-only Pkulaw adapter using the official MCP SDK and reviewed schemas.

The service never imports desktop MCP credentials. Callers must explicitly
request this source; no source text, conversation, or uploaded file is forwarded.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from .config import settings
from .request_control import run_async

ENDPOINT = "https://apim-gateway.pkulaw.com/mcp-law-search-service"
CONTRACT = json.loads((Path(__file__).parent / "contracts/pkulaw-law-search.json").read_text(encoding="utf-8"))


class PkulawError(RuntimeError):
    pass


def schema_shape(value):
    if not isinstance(value, dict):
        return value
    return {key: ({name: schema_shape(part) for name, part in part_value.items()} if key in {"properties", "$defs"}
                  else [schema_shape(part) for part in part_value] if isinstance(part_value, list)
                  else schema_shape(part_value))
            for key, part_value in value.items() if key not in {"description", "title", "examples"}}


def verify_tools(tools):
    names = [tool.name for tool in tools]
    if any(names.count(name) != 1 for name in CONTRACT["tools"]):
        raise PkulawError("北大法宝只读工具缺失或重名，需复核后启用")
    known = {tool.name: tool for tool in tools}
    for name, contract in CONTRACT["tools"].items():
        tool = known.get(name)
        if tool is None or schema_shape(tool.input_schema) != contract["inputSchema"] or schema_shape(tool.output_schema) != contract["outputSchema"]:
            raise PkulawError("北大法宝工具契约已变化，需复核后启用")
    return hashlib.sha256(json.dumps(CONTRACT["tools"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def discover_contract(client):
    tools, seen, cursor = [], set(), None
    for _ in range(3):
        result = await client.list_tools(cursor=cursor) if cursor else await client.list_tools()
        tools.extend(result.tools)
        if len(tools) > 100:
            raise PkulawError("北大法宝工具目录超过已复核预算")
        cursor = getattr(result, "next_cursor", None)
        if cursor is None:
            return verify_tools(tools)
        if cursor in seen:
            raise PkulawError("北大法宝工具目录分页游标重复")
        seen.add(cursor)
    raise PkulawError("北大法宝工具目录超过分页预算")


def tool_payload(result, name):
    if result.is_error:
        raise PkulawError("北大法宝查询工具返回错误")
    payload = result.structured_content
    if payload is None:
        texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        if len(texts) != 1:
            raise PkulawError("北大法宝返回格式不匹配")
        try:
            payload = json.loads(texts[0])
        except (TypeError, ValueError):
            raise PkulawError("北大法宝返回格式不匹配") from None
    if not Draft202012Validator(CONTRACT["tools"][name]["outputSchema"]).is_valid(payload):
        raise PkulawError("北大法宝返回字段与已复核契约不符")
    return payload


def source_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme == "https" and (host == "pkulaw.com" or host.endswith(".pkulaw.com")) and not parsed.username and not parsed.password and parsed.port in {None, 443}:
            return value
    except ValueError:
        pass
    return None


class PkulawSource:
    @property
    def configured(self):
        return settings.PKULAW_MCP_ENABLED and bool(settings.PKULAW_MCP_TOKEN.get_secret_value())

    async def retrieve_async(self, *, query, top_k=3, timeout_seconds=None):
        if not self.configured:
            raise PkulawError("北大法宝检索尚未启用或未配置服务端凭证")
        if settings.PKULAW_MCP_LAW_SEARCH_URL != ENDPOINT:
            raise PkulawError("北大法宝服务地址不在已复核白名单")
        if not query.strip() or len(query) > 4000:
            raise PkulawError("北大法宝查询长度无效")
        duration = min(settings.PKULAW_MCP_TIMEOUT_SECONDS, timeout_seconds) if timeout_seconds is not None else settings.PKULAW_MCP_TIMEOUT_SECONDS
        if duration <= 0:
            raise PkulawError("北大法宝调用预算已耗尽")
        warnings, items = [], []
        try:
            async with asyncio.timeout(duration):
                async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {settings.PKULAW_MCP_TOKEN.get_secret_value()}"},
                                             timeout=httpx2.Timeout(duration, connect=min(duration, 10)), follow_redirects=False) as http:
                    async with Client(streamable_http_client(ENDPOINT, http_client=http)) as client:
                        schema_hash = await discover_contract(client)
                        arguments = {"text": query, "size": min(3, max(1, top_k))}
                        Draft202012Validator(CONTRACT["tools"]["search_article"]["inputSchema"]).validate(arguments)
                        payload = tool_payload(await client.call_tool("search_article", arguments), "search_article")
                        # Never invent an article number to fetch an entire law.
                        article_number = re.search(r"第[一二三四五六七八九十百千万零〇两0-9]+条", query)
                        fetches = 0
                        for record in payload["result"][:3]:
                            if not record["article"].strip() and article_number and fetches < 2:
                                fetches += 1
                                fetched = tool_payload(await client.call_tool("get_article", {"title": record["title"], "number": article_number.group()}), "get_article")
                                # An unrelated title/version is not a valid body replacement.
                                version_conflict = any(fetched[key] and record[key] and fetched[key] != record[key]
                                                       for key in ("doc_no", "issue_date", "implementation_date", "timeliness"))
                                if fetched["gid"] == record["gid"] and fetched["title"] == record["title"] and not version_conflict:
                                    record = fetched
                                else:
                                    warnings.append("补取条文的法规标识或版本与搜索命中不符，未合并该正文")
                            if not record["article"].strip():
                                warnings.append("北大法宝命中仅有元数据，正文未取得；未将标题当作法规要求")
                                continue
                            if not record["gid"].strip() or not record["title"].strip() or len(record["article"]) > 100_000:
                                warnings.append("北大法宝片段标识缺失或正文超出处理上限，未纳入依据")
                                continue
                            url = source_url(record["url"])
                            if url is None:
                                warnings.append("北大法宝返回的来源链接未通过白名单检查")
                            digest = hashlib.sha256(record["article"].encode()).hexdigest()
                            metadata = {key: value for key, value in record.items() if key not in {"article", "url"}}
                            version_facts = {key: record[key] for key in ("doc_no", "issue_date", "implementation_date", "timeliness", "effectiveness")}
                            metadata_version = hashlib.sha256(json.dumps(version_facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                            metadata.update(source_type="pkulaw", scope="law", fetched_at=datetime.now(timezone.utc).isoformat(),
                                            schema_sha256=schema_hash, content_sha256=digest,
                                            version="provider-metadata:" + metadata_version, version_basis="unverified_provider_metadata",
                                            applicability="unverified", completeness="article_excerpt",
                                            jurisdiction="unknown", url_verified=url is not None)
                            items.append({"document_id": "pkulaw:" + record["gid"], "chunk_id": "article:" + digest[:24],
                                          "document_keyword": record["title"], "content": record["article"],
                                          "similarity": None, "page_num": None, "source_url": url, "reader_url": url,
                                          "metadata": metadata})
        except PkulawError:
            raise
        except Exception:
            # Provider errors and SDK exception groups may contain payloads/headers.
            raise PkulawError("北大法宝连接、鉴权、限流或响应处理未完成，本次外部检索不可用") from None
        return {"items": items, "warnings": list(dict.fromkeys(warnings)),
                "status": "partial" if warnings else "ok"}

    def retrieve(self, **kwargs):
        # FastAPI sync endpoints and the sync graph run in worker threads.
        return run_async(lambda: self.retrieve_async(**kwargs))
