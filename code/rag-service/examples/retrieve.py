"""Standalone HTTP consumer: no imports from RAG internals or business backend."""
import argparse
import json
import os

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--scope", choices=["all", "business_rules", "project_design", "law"], default="business_rules")
    parser.add_argument("--mode", choices=["query", "retrievals"], default="retrievals")
    args = parser.parse_args()
    base_url, token = os.environ.get("RAG_BASE_URL", ""), os.environ.get("RAG_SERVICE_TOKEN", "")
    if not base_url or not token:
        parser.error("set RAG_BASE_URL and RAG_SERVICE_TOKEN in the calling backend environment")
    # Enhanced retrieval can use the whole graph budget. Do not silently retry a
    # timed-out request: the remote provider may have accepted and billed it.
    with httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=httpx.Timeout(300, connect=10), follow_redirects=False) as client:
        response = client.post(f"api/v1/{args.mode}", json={"query": args.query, "scope": args.scope, "top_k": 5},
                               headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            raise SystemExit(f"RAG request failed with HTTP {response.status_code}; inspect the service privately")
        contract = response.headers.get("x-rag-contract-version", "")
        if contract.split(".")[0] != "1":
            raise SystemExit("RAG v1 contract not confirmed; check the deployed version")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
