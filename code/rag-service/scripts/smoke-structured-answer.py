"""Actual planning/generation/verification with synthetic evidence; explicit opt-in."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.answer_graph import build_answer_graph
from app.config import settings
from app.runtime_client import SDKRuntime


TEXT = "合成测试规定：支付指令金额与支持单据不一致时，应暂停处理，核对原始单据，并更正后重新提交。不得仅因历史已通过而直接放行。"


class Engine:
    def retrieve(self, **kwargs):
        return [{"content": TEXT, "document_keyword": "synthetic-only.txt", "document_id": "synthetic",
                 "chunk_id": "s1", "similarity": 0.9, "metadata": {"scope": "business_rules"}}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow actual model calls/fees with synthetic data")
    if not parser.parse_args().execute:
        parser.error("use --execute for real model calls")
    runtime = SDKRuntime()
    if not runtime.health():
        raise RuntimeError("SDK not ready")
    settings.RAG_MAX_RETRIEVAL_ROUNDS = 1
    settings.RAG_RERANK_PROVIDER = "disabled"
    start = time.monotonic()
    result = build_answer_graph(Engine(), runtime).invoke(
        {"query": "合成规定里，支付指令金额不一致时应如何处理？", "scope": "business_rules", "top_k": 5,
         "sources": ["knowledge_base"]}, {"recursion_limit": 12})["result"]
    summary = {"grounding": result["grounding"], "verification": result["answer_verification"]["status"],
               "segments": result["answer_verification"].get("segments", 0), "source_count": len(result["sources"]),
               "answer_contains_correction": "更正" in result["answer"],
               "elapsed_seconds": round(time.monotonic() - start, 2)}
    root = Path(__file__).resolve().parent.parent / "data"
    root.mkdir(exist_ok=True)
    (root / "structured-answer-smoke.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    if result["grounding"] != "cited" or not summary["answer_contains_correction"]:
        raise RuntimeError("Structured answer smoke did not pass; inspect safe summary")


if __name__ == "__main__":
    main()
