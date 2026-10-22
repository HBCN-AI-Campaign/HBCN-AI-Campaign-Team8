"""Run live paired RRF/reranker evaluation against the configured RAG index."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.engine import engine_kind, get_engine
from app.evaluation import load_set, validate_split_isolation
from app.evaluation_runner import EvaluationRunError, collect_paired_rankings, validate_evaluation_preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="reviewed evaluation JSON; holdout requires --development")
    parser.add_argument("--development", help="reviewed development set used for holdout contamination check")
    parser.add_argument("--baseline-output", required=True, help="new content-free baseline rankings JSON")
    parser.add_argument("--candidate-output", required=True, help="new content-free reranked results JSON")
    parser.add_argument("--report-output", required=True, help="new aggregate report JSON")
    parser.add_argument("--max-cases", type=int, default=120, help="maximum cases this invocation may process (default 120)")
    parser.add_argument("--allow-external-sources", action="store_true", help="explicitly permit configured paid/remote sources such as Pkulaw")
    parser.add_argument("--max-external-calls", type=int, help="maximum law source queries; each may make 1 search and up to 2 article tool calls")
    parser.add_argument("--allow-embedding-dataflow", action="store_true", help="explicitly permit sending reviewed query text to the configured remote Embedding provider")
    parser.add_argument("--allow-reranker-dataflow", action="store_true", help="explicitly permit sending retrieved evidence text to the configured remote reranker")
    args = parser.parse_args()
    try:
        dataset = load_set(args.cases)
    except ValueError as error:
        parser.error(str(error))
    if dataset.split == "holdout":
        if not args.development:
            parser.error("--development is required before running a holdout evaluation")
        try:
            development = load_set(args.development)
            validate_split_isolation(development, dataset)
        except ValueError as error:
            parser.error(str(error))
    elif args.development:
        parser.error("--development may only accompany a holdout set")
    outputs = [Path(args.baseline_output), Path(args.candidate_output), Path(args.report_output)]
    if len({str(path.resolve()) for path in outputs}) != 3 or any(path.exists() for path in outputs):
        parser.error("all three output paths must be distinct and new")
    if any(not path.parent.is_dir() for path in outputs):
        parser.error("output parent directories must already exist")
    if not 1 <= args.max_cases <= 500:
        parser.error("--max-cases must be from 1 to 500")
    if args.max_external_calls is not None and not 0 <= args.max_external_calls <= args.max_cases:
        parser.error("--max-external-calls must be between 0 and --max-cases")
    if engine_kind() != "postgres":
        parser.error("live ranking evaluation requires the configured PostgreSQL/pgvector engine")
    law_source = None
    if any("pkulaw" in case.sources for case in dataset.cases):
        from app.pkulaw import PkulawSource
        law_source = PkulawSource()
    try:
        validate_evaluation_preflight(dataset, allow_external_sources=args.allow_external_sources,
            allow_embedding_dataflow=args.allow_embedding_dataflow, allow_reranker_dataflow=args.allow_reranker_dataflow,
            max_cases=args.max_cases, external_call_budget=args.max_external_calls, law_source=law_source)
    except EvaluationRunError as error:
        parser.error(str(error))
    baseline, candidate, report = collect_paired_rankings(dataset, engine=get_engine(),
        allow_external_sources=args.allow_external_sources, allow_embedding_dataflow=args.allow_embedding_dataflow,
        allow_reranker_dataflow=args.allow_reranker_dataflow, law_source=law_source, max_cases=args.max_cases,
        external_call_budget=args.max_external_calls)
    payloads = (baseline.model_dump(mode="json"), candidate.model_dump(mode="json"), report)
    opened, created = [], []
    try:
        for path in outputs:
            opened.append(path.open("x", encoding="utf-8"))
            created.append(path)
        for output, payload in zip(opened, payloads):
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except Exception:
        for output in opened:
            output.close()
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for output in opened:
            if not output.closed:
                output.close()
    print(json.dumps({"comparison_id": baseline.comparison_id, "report_sha256": report["report_sha256"],
                      "outputs": [str(path) for path in outputs], "cases": len(dataset.cases),
                      "embedding_model": settings.EMBEDDING_MODEL, "reranker_model": settings.RAG_RERANK_MODEL}, ensure_ascii=False))


if __name__ == "__main__":
    main()
