"""Start an isolated local API and verify its public contracts without model fees.

Run from code/rag-service with its virtualenv Python. Does not initialize the
shared PostgreSQL engine, enable external sources, or restart another service.
"""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = secrets.token_urlsafe(24)
    env = dict(os.environ, RAG_ENGINE="ragflow", RAGFLOW_BASE_URL="", RAGFLOW_API_KEY="", SERVICE_TOKEN=token,
               PKULAW_MCP_ENABLED="false", RAG_RERANK_PROVIDER="disabled", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=Path(__file__).resolve().parent.parent, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 50
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Isolated API startup exited; inspect imports/configuration separately")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("Isolated API startup exceeded 50 seconds")
            assert client.get("/docs").status_code == 200
            schema = client.get("/openapi.json").json()
            assert "/api/v1/retrievals" in schema["paths"]
            assert "sources" in schema["components"]["schemas"]["AnswerRequest"]["properties"]
            assert "source_status" in schema["components"]["schemas"]["RetrievalResponse"]["properties"]
            assert "rerank_status" in schema["components"]["schemas"]["RetrievalResponse"]["properties"]
            assert "context_coverage" in schema["components"]["schemas"]["RetrievalResponse"]["properties"]
            assert "answer_verification" in schema["components"]["schemas"]["AnswerResponse"]["properties"]
            assert "legal_context" in schema["components"]["schemas"]["AnswerRequest"]["properties"]
            assert "legal_applicability" in schema["components"]["schemas"]["RetrievalResponse"]["properties"]
            assert client.post("/api/v1/retrievals", json={"query": "synthetic"}).status_code == 401
            response = client.get("/api/v1/capabilities", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.json()["external_law_mcp"] is False
            assert response.json()["dedicated_reranking"] is False
            invalid = client.post("/api/v1/retrievals", headers={"Authorization": f"Bearer {token}"},
                json={"query": "synthetic", "purpose": "case_assessment", "legal_context": {
                    "business_date": "2024-02-31", "jurisdiction": "CN", "subject_type": "synthetic", "business_type": "synthetic"}})
            assert invalid.status_code == 422
        print("PASS: isolated startup, health/docs/OpenAPI, source/rerank contracts and authentication; no shared DB or model calls")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
