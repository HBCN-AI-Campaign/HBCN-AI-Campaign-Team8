"""Standalone HTTP consumer: no imports from RAG internals or business backend."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--scope", choices=["all", "business_rules", "project_design", "law"], default="business_rules")
    parser.add_argument("--mode", choices=["query", "retrievals"], default="retrievals")
    parser.add_argument("--web-context-file", help="authorized capture JSON array; actual text/time required, no URL fetching")
    args = parser.parse_args()
    base_url, token = os.environ.get("RAG_BASE_URL", ""), os.environ.get("RAG_SERVICE_TOKEN", "")
    if not base_url or not token:
        parser.error("set RAG_BASE_URL and RAG_SERVICE_TOKEN in the calling backend environment")
    payload = {"query": args.query, "scope": args.scope, "top_k": 5}
    headers = {"Authorization": f"Bearer {token}"}
    if args.web_context_file:
        if args.mode != "retrievals" or not os.environ.get("RAG_WEB_CONTEXT_KEY"):
            parser.error("web context needs retrievals mode and RAG_WEB_CONTEXT_KEY in the backend environment")
        try:
            path = Path(args.web_context_file)
            if path.stat().st_size > 180000:
                raise ValueError
            snapshots = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 4:
                raise ValueError
        except (OSError, ValueError):
            parser.error("web snapshot file must be a bounded UTF-8 JSON array; no file content printed")
        payload.update(sources=["knowledge_base", "web_context"], web_context=snapshots)
        headers["X-Web-Context-Key"] = os.environ["RAG_WEB_CONTEXT_KEY"]
    # Enhanced retrieval can use the whole graph budget. Do not silently retry a
    # timed-out request: the remote provider may have accepted and billed it.
    with httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=httpx.Timeout(300, connect=10), follow_redirects=False) as client:
        try:
            response = client.post(f"api/v1/{args.mode}", json=payload, headers=headers)
        except httpx.HTTPError:
            raise SystemExit("RAG transport failed; inspect configuration privately, no automatic replay") from None
        if response.status_code != 200:
            raise SystemExit(f"RAG request failed with HTTP {response.status_code}; inspect the service privately")
        contract = response.headers.get("x-rag-contract-version", "")
        if contract.split(".")[0] != "1":
            raise SystemExit("RAG v1 contract not confirmed; check the deployed version")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
