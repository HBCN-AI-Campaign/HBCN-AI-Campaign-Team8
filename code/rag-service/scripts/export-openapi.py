"""Export the reviewable v1 API snapshot without starting services or reading data."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed API snapshot has drifted")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "contracts/openapi-v1.json"
    content = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("OpenAPI snapshot changed; review v1 compatibility, versions and contract documentation")
        print("PASS: API snapshot matches the service; compatibility review is still required for intentional changes")
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print("Exported contracts/openapi-v1.json; no database/model initialization")


if __name__ == "__main__":
    main()
