"""Request-local, credentialed web snapshots. No fetching or implicit authority.

The capture service attests provenance; this module cannot prove a page really
contained supplied text. Keys live in the adapter closure, never graph state.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .document_quality import assess_pages
from .reference_security import ReferenceForbidden, resolve_principal


NOTICE = "网页快照为获授权调用方提交的未核实上下文；不代表本服务已抓取全文、核实网页真实性或确认法规效力。"


class WebContextError(ValueError):
    pass


def checked_url(value):
    if any(ord(char) < 33 or char == "\\" for char in value):
        raise ValueError("web URL contains unsafe characters")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
        or parsed.port not in (None, 443) or parsed.query or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
        or "." not in host or host.endswith(".") or host.lower().endswith((".local", ".internal"))):
        raise ValueError("use an approved public HTTPS URL without credentials or query parameters")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return value
    raise ValueError("web URL must use an approved DNS hostname")


class WebSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=40000)
    captured_at: str = Field(max_length=50)
    scope: str = Field(pattern=r"^(business_rules|project_design|law)$")
    completeness: str = Field(pattern=r"^(selection|page_text)$")
    processing_authorized: Literal[True]
    language: str | None = Field(default=None, pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})?$")

    _url = field_validator("url")(checked_url)

    @field_validator("processing_authorized", mode="before")
    @classmethod
    def explicit_processing_consent(cls, value):
        if value is not True:
            raise ValueError("processing_authorized must be explicit boolean true")
        return value

    @field_validator("captured_at")
    @classmethod
    def timestamp(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("capture timestamp requires a timezone")
        return parsed.astimezone(timezone.utc).isoformat()

    @field_validator("text", "title")
    @classmethod
    def usable_text(cls, value):
        report = assess_pages([{"page": None, "text": value, "extraction": {"method": "caller_supplied_text"}}])
        if report["status"] != "mechanically_checked":
            raise ValueError("snapshot text is empty, lossy or contains invalid characters")
        return value


class WebContextSource:
    def __init__(self, snapshots, *, scope, key):
        if not settings.RAG_WEB_CONTEXT_ENABLED:
            raise HTTPException(404, "网页上下文接口未启用")
        if not settings.RAG_WEB_CONTEXT_PRINCIPALS_FILE or not settings.RAG_WEB_CONTEXT_ALLOWED_HOSTS.strip():
            raise HTTPException(503, "网页上下文授权配置未就绪")
        self._snapshots = tuple(snapshots)
        self._key = key
        self._scope = scope
        self._check_permission()
        self._items = {}
        for snapshot in self._snapshots:
            content_hash = hashlib.sha256(snapshot.text.encode()).hexdigest()
            identity = hashlib.sha256((snapshot.url + "\n" + snapshot.captured_at + "\n" + content_hash).encode()).hexdigest()
            item = {"content": snapshot.text, "document_id": "web:" + identity,
                "document_keyword": snapshot.title, "chunk_id": "web:" + identity, "page_num": None,
                "similarity": None, "source_url": snapshot.url, "reader_url": None,
                "metadata": {"source_type": "web_context", "scope": snapshot.scope,
                    "content_sha256": content_hash, "version": identity, "language": snapshot.language,
                    "captured_at": snapshot.captured_at, "received_at": datetime.now(timezone.utc).isoformat(),
                    "capture_completeness": snapshot.completeness, "verification": "caller_supplied_unverified",
                    "evidence_role": "unverified_web_context", "retrieval": {"score_type": "unranked_context"}}}
            self._items[item["chunk_id"]] = item

    def _check_permission(self):
        if not settings.RAG_WEB_CONTEXT_ENABLED:
            raise HTTPException(403, "网页上下文授权已关闭")
        actor = resolve_principal(self._key, settings.RAG_WEB_CONTEXT_PRINCIPALS_FILE)
        hosts = {host.strip().lower() for host in settings.RAG_WEB_CONTEXT_ALLOWED_HOSTS.split(",") if host.strip()}
        now = datetime.now(timezone.utc)
        for snapshot in self._snapshots:
            try:
                actor.require(snapshot.scope, "reader")
            except ReferenceForbidden:
                raise HTTPException(403, "无权使用此网页上下文范围") from None
            age = (now - datetime.fromisoformat(snapshot.captured_at)).total_seconds()
            if (self._scope not in ("all", snapshot.scope) or urlsplit(snapshot.url).hostname.lower() not in hosts):
                raise HTTPException(403, "网页来源或知识范围未获授权")
            if age < 0 or age > settings.RAG_WEB_CONTEXT_MAX_AGE_SECONDS:
                raise HTTPException(409, "网页快照采集时间不在当前允许窗口内，请重新采集")

    def current_evidence(self, items):
        try:
            self._check_permission()
        except HTTPException:
            raise WebContextError("网页上下文授权或快照有效期已变化，请重新核对") from None
        current = []
        for item in items:
            original = self._items.get(item.get("chunk_id"))
            if not original or any(item.get(key) != original[key] for key in
                ("document_id", "document_keyword", "source_url", "reader_url", "page_num")):
                continue
            metadata = item.get("metadata", {})
            if any(metadata.get(key) != value for key, value in original["metadata"].items()
                   if key not in {"retrieval", "content_sha256"}):
                continue
            excerpt = metadata.get("excerpt")
            if excerpt:
                start, end = excerpt.get("start_char"), excerpt.get("end_char")
                if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original["content"])
                    or excerpt.get("parent_chunk_id") != original["chunk_id"]
                    or excerpt.get("parent_content_sha256") != original["metadata"]["content_sha256"]
                    or item.get("content") != original["content"][start:end]):
                    continue
            elif item.get("content") != original["content"]:
                continue
            if metadata.get("content_sha256") != hashlib.sha256(item["content"].encode()).hexdigest():
                continue
            current.append(item)
        return current

    def candidates(self):
        # Return copies: fusion/reranking cannot mutate the binding originals.
        import copy
        return self.current_evidence(copy.deepcopy(list(self._items.values())))
