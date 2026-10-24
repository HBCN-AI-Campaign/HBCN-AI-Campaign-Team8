"""Run local OCR and deterministic review rules on sets 8-10 without logging document content."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx

from app import parse_agent
from app.config import settings
from app.rule_engine.runner import run_all


SET_CONFIG = {
    "第八套材料": ("set_8", "SUPPORTING__SELLER"),
    "第九套材料": ("set_9", "SUPPORTING__AMOUNT"),
    "第十套材料": ("set_10", "SUPPORTING__CONTRACT_NO"),
}

TARGET_DOCUMENT_TYPES = {
    "set_8": {"COMMERCIAL_CONTRACT", "PROFORMA_INVOICE", "WAYBILL", "PAYMENT_INSTRUCTION"},
    "set_9": {"COMMERCIAL_CONTRACT", "PROFORMA_INVOICE", "PAYMENT_INSTRUCTION"},
    "set_10": {"COMMERCIAL_CONTRACT", "PROFORMA_INVOICE", "CUSTOMS_DECLARATION"},
}

TARGET_KEY_FIELDS = {
    "set_8": [
        ("COMMERCIAL_CONTRACT", "seller"),
        ("PROFORMA_INVOICE", "seller"),
        ("WAYBILL", "seller"),
        ("PAYMENT_INSTRUCTION", "payee"),
    ],
    "set_9": [
        ("COMMERCIAL_CONTRACT", "amount"),
        ("PROFORMA_INVOICE", "amount"),
        ("PAYMENT_INSTRUCTION", "amount"),
    ],
    "set_10": [
        ("COMMERCIAL_CONTRACT", "contract_no"),
        ("PROFORMA_INVOICE", "contract_no"),
        ("CUSTOMS_DECLARATION", "contract_no"),
    ],
}


def _safe_ocr_url() -> str:
    url = os.getenv("OCR_BASE_URL", "http://127.0.0.1:7888").rstrip("/")
    if urlparse(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("OCR_BASE_URL must target loopback for this sensitive-material test")
    return url


def _has_source_location(field: dict) -> bool:
    source = field.get("source")
    bbox = source.get("bbox") if isinstance(source, dict) else None
    return bool(
        isinstance(source, dict)
        and source.get("page") is not None
        and isinstance(bbox, (list, tuple))
        and len(bbox) == 4
    )


def _local_documents(
    folder: Path,
    temp_root: Path,
    set_key: str,
    *,
    target_only: bool = False,
) -> tuple[list[dict], int, int, list[dict]]:
    pdfs = sorted(folder.rglob("*.pdf"))
    if len(pdfs) != 7:
        raise ValueError(f"{set_key} must contain exactly seven PDFs")

    selected = []
    required_types = TARGET_DOCUMENT_TYPES[set_key] if target_only else None
    found_types = set()
    for source in pdfs:
        doc_type = parse_agent.guess_type(source.name)
        if not doc_type:
            raise ValueError(f"{set_key} contains a file whose type is not recognized")
        if required_types is None or doc_type in required_types:
            if doc_type in found_types:
                raise ValueError(f"{set_key} contains duplicate target document types")
            found_types.add(doc_type)
            selected.append(source)
    if required_types is not None and found_types != required_types:
        raise ValueError(f"{set_key} is missing one or more target document types")

    uploads = []
    for source in selected:
        relative = Path("uploads") / set_key / source.name
        target = temp_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        uploads.append({"filename": source.name, "pdf_url": relative.as_posix()})

    ocr_metrics = []
    original_ocr = parse_agent._ocr_detailed

    def measured_ocr(abs_path: str, type_code: str | None = None):
        started = time.perf_counter()
        text, blocks, extracted_fields = original_ocr(abs_path, type_code)
        ocr_metrics.append({
            "type_code": type_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "ocr_chars": len(text),
            "ocr_blocks": len(blocks),
        })
        return text, blocks, extracted_fields

    parse_agent._ocr_detailed = measured_ocr
    try:
        parsed = parse_agent.parse_files(uploads)
    finally:
        parse_agent._ocr_detailed = original_ocr

    metrics_by_type = {}
    for document, metric in zip(parsed["documents"], ocr_metrics):
        fields = document["fields"]
        values_count = sum(
            field.get("value") not in (None, "") for field in fields
        )
        located_count = sum(_has_source_location(field) for field in fields)
        if metric["ocr_chars"] == 0 or metric["ocr_blocks"] == 0:
            if metric["duration_ms"] >= settings.OCR_REQUEST_TIMEOUT_SECONDS * 950:
                failure_class = "ocr_request_timeout"
            else:
                failure_class = "ocr_empty_or_service_error"
        elif values_count == 0:
            failure_class = "field_extraction_empty"
        elif located_count < values_count:
            failure_class = "source_location_incomplete"
        elif values_count < len(fields):
            failure_class = "partial_field_coverage_with_locations"
        else:
            failure_class = "parsed_with_source_location"
        metrics_by_type.setdefault(document["type_code"], []).append({
            **metric,
            "field_slots": len(fields),
            "fields_with_values": values_count,
            "fields_with_locations": located_count,
            "failure_class": failure_class,
        })
    parse_by_type = [
        {"type_code": type_code, **metric}
        for type_code, metrics in sorted(metrics_by_type.items())
        for metric in metrics
    ]
    return parsed["documents"], len(pdfs), len(selected), parse_by_type


def main() -> int:
    total_started = time.perf_counter()
    logging.disable(logging.CRITICAL)
    root_value = os.getenv("HBCN_BUSINESS_MATERIALS_ROOT")
    if not root_value:
        print(json.dumps({"error": "HBCN_BUSINESS_MATERIALS_ROOT is required"}))
        return 2

    root = Path(root_value)
    if not root.is_dir():
        print(json.dumps({"error": "materials directory is unavailable"}))
        return 2

    ocr_url = _safe_ocr_url()
    scope = os.getenv("HBCN_BUSINESS_ACCEPTANCE_SCOPE", "all")
    if scope not in {"all", "target_documents"}:
        print(json.dumps({"error": "unsupported acceptance scope"}))
        return 2
    target_only = scope == "target_documents"
    try:
        health = httpx.get(f"{ocr_url}/health", timeout=3)
        health.raise_for_status()
    except Exception:
        print(json.dumps({"error": "local OCR service is unavailable"}))
        return 2

    selected_sets = {
        item.strip()
        for item in os.getenv("HBCN_BUSINESS_ACCEPTANCE_DATASETS", "8,9,10").split(",")
        if item.strip()
    }
    if not selected_sets or not selected_sets <= {"8", "9", "10"}:
        print(json.dumps({"error": "unsupported dataset selection"}))
        return 2

    folders = {}
    for prefix, (set_key, _) in SET_CONFIG.items():
        if set_key.removeprefix("set_") not in selected_sets:
            continue
        matches = sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith(prefix))
        if len(matches) != 1:
            print(json.dumps({"error": f"expected one folder for {set_key}"}))
            return 2
        folders[set_key] = matches[0]

    old_upload_dir = parse_agent.UPLOAD_DIR
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix="hbcn-business-review-") as directory:
            app_dir = Path(directory) / "app"
            parse_agent.UPLOAD_DIR = app_dir / "uploads"
            for prefix, (set_key, expected_rule) in SET_CONFIG.items():
                if set_key not in folders:
                    continue
                set_started = time.perf_counter()
                parsed_docs, pdf_count, processed_count, parse_by_type = _local_documents(
                    folders[set_key], app_dir, set_key, target_only=target_only
                )
                parsed_by_type = {doc["type_code"]: doc for doc in parsed_docs}
                target_key_fields = [
                    field
                    for type_code, key in TARGET_KEY_FIELDS[set_key]
                    for field in parsed_by_type.get(type_code, {}).get("fields", [])
                    if field.get("key") == key
                ]
                target_key_values = [
                    field for field in target_key_fields
                    if field.get("value") not in (None, "")
                ]
                target_key_located = sum(_has_source_location(field) for field in target_key_values)
                docs = []
                field_count = located_count = recognized_count = 0
                for index, parsed in enumerate(parsed_docs, start=1):
                    fields = {item["key"]: item.get("value") for item in parsed["fields"]}
                    field_sources = {}
                    for field in parsed["fields"]:
                        field_count += 1
                        if field.get("value") not in (None, ""):
                            recognized_count += 1
                        if field.get("source"):
                            field_sources[field["key"]] = field["source"]
                        if _has_source_location(field):
                            located_count += 1
                    docs.append(SimpleNamespace(
                        id=index,
                        doc_code=parsed["doc_code"],
                        type_code=parsed["type_code"],
                        fields=fields,
                        pdf_file=parsed.get("pdf_file"),
                        field_sources=field_sources,
                    ))

                rule_results = {item.rule_id: item for item in run_all(docs)}
                target = rule_results.get(expected_rule)
                target_bad_rows = sum(
                    len(row) > 2 and row[2] == "bad"
                    for row in (target.detail or [])
                ) if target else 0
                set_result = {
                    "dataset": set_key,
                    "documents_available": pdf_count,
                    "documents_processed": processed_count,
                    "parsed_fields": field_count,
                    "recognized_fields": recognized_count,
                    "located_fields": located_count,
                    "recognized_field_locator_coverage": round(located_count / recognized_count, 4)
                    if recognized_count else None,
                    "field_extraction_coverage": round(recognized_count / field_count, 4)
                    if field_count else None,
                    "target_key_field_slots": len(TARGET_KEY_FIELDS[set_key]),
                    "target_key_fields_with_values": len(target_key_values),
                    "target_key_fields_located": target_key_located,
                    "target_key_field_locator_coverage": round(
                        target_key_located / len(TARGET_KEY_FIELDS[set_key]), 4
                    ) if TARGET_KEY_FIELDS[set_key] else None,
                    "target_rule": expected_rule,
                    "target_status": target.status.value if target else "missing",
                    "target_evidence_rows": len(target.detail or []) if target else 0,
                    "target_bad_evidence_rows": target_bad_rows,
                    "parse_by_type": parse_by_type,
                    "duration_ms": round((time.perf_counter() - set_started) * 1000, 1),
                    "target_hit": bool(
                        target and target.status.value == "fail" and target_bad_rows
                    ),
                    "failure_class_counts": {
                        failure_class: sum(
                            item["failure_class"] == failure_class
                            for item in parse_by_type
                        )
                        for failure_class in sorted({
                            item["failure_class"] for item in parse_by_type
                        })
                    },
                    "strong_rule_counts": {
                        state: sum(item.status.value == state for item in rule_results.values())
                        for state in ("pass", "fail", "warn", "skip")
                    },
                }
                results.append(set_result)
                print(json.dumps({"dataset_complete": set_key, **set_result}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"error": f"acceptance failed: {type(exc).__name__}"}, ensure_ascii=False))
        return 1
    finally:
        parse_agent.UPLOAD_DIR = old_upload_dir

    print(json.dumps({
        "duration_ms": round((time.perf_counter() - total_started) * 1000, 1),
        "ocr_request_timeout_seconds": settings.OCR_REQUEST_TIMEOUT_SECONDS,
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
