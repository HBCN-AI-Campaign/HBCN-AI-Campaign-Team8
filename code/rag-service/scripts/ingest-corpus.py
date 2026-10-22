import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.manifest import SAFE_MANIFEST


def selected_files(source_root):
    selected = []
    for relative in SAFE_MANIFEST["business_rules"][:4]:
        path = source_root / relative
        if not path.is_file():
            raise SystemExit(f"业务文件不存在：{path.name}")
        selected.append((path, {"scope": "business_rules"}))
    catalog = json.loads((ROOT / "knowledge-base/catalog.json").read_text(encoding="utf-8"))
    for document_id in ["cn-overseas-loan-banks-2022", "cn-overseas-loan-banks-2026-72"]:
        item = next(item for item in catalog["documents"] if item["id"] == document_id)
        path = ROOT / "knowledge-base/docs/cn" / f"{document_id}.pdf"
        if not path.is_file():
            raise SystemExit(f"法规文件不存在：{path.name}；先运行资料下载脚本")
        selected.append((path, {"scope": "law", "source_url": item["url"], "jurisdiction": item["jurisdiction"]}))
    return selected


def main():
    parser = argparse.ArgumentParser(description="仅导入明确白名单的4份业务资料与2份境外贷款通知；默认只预览")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    selected = selected_files(args.source_root.resolve())
    for path, fields in selected:
        print(fields["scope"], path.name, flush=True)
    if not args.execute:
        print("仅预览，未发送文件；加 --execute 才会入库")
        return
    report = []
    with httpx.Client(base_url=args.base_url, headers={"Authorization": f"Bearer {settings.SERVICE_TOKEN}"}, timeout=120) as client:
        for path, fields in selected:
            with path.open("rb") as content:
                response = client.post("/api/v1/ingestions", data=fields, files={"file": (path.name, content)})
            response.raise_for_status()
            document_id = response.json()["document"]["id"]
            deadline = time.monotonic() + 600
            while True:
                status = client.get(f"/api/v1/documents/{document_id}")
                status.raise_for_status()
                document = status.json()
                if document["state"] in {"ready", "failed"}:
                    break
                if time.monotonic() > deadline:
                    raise SystemExit("索引等待超时，请通过文档状态接口检查")
                time.sleep(1)
            report.append({"id": document_id, "name": path.name, "state": document["state"], "chunks": document["chunk_count"]})
            print(document["state"], path.name, document["chunk_count"], flush=True)
            if document["state"] == "failed":
                raise SystemExit(document["error"])
    target = ROOT / "data/corpus-import.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
