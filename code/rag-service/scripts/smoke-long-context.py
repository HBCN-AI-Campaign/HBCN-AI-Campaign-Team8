"""Explicit opt-in synthetic long-text smoke with the actual configured SDK.

No database/MCP call. This invokes the actual planning/assessment model and may
incur fees. Only a body-free summary is saved to the ignored data directory.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.answer_graph import build_answer_graph
from app.config import settings
from app.evidence_context import utf16_units
from app.runtime_client import SDKRuntime


TEXT = ("这是合成测试材料，不是真实政策。\n" + "无关背景：介绍文件格式与目录，不包含业务处理要求。\n" * 550
        + "\n合成测试规则：支付指令金额与支持单据不一致时，应暂停处理，核对原始单据，并更正后重新提交。不得仅因历史已通过而直接放行。")


class SyntheticEngine:
    def retrieve(self, **kwargs):
        return [{"content": TEXT, "document_id": "synthetic-long", "chunk_id": "synthetic-parent",
                 "document_keyword": "synthetic-long.txt", "similarity": 0.9,
                 "metadata": {"scope": "business_rules", "source_type": "synthetic_test"}}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow real model calls/possible fees using synthetic text")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Review the script, then supply --execute for actual model calls")
    if not SDKRuntime().health():
        raise RuntimeError("SDK not ready")
    settings.RAG_MAX_RETRIEVAL_ROUNDS = 1
    settings.RAG_RERANK_PROVIDER = "disabled"
    start = time.monotonic()
    result = build_answer_graph(SyntheticEngine(), generate_answer=False).invoke(
        {"query": "合成测试规定里，支付指令金额不一致时应如何处理？", "scope": "business_rules", "top_k": 5,
         "sources": ["knowledge_base"]}, {"recursion_limit": 12})["result"]
    exact = all("excerpt" in item["metadata"]
                and item["content"] == TEXT[item["metadata"]["excerpt"]["start_char"]:item["metadata"]["excerpt"]["end_char"]]
                and utf16_units(item["content"]) <= 4000 for item in result["sources"])
    summary = {"evidence_status": result["evidence_status"], "context_coverage": result["context_coverage"],
               "source_count": len(result["sources"]), "original_chars": len(TEXT),
               "tail_rule_returned": any("不得仅因历史已通过" in item["content"] for item in result["sources"]),
               "exact_source_windows": exact, "elapsed_seconds": round(time.monotonic() - start, 2),
               "has_answer": "answer" in result}
    root = Path(__file__).resolve().parent.parent / "data"
    root.mkdir(exist_ok=True)
    (root / "long-context-smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["tail_rule_returned"] or not exact or not result["context_coverage"].get("input_complete") or summary["has_answer"]:
        raise RuntimeError("Long-text smoke did not meet its mechanism checks; inspect the safe summary")


if __name__ == "__main__":
    main()
