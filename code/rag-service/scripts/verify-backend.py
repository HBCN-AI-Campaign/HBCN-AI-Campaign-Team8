import argparse
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings


def main():
    parser = argparse.ArgumentParser(description="真实 API 验收，会调用百炼 Embedding 和 OpenCode SDK 并产生小额模型费用")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--persistence-only", action="store_true")
    args = parser.parse_args()
    results = {}

    def check(name, condition):
        results[name] = bool(condition)
        print(name, "PASS" if condition else "FAIL", flush=True)
        if not condition:
            raise AssertionError(name)

    headers = {"Authorization": f"Bearer {settings.SERVICE_TOKEN}"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=240) as client:
        deadline = time.monotonic() + 90
        while True:
            try:
                response = client.get("/health", timeout=3)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("服务启动超时，请检查后端日志")
            time.sleep(1)
        response = client.get("/health")
        check("liveness", response.status_code == 200)
        check("unauthorized_denied", httpx.get(args.base_url + "/api/v1/documents").status_code == 401)
        response = client.get("/api/v1/ready")
        check("postgres_vector_sdk_ready", response.status_code == 200 and response.json()["engine"] == "postgres")
        documents = client.get("/api/v1/documents").json()["documents"]
        ready = [item for item in documents if item["state"] == "ready"]
        check("real_business_and_law_documents", len([item for item in ready if item["scope"] == "business_rules"]) >= 4 and len([item for item in ready if item["scope"] == "law"]) >= 2)
        question = "固定资产投资类贷款的用途应如何填写，有哪些常见用途描述？"
        response = client.post("/api/v1/query", json={"query": question, "scope": "business_rules", "top_k": 5})
        check("persistent_pgvector_retrieval", response.status_code == 200 and len(response.json()["evidence"]) > 0)
        evidence = response.json()["evidence"]
        check("scope_isolation", all(item["metadata"]["metadata"]["scope"] == "business_rules" for item in evidence))
        first = evidence[0]
        focus_response = client.get(first["metadata"]["reader_url"])
        check("full_source_with_focused_chunk", focus_response.status_code == 200 and focus_response.json()["focus"]["text"] == first["content"] and len(focus_response.json()["pages"]) > 0)
        focus = focus_response.json()["focus"]
        check("focused_chunk_matches_original_text", any(
            page["page"] == focus.get("page") and page.get("section") == focus.get("section")
            and page["text"][focus["start_index"]:focus["start_index"] + len(focus["text"])] == focus["text"]
            for page in focus_response.json()["pages"]
        ))
        other = next(item for item in ready if item["id"] != first["document_id"])
        mismatch = client.get(f"/api/v1/documents/{other['id']}/content", params={"chunk_id": first["metadata"]["chunk_id"]})
        check("cross_document_chunk_denied", mismatch.status_code == 404)
        if not args.persistence_only:
            buffer = io.BytesIO()
            pdf = Canvas(buffer)
            pdf.drawString(50, 700, "HBCN RAG backend acceptance test. Not a business rule.")
            pdf.showPage()
            pdf.drawString(50, 700, "Second original page for source navigation verification.")
            pdf.save()
            original = buffer.getvalue()
            response = client.post("/api/v1/ingestions", data={"scope": "project_design"}, files={"file": ("backend-api-acceptance.pdf", original, "application/pdf")})
            check("async_upload_accepted", response.status_code == 202)
            document_id = response.json()["document"]["id"]
            deadline = time.monotonic() + 180
            while True:
                status = client.get(f"/api/v1/documents/{document_id}").json()
                if status["state"] in {"ready", "failed"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("文档处理超时")
                time.sleep(1)
            stages = [item["stage"] for item in status["events"]]
            check("real_ingestion_stages", status["state"] == "ready" and all(stage in stages for stage in ["received", "parsing", "splitting", "embedding", "indexing", "ready"]))
            source = client.get(f"/api/v1/documents/{document_id}/source")
            check("original_bytes_preserved", source.status_code == 200 and hashlib.sha256(source.content).digest() == hashlib.sha256(original).digest())
            pages = client.get(f"/api/v1/documents/{document_id}/content").json()["pages"]
            check("real_pdf_pages", [page["page"] for page in pages] == [1, 2])
            duplicate = client.post("/api/v1/ingestions", data={"scope": "project_design"}, files={"file": ("backend-api-acceptance.pdf", original)})
            check("deduplicated_upload", duplicate.status_code == 202 and duplicate.json()["created"] is False and duplicate.json()["document"]["id"] == document_id)
            invalid = client.post("/api/v1/ingestions", data={"scope": "project_design"}, files={"file": ("backend-invalid-acceptance.pdf", b"Invalid PDF test - not a business document")})
            invalid_id = invalid.json()["document"]["id"]
            deadline = time.monotonic() + 60
            while True:
                status = client.get(f"/api/v1/documents/{invalid_id}").json()
                if status["state"] in {"ready", "failed"} or time.monotonic() > deadline:
                    break
                time.sleep(1)
            check("invalid_pdf_fails_honestly", status["state"] == "failed" and status["chunk_count"] == 0 and bool(status["error"]))
            retry = client.post(f"/api/v1/documents/{invalid_id}/retry")
            check("failed_document_retry_accepted", retry.status_code == 202)
            deadline = time.monotonic() + 60
            while True:
                status = client.get(f"/api/v1/documents/{invalid_id}").json()
                if status["state"] == "failed" or time.monotonic() > deadline:
                    break
                time.sleep(1)
            check("retry_does_not_fake_success", status["state"] == "failed")
            start = time.monotonic()
            response = client.post("/api/v1/answers", json={"query": question, "scope": "business_rules"})
            check("sdk_grounded_answer", response.status_code == 200 and response.json().get("grounding") == "cited" and len(response.json().get("sources", [])) > 0)
            results["answer_seconds"] = round(time.monotonic() - start, 2)
            results["answer_source_count"] = len(response.json()["sources"])
            stream_events = []
            with client.stream("POST", "/api/v1/answers/stream", json={"query": "贷款用途描述中可以出现哪些营运资金用途？", "scope": "business_rules"}) as stream:
                check("sse_http", stream.status_code == 200)
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        stream_events.append(line[6:].strip())
            check("sse_real_steps_and_result", stream_events.count("step") >= 6 and "result" in stream_events and "error" not in stream_events)
            response = client.post("/api/v1/answers", json={"query": "火星居民今天买彩票的中奖号码是多少？", "scope": "business_rules"})
            check("irrelevant_question_abstains", response.status_code == 200 and response.json().get("grounding") == "insufficient" and not response.json().get("sources"))
        results["verified_at"] = datetime.now(timezone.utc).isoformat()
        report = ROOT / "data" / ("persistence-acceptance.json" if args.persistence_only else "backend-acceptance.json")
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("验收完成；报告不含凭证或业务原文", flush=True)


if __name__ == "__main__":
    main()
