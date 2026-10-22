"""Live HTTP acceptance of a deployed RAG module, using an explicit test fixture.

Requires a running PostgreSQL RAG service, real embedding/runtime credentials,
and permission to create then withdraw a synthetic project_design document.
Model calls incur fees. Reports contain checks and identifiers, not credentials
or source contents. Existing business documents are never changed.
"""
import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--write-fixture", action="store_true", help="Allow creating/withdrawing an explicitly synthetic test document")
    parser.add_argument("--report", default="data/module-acceptance.json")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if not args.write_fixture:
        parser.error("Pass --write-fixture to authorize the synthetic document lifecycle and real model calls")
    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root / ".env")
    token = os.environ.get("RAG_SERVICE_TOKEN") or os.environ.get("SERVICE_TOKEN") or values.get("SERVICE_TOKEN")
    if not token:
        parser.error("Set RAG_SERVICE_TOKEN or SERVICE_TOKEN on the server; never pass a token on the command line")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": {}, "passed": False}
    doc = None
    started = time.monotonic()

    def check(name, passed):
        report["checks"][name] = bool(passed)
        print(name + (" PASS" if passed else " FAIL"), flush=True)
        if not passed:
            raise AssertionError(name)

    marker = "RAG-CHECK-" + uuid.uuid4().hex[:12]
    content = (f"# Synthetic integration fixture {marker}\n"
        "This document is test data, not a real bank rule or an approval instruction.\n"
        "For this synthetic payment instruction, if the amount is incorrect, compare the amount and currency "
        "against the source document and request a corrected payment instruction. "
        "A USD 5000 amount must not be automatically changed to another amount or currency.\n").encode()
    digest = hashlib.sha256(content).hexdigest()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=args.timeout, follow_redirects=False) as client:
        try:
            health = client.get("/health")
            check("health", health.status_code == 200)
            report["service"] = {key: health.json().get(key) for key in ("service_version", "api_contract_version")}
            check("unauthorized_denied", httpx.get(args.base_url.rstrip("/") + "/api/v1/documents", timeout=10).status_code == 401)
            ready = client.get("/api/v1/ready")
            report["readiness"] = ready.json()
            check("database_and_runtime_ready", ready.status_code == 200 and ready.json().get("status") == "ready")
            check("openapi", "/api/v1/retrievals" in client.get("/openapi.json").json().get("paths", {}))
            upload = client.post("/api/v1/ingestions", data={"scope": "project_design"},
                files={"file": (marker + ".md", content, "text/markdown")})
            check("upload_accepted", upload.status_code == 202)
            doc = upload.json()["document"]
            report["fixture_document_id"] = doc["id"]
            deadline = time.monotonic() + args.timeout
            while True:
                state = client.get("/api/v1/documents/" + doc["id"]).json()
                if state["state"] in {"ready", "failed", "quality_review", "quarantined", "withdrawn"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("fixture ingestion")
                time.sleep(1)
            report["fixture_state"] = state["state"]
            check("parsed_embedded_indexed", state["state"] == "ready" and state.get("chunk_count", 0) > 0)
            original = client.get(f"/api/v1/documents/{doc['id']}/source")
            check("original_bytes_preserved", original.status_code == 200 and hashlib.sha256(original.content).hexdigest() == digest)
            query = f"In synthetic fixture {marker}, what should be done when the payment instruction amount is incorrect?"
            request = {"query": query, "scope": "project_design", "top_k": 5}
            legacy = client.post("/api/v1/query", json=request)
            check("legacy_evidence_endpoint", legacy.status_code == 200 and any(e.get("document_id") == doc["id"] for e in legacy.json().get("evidence", [])))
            enhanced = client.post("/api/v1/retrievals", json={**request, "sources": ["knowledge_base"]})
            check("enhanced_retrieval_http", enhanced.status_code == 200)
            retrieval = enhanced.json()
            report["retrieval"] = {key: retrieval.get(key) for key in ("evidence_status", "stop_reason", "retrieval_rounds", "source_status", "rerank_status")}
            check("enhanced_original_evidence", any(e.get("document_id") == doc["id"] for e in retrieval.get("sources", [])))
            check("retrieval_does_not_generate_answer", "answer" not in retrieval)
            source = next(e for e in retrieval["sources"] if e.get("document_id") == doc["id"])
            reader = client.get(source["reader_url"])
            check("source_location", reader.status_code == 200 and source["content"] in reader.json().get("focus", {}).get("text", ""))
            answer = client.post("/api/v1/answers", json=request)
            check("answer_http", answer.status_code == 200)
            result = answer.json()
            report["answer"] = {"grounding": result.get("grounding"), "verification_status": result.get("answer_verification", {}).get("status")}
            check("answer_has_verified_citations", result.get("grounding") == "cited" and bool(result.get("answer"))
                and result.get("answer_verification", {}).get("status") == "supported_by_model"
                and any(e.get("document_id") == doc["id"] for e in result.get("sources", [])))
            check("scope_boundary", client.post("/api/v1/retrievals", json={"query": query, "scope": "task_documents"}).status_code == 422)
            report["passed"] = True
        except Exception as exc:
            report["failure"] = {"type": type(exc).__name__, "check": str(exc) if isinstance(exc, AssertionError) else "see last completed check"}
        finally:
            if doc:
                try:
                    withdrawn = client.post(f"/api/v1/documents/{doc['id']}/withdraw", json={"expected_sha256": digest, "reason": "other"})
                    removed = withdrawn.status_code == 200 and client.get(f"/api/v1/documents/{doc['id']}/source").status_code == 404
                    report["checks"]["fixture_withdrawn_and_source_blocked"] = removed
                    report["passed"] = report["passed"] and removed
                except httpx.HTTPError:
                    report["checks"]["fixture_withdrawn_and_source_blocked"] = False
                    report["passed"] = False
            report["duration_seconds"] = round(time.monotonic() - started, 2)
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS" if report["passed"] else "FAIL", str(Path(args.report).resolve()), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
