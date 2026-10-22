"""Compare two ranked-candidate runs on the exact same reviewed dataset."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import evaluate, load_ranking, load_set, validate_split_isolation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="reviewed evaluation set JSON")
    parser.add_argument("--development", help="development JSON, required when --cases is the holdout")
    parser.add_argument("--baseline", required=True, help="baseline ranked candidates JSON")
    parser.add_argument("--candidate", required=True, help="candidate ranked candidates JSON")
    parser.add_argument("--output", required=True, help="new report JSON path")
    args = parser.parse_args()
    try:
        dataset = load_set(args.cases)
    except ValueError as error:
        parser.error(str(error))
    if dataset.split == "holdout":
        if not args.development:
            parser.error("--development is required before evaluating a holdout set")
        try:
            validate_split_isolation(load_set(args.development), dataset)
        except ValueError as error:
            parser.error(str(error))
    elif args.development:
        parser.error("--development may only accompany a holdout set")
    try:
        report = evaluate(dataset, load_ranking(args.baseline), load_ranking(args.candidate))
    except ValueError as error:
        parser.error(str(error))
    with open(args.output, "x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"report_sha256": report["report_sha256"], "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
