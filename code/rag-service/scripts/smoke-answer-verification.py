"""Opt-in real SDK positive/negative controls with synthetic evidence only."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.answer_verification import verify_answer
from app.runtime_client import SDKRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow actual SDK calls and possible fees")
    if not parser.parse_args().execute:
        parser.error("use --execute for real model calls")
    runtime = SDKRuntime()
    if not runtime.health():
        raise RuntimeError("SDK not ready")
    evidence = [{"content": "合成规定：金额不一致时应暂停处理，核对原始单据并更正后重新提交。不得因历史通过而直接放行。",
                 "document_keyword": "synthetic-only.txt", "document_id": "synthetic", "chunk_id": "s1", "metadata": {}}]
    start = time.monotonic()
    positive = verify_answer(answer="金额不一致时应暂停处理，核对原始单据并更正后重新提交。[1]",
                             query="金额不符怎么办？", evidence=evidence, complete=runtime.complete)
    negative = verify_answer(answer="金额不一致时可以因历史通过而直接放行。[1]",
                             query="金额不符怎么办？", evidence=evidence, complete=runtime.complete)
    summary = {"positive_control": positive["status"], "negative_control": negative["status"],
               "elapsed_seconds": round(time.monotonic() - start, 2)}
    root = Path(__file__).resolve().parent.parent / "data"
    root.mkdir(exist_ok=True)
    (root / "answer-verification-controls.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    if positive["status"] != "supported_by_model" or negative["status"] != "unsupported":
        raise RuntimeError("Verification controls did not both pass; inspect safe summary")


if __name__ == "__main__":
    main()
