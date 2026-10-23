"""Profile one local business PDF without emitting recognized content.

Run this with the OCR virtual environment and both source roots on PYTHONPATH.
The sample PDF stays in place; rendered pages are removed after each run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "code" / "backend"
OCR_ROOT = REPO_ROOT / "code" / "ocr_service"
for source_root in (str(BACKEND_ROOT), str(OCR_ROOT)):
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

DATASET_PREFIXES = {
    "8": "第八套材料",
    "9": "第九套材料",
    "10": "第十套材料",
}


def _parse_agent():
    app = types.ModuleType("app")
    app.__path__ = [str(BACKEND_ROOT / "app")]
    sys.modules["app"] = app
    config = types.ModuleType("app.config")
    config.UPLOAD_DIR = BACKEND_ROOT / "uploads"
    config.settings = types.SimpleNamespace(
        OCR_BASE_URL="",
        OCR_REQUEST_TIMEOUT_SECONDS=180,
    )
    sys.modules["app.config"] = config
    from app import parse_agent

    return parse_agent


def _fingerprint(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _worker(image: Path, batch_size: int, cpu_threads: int, doc_type: str) -> int:
    logging.disable(logging.CRITICAL)
    parse_agent = _parse_agent()

    from ocr_service import config as ocr_config
    from ocr_service.ocr_engine import OcrEngine

    ocr_config.OCR_TEXT_RECOGNITION_BATCH_SIZE = batch_size
    ocr_config.OCR_CPU_THREADS = cpu_threads
    engine = OcrEngine(lang="ch", device="cpu")

    started = time.perf_counter()
    engine._ensure()
    model_init_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    items = engine.recognize_image_detailed(image, min_score=0.3)
    inference_ms = (time.perf_counter() - started) * 1000
    text = "\n".join(item.get("text", "") for item in items if item.get("text"))
    blocks = [dict(item, page=1, method="paddleocr") for item in items]

    started = time.perf_counter()
    fields_without_evidence = parse_agent._extract_fields(
        doc_type, text, "diagnostic.pdf", []
    )
    normalization_ms = (time.perf_counter() - started) * 1000

    examined_blocks = [0]
    lookup_ns = [0]
    lookup_calls = [0]
    original_find = parse_agent._find_block

    class CountingBlocks(list):
        def __iter__(self):
            for block in super().__iter__():
                examined_blocks[0] += 1
                yield block

    def timed_find(source_blocks, value):
        started_ns = time.perf_counter_ns()
        lookup_calls[0] += 1
        try:
            return original_find(source_blocks, value)
        finally:
            lookup_ns[0] += time.perf_counter_ns() - started_ns

    parse_agent._find_block = timed_find
    try:
        started = time.perf_counter()
        fields = parse_agent._extract_fields(
            doc_type, text, "diagnostic.pdf", CountingBlocks(blocks)
        )
        mapping_ms = (time.perf_counter() - started) * 1000
    finally:
        parse_agent._find_block = original_find

    result = {
        "batch_size": batch_size,
        "cpu_threads": cpu_threads,
        "model_init_ms": round(model_init_ms, 1),
        "ocr_ms": round(inference_ms, 1),
        "ocr_lines": len(items),
        "ocr_chars": len(text),
        "ocr_fingerprint": _fingerprint(items),
        "field_fingerprint": _fingerprint(fields),
        "normalization_ms": round(normalization_ms, 2),
        "mapping_with_evidence_ms": round(mapping_ms, 2),
        "evidence_lookup_ms": round(lookup_ns[0] / 1_000_000, 2),
        "evidence_lookup_calls": lookup_calls[0],
        "evidence_blocks_examined": examined_blocks[0],
        "fields_with_values": sum(
            field.get("value") not in (None, "") for field in fields_without_evidence
        ),
        "fields_with_location": sum(bool(field.get("source")) for field in fields),
        "status": "ok" if items else "ocr_empty",
    }
    print("PROFILE_RESULT:" + json.dumps(result), flush=True)
    return 0


def _find_sample(root: Path, dataset: str, doc_type: str):
    parse_agent = _parse_agent()
    folders = [
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith(DATASET_PREFIXES[dataset])
    ]
    if len(folders) != 1:
        raise ValueError("dataset folder must resolve to exactly one directory")

    import pdfplumber

    for pdf in sorted(folders[0].rglob("*.pdf")):
        if parse_agent.guess_type(pdf.name) != doc_type:
            continue
        with pdfplumber.open(pdf) as document:
            native_chars = sum(
                len((page.extract_text() or "").strip()) for page in document.pages
            )
            page_count = len(document.pages)
        if native_chars < 20:
            return pdf, native_chars, page_count
    raise ValueError("no scanned PDF found for requested dataset and type")


def _run_variant(image: Path, batch_size: int, cpu_threads: int, doc_type: str) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--image",
        str(image),
        "--batch-size",
        str(batch_size),
        "--worker-cpu-threads",
        str(cpu_threads),
        "--doc-type",
        doc_type,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("OCR profile worker failed")
    line = next(
        (line for line in reversed(completed.stdout.splitlines())
         if line.startswith("PROFILE_RESULT:")),
        None,
    )
    if line is None:
        raise RuntimeError("OCR profile worker returned no result")
    return json.loads(line.removeprefix("PROFILE_RESULT:"))


def _profile(args) -> int:
    logging.disable(logging.CRITICAL)
    root_value = os.environ.get("HBCN_BUSINESS_MATERIALS_ROOT")
    if not root_value:
        raise ValueError("HBCN_BUSINESS_MATERIALS_ROOT is required")

    pdf, native_chars, page_count = _find_sample(
        Path(root_value), args.dataset, args.doc_type
    )
    from ocr_service.pdf_to_image import pdf_to_images
    from ocr_service.parser import _remove_rendered_pages

    started = time.perf_counter()
    images = pdf_to_images(pdf, dpi=200)
    render_ms = (time.perf_counter() - started) * 1000
    if len(images) != page_count:
        _remove_rendered_pages(images)
        raise RuntimeError("rendered page count does not match PDF page count")

    try:
        variants = [
            _run_variant(images[0], batch_size, cpu_threads, args.doc_type)
            for cpu_threads in args.cpu_threads
            for batch_size in args.batch_sizes
        ]
    finally:
        _remove_rendered_pages(images)

    baseline = variants[0] if variants else None
    output = {
        "dataset": f"set_{args.dataset}",
        "doc_type": args.doc_type,
        "pages": page_count,
        "native_chars": native_chars,
        "render_dpi": 200,
        "render_ms": round(render_ms, 1),
        "variants": [
            {key: value for key, value in row.items()
             if key not in ("ocr_fingerprint", "field_fingerprint")}
            for row in variants
        ],
        "ocr_output_identical": (
            all(row["ocr_fingerprint"] == variants[0]["ocr_fingerprint"] for row in variants)
            if len(variants) > 1 else None
        ),
        "business_field_output_identical": (
            all(row["field_fingerprint"] == baseline["field_fingerprint"] for row in variants)
            if baseline and len(variants) > 1 else None
        ),
        "inference_speedup_vs_first_variant": {
            f"threads_{row['cpu_threads']}_batch_{row['batch_size']}": round(
                baseline["ocr_ms"] / row["ocr_ms"], 3
            )
            for row in variants
            if baseline and row != baseline and row["ocr_ms"]
        },
        "status": "profiled",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASET_PREFIXES, default="10")
    parser.add_argument("--doc-type", choices=("PROFORMA_INVOICE",), default="PROFORMA_INVOICE")
    parser.add_argument("--batch-sizes", default="1,8")
    parser.add_argument("--cpu-threads", default="4,1")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-cpu-threads", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        if not args.image or not args.batch_size or not args.worker_cpu_threads:
            raise ValueError("worker arguments are incomplete")
        return _worker(
            args.image, args.batch_size, args.worker_cpu_threads, args.doc_type
        )

    try:
        args.batch_sizes = [int(value) for value in args.batch_sizes.split(",")]
        args.cpu_threads = [int(value) for value in args.cpu_threads.split(",")]
        if not args.batch_sizes or any(value < 1 for value in args.batch_sizes):
            raise ValueError("batch sizes must be positive integers")
        if not args.cpu_threads or any(value < 1 for value in args.cpu_threads):
            raise ValueError("CPU thread counts must be positive integers")
        return _profile(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "profile_failed", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
