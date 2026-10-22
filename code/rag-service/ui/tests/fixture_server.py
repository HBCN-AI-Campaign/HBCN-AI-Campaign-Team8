"""Synthetic dependencies for browser contract tests, never production deployment.

Uses the real FastAPI routes, cookie auth, LangGraph, SSE and static UI. No DB,
embedding, SDK model or MCP calls. Run only as the smoke-ui.cjs child process.
"""
import json
import os
import secrets
import socket
import sys
import time
import asyncio
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.update(RAG_ENGINE="ragflow", RAGFLOW_BASE_URL="", RAGFLOW_API_KEY="", SERVICE_TOKEN=secrets.token_urlsafe(32),
                  PKULAW_MCP_ENABLED="false", RAG_RERANK_PROVIDER="disabled", RAG_LEGAL_REVIEW_FILE="")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import uvicorn
from pydantic import SecretStr
from app import main, backend_api, answer_graph
from app.request_control import run_async
from app.document_quality import assess_pages
from app.document_store import DocumentConflict

review_folder = tempfile.TemporaryDirectory()
review_key = secrets.token_urlsafe(48)
registry = Path(review_folder.name) / 'principals.json'
registry.write_text(json.dumps({'principals': [{'subject': 'synthetic-browser-operator', 'key_sha256': hashlib.sha256(review_key.encode()).hexdigest(),
    'namespaces': ['business_rules'], 'roles': ['reviewer'], 'valid_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}]}))
main.settings.RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE = str(registry)
main.settings.RAG_UI_DOCUMENT_REVIEW_KEY = SecretStr(review_key)
original = Path(review_folder.name) / 'synthetic-original.txt'
original.write_text('金额 5000 USD 不得更改。\n请核对日期。', encoding='utf-8')
PAGES = [{'page': 1, 'text': '金额 5000 USD 不得更改。', 'extraction': {'method': 'vision_ocr'}},
         {'page': 2, 'text': '请核对日期。', 'extraction': {'method': 'vision_ocr'}}]

cancel_state = {"started": 0, "closed": 0, "active": 0}


@main.app.get("/api/v1/fixture-cancellation")
def cancellation_state():
    # Exists only in this synthetic child process, never in production routes.
    available = backend_api.answer_slots.acquire(blocking=False)
    if available:
        backend_api.answer_slots.release()
    return {**cancel_state, "capacity_available": available}

IDS = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
TEXT = "合成规则：金额不一致须暂停处理并核对更正。"
rows = {identifier: {"id": identifier, "name": f"合成资料{index + 1}.txt", "scope": "business_rules", "state": "ready", "stage": "done", "chunk_count": 1, "sha256": hashlib.sha256(TEXT.encode()).hexdigest()}
        for index, identifier in enumerate(IDS)}


class FixtureRuntime:
    def complete(self, *, message, instructions, **kwargs):
        if "取消测试" in message:
            async def pending():
                cancel_state["started"] += 1
                cancel_state["active"] += 1
                try:
                    await asyncio.sleep(30)
                finally:
                    cancel_state["active"] -= 1
                    cancel_state["closed"] += 1
            run_async(pending)
        if "故障测试" in message:
            raise RuntimeError("synthetic upstream failure")
        if "你是回答依据复核员" in instructions:
            value = {"checks": [{"segment": 1, "verdict": "supported", "supports": [{"citation": 1, "quote": "金额不一致须暂停处理并核对更正"}], "reason": "synthetic contract fixture"}]}
        elif '"statements"' in instructions:
            value = {"statements": [{"text": "金额不一致须暂停处理并核对更正。", "supports": [{"citation": 1, "quote": "金额不一致须暂停处理并核对更正"}]}]}
        elif "检查检索原文" in instructions:
            value = {"relevant": True, "sufficient": True, "selected": [1], "missing": [], "rewrite": ""}
        else:
            value = {"intent": "rule", "queries": []}
        return json.dumps(value, ensure_ascii=False)


class FixtureEngine:
    def __init__(self):
        self.documents = SimpleNamespace(recover_interrupted=lambda: None, list=lambda: list(rows.values()), get=self.get,
                                         public=lambda row: row, original_path=lambda identifier: original)

    def get(self, identifier):
        row = rows.get(identifier)
        if row and row["state"] == "queued":
            pending = row.get('quality') and row['quality'].get('review_status') != 'approved'
            row.update(state="quality_review" if pending else "ready",
                       stage="quality_review" if pending else "done", chunk_count=0 if pending else 1)
        return row

    def review_quality(self, identifier, payload, actor):
        row = rows[identifier]
        actor.require(row['scope'], 'reviewer')
        report = row['quality']
        if row['state'] != 'quality_review' or payload.expected_sha256 != row['sha256'] or payload.expected_parsed_sha256 != report['parsed_sha256'] or payload.expected_report_sha256 != report['report_sha256']:
            raise DocumentConflict('synthetic stale version')
        if payload.decision == 'approve':
            if payload.verified_units != [0, 1] or payload.reason != 'source_compared':
                raise DocumentConflict('synthetic incomplete comparison')
            row.update(state='queued', stage='quality_approved', quality={**report, 'review_status': 'approved'})
        else:
            row.update(state='failed', stage='quality_rejected')
        return row

    def recheck_quality(self, identifier, expected_sha256, actor):
        row = rows[identifier]
        actor.require(row['scope'], 'reviewer')
        if expected_sha256 != row['sha256'] or row['state'] == 'withdrawn':
            raise DocumentConflict('synthetic stale version')
        row.update(state='queued', stage='quality_recheck', quality=assess_pages(PAGES))
        return row

    def retrieve(self, *, query, **kwargs):
        identifier = IDS[1] if "第二" in query else IDS[0]
        if rows[identifier]["state"] == "withdrawn":
            return []
        return [{"document_id": identifier, "chunk_id": identifier, "document_keyword": rows[identifier]["name"], "content": TEXT,
                 "metadata": {"scope": "business_rules"}, "reader_url": f"/api/v1/documents/{identifier}/content?chunk_id={identifier}"}]

    def content(self, identifier, chunk_id=None):
        if rows[identifier]["state"] == "withdrawn":
            return None
        return {"document": rows[identifier], "pages": [{"page": None, "text": TEXT}], "focus": None}

    def withdraw(self, identifier, *, expected_sha256, reason):
        from app.document_store import DocumentConflict
        if expected_sha256 != rows[identifier]["sha256"]:
            raise DocumentConflict("synthetic version mismatch")
        rows[identifier].update(state="withdrawn", stage="withdrawn", source_available=False)
        return rows[identifier]

    def submit(self, *, filename, scope, **kwargs):
        identifier = "33333333-3333-3333-3333-333333333333"
        rows[identifier] = {"id": identifier, "name": filename, "scope": scope, "state": "queued", "stage": "queued", "chunk_count": 0, "sha256": hashlib.sha256(b"synthetic").hexdigest()}
        if filename.startswith("quality-"):
            rows[identifier].update(quality=assess_pages(PAGES), pages=PAGES, source_available=True)
        return rows[identifier], True


engine = FixtureEngine()
main.engine_kind = lambda: "postgres"
main.get_engine = lambda: engine
backend_api.postgres_engine = lambda: engine
answer_graph.SDKRuntime = FixtureRuntime
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(128)
print(json.dumps({"port": listener.getsockname()[1], "fixture": "synthetic-no-external-calls"}), flush=True)
uvicorn.Server(uvicorn.Config(main.app, log_level="critical", access_log=False)).run(sockets=[listener])
