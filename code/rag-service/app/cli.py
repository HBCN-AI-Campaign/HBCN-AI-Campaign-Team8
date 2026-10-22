import argparse
import json
import mimetypes
from pathlib import Path

from .config import settings
from .manifest import manifest_paths
from .ragflow import RAGFlowClient, RAGFlowError, RAGFlowNotConfiguredError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HBCN RAGFlow 初始化与安全资料入库")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="创建或复用两个 RAGFlow dataset")
    bootstrap.add_argument("--json", action="store_true", help="以 JSON 输出结果")

    ingest = subparsers.add_parser("ingest", help="按白名单上传资料并等待解析")
    ingest.add_argument("--scope", choices=("business_rules", "project_design"))
    ingest.add_argument("--execute", action="store_true", help="真实上传；默认只检查和预览")
    ingest.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def dataset_description(scope: str) -> str:
    return {
        "business_rules": "HBCN Team 8 业务规则与贷款用途资料（白名单）",
        "project_design": "HBCN Team 8 项目方案与会议设计资料（白名单）",
    }[scope]


def bootstrap() -> dict[str, str]:
    client = RAGFlowClient()
    result = {}
    for scope in ("business_rules", "project_design"):
        result[scope] = client.ensure_dataset(scope=scope, description=dataset_description(scope))
    return result


def ingest(scope: str | None, execute: bool) -> list[dict[str, object]]:
    if not settings.BUSINESS_SOURCE_ROOT:
        raise RAGFlowNotConfiguredError("BUSINESS_SOURCE_ROOT 尚未配置")
    files = manifest_paths(Path(settings.BUSINESS_SOURCE_ROOT), scope)
    result = [
        {"scope": selected_scope, "path": str(path), "bytes": path.stat().st_size, "status": "planned"}
        for selected_scope, path in files
    ]
    if not execute:
        return result

    client = RAGFlowClient()
    dataset_ids = bootstrap()
    source_root = Path(settings.BUSINESS_SOURCE_ROOT).expanduser().resolve()
    existing_by_scope = {
        selected_scope: {str(doc.get("name")) for doc in client.list_documents(scope=selected_scope, dataset_id=dataset_ids[selected_scope])}
        for selected_scope in dataset_ids
    }
    for item, (selected_scope, path) in zip(result, files):
        if path.name in existing_by_scope[selected_scope]:
            item["status"] = "skipped_existing"
            continue
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        document_ids = client.upload(
            scope=selected_scope,
            dataset_id=dataset_ids[selected_scope],
            filename=path.name,
            content=path.read_bytes(),
            content_type=content_type,
            metadata={
                "source_path": path.relative_to(source_root).as_posix(),
                "knowledge_scope": selected_scope,
                "permission_scope": "team8",
                "document_version": str(path.stat().st_mtime_ns),
            },
        )
        client.wait_for_documents(
            scope=selected_scope,
            dataset_id=dataset_ids[selected_scope],
            document_ids=document_ids,
        )
        item["status"] = "indexed"
        item["document_ids"] = document_ids
    return result


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "bootstrap":
            output = bootstrap()
        else:
            output = ingest(args.scope, args.execute)
    except (FileNotFoundError, RAGFlowError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
