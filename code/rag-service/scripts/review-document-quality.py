"""Explicit quality review HTTP client; credentials never enter the browser.

Set RAG_BASE_URL/RAG_SERVICE_TOKEN/RAG_DOCUMENT_REVIEW_KEY on a trusted reviewer
machine. GET is the default. A decision needs explicit snapshot hashes and an
explicit list of units actually compared against the source; no automatic yes.
"""
import argparse
import json
import os
import sys
from uuid import UUID

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_id", type=UUID)
    parser.add_argument("--decision", choices=["approve", "reject"])
    parser.add_argument("--recheck", action="store_true", help="explicitly reparse a legacy/failed/pending source; hides old chunks")
    parser.add_argument("--source-sha256")
    parser.add_argument("--parsed-sha256")
    parser.add_argument("--report-sha256")
    parser.add_argument("--verified-unit", type=int, action="append", default=[])
    parser.add_argument("--reason", choices=["source_compared", "incomplete", "incorrect", "unreadable"])
    args = parser.parse_args()
    if args.recheck and args.decision:
        parser.error("choose recheck or a review decision")
    names = ["RAG_BASE_URL", "RAG_SERVICE_TOKEN", "RAG_DOCUMENT_REVIEW_KEY"]
    if not all(os.environ.get(name) for name in names):
        parser.error("configure RAG_BASE_URL/RAG_SERVICE_TOKEN/RAG_DOCUMENT_REVIEW_KEY")
    headers = {"Authorization": "Bearer " + os.environ["RAG_SERVICE_TOKEN"],
               "X-Document-Review-Key": os.environ["RAG_DOCUMENT_REVIEW_KEY"]}
    path = f"/api/v1/documents/{args.document_id}"
    try:
        with httpx.Client(base_url=os.environ["RAG_BASE_URL"].rstrip("/"), headers=headers,
                          timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
            if args.recheck:
                if not args.source_sha256:
                    parser.error("recheck requires the source hash from the inspected snapshot")
                response = client.post(path + "/quality-recheck", json={"expected_sha256": args.source_sha256})
            elif args.decision:
                if not all([args.source_sha256, args.parsed_sha256, args.report_sha256, args.reason]):
                    parser.error("a decision needs source/parsed/report hashes and reason from the reviewed snapshot")
                response = client.post(path + "/quality-review", json={"decision": args.decision,
                    "expected_sha256": args.source_sha256, "expected_parsed_sha256": args.parsed_sha256,
                    "expected_report_sha256": args.report_sha256, "reason": args.reason, "verified_units": args.verified_unit})
            else:
                response = client.get(path + "/quality")
            if not response.is_success:
                raise RuntimeError(f"Quality API returned HTTP {response.status_code}; no decision replayed")
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        # Do not print upstream responses, request URLs or credential values.
        print(str(exc) if isinstance(exc, RuntimeError) else "Quality API request failed; inspect configuration", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
