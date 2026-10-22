"""Versioned mechanical checks; never an OCR accuracy or legal-quality score.

Uncertain extraction requires a credentialed human review of the exact source,
parsed units and report. Invalid/lossy output cannot be approved by this route.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "document-quality-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def assess_pages(pages):
    blockers, reviews, units = [], [], []
    if not pages or len(pages) > 2000:
        blockers.append("invalid_unit_count")
    for index, page in enumerate(pages):
        text = page.get("text")
        if not isinstance(text, str):
            blockers.append("invalid_text_type")
            continue
        controls = sum(unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\r\t\f" for char in text)
        replacements = text.count("\ufffd")
        if replacements or controls:
            blockers.append("lossy_or_invalid_text")
        reasons = []
        if not text.strip():
            reasons.append("empty_unit")
        if page.get("extraction", {}).get("method") in {"ocr_service", "vision_ocr", "ocr_unknown"}:
            reasons.append("ocr_requires_source_comparison")
        if not page.get("extraction", {}).get("method"):
            reasons.append("extraction_provenance_missing")
        if any(unicodedata.category(char) == "Co" for char in text) or re.search(r"\(cid:\d+\)", text):
            reasons.append("unmapped_glyphs")
        reasons.extend(page.get("extraction", {}).get("review_reasons", []))
        reviews.extend(reasons)
        units.append({"index": index, "page": page.get("page"), "section": page.get("section"),
            "characters": len(text), "replacement_characters": replacements, "invalid_controls": controls,
            "method": page.get("extraction", {}).get("method", "native_unknown"), "review_reasons": sorted(set(reasons))})
    if not any(isinstance(page.get("text"), str) and page["text"].strip() for page in pages):
        blockers.append("no_indexable_text")
    report = {"policy_version": POLICY_VERSION, "parsed_sha256": digest(pages), "unit_count": len(pages),
        "status": "quarantined" if blockers else "quality_review" if reviews else "mechanically_checked",
        "blockers": sorted(set(blockers)), "review_reasons": sorted(set(reviews)), "units": units,
        "limits": ["not_ocr_accuracy", "not_source_completeness_proof", "not_legal_approval"]}
    report["report_sha256"] = digest(report)
    return report


class QualityReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_parsed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject"]
    verified_units: list[int] = Field(max_length=2000)
    reason: Literal["source_compared", "incomplete", "incorrect", "unreadable"]


def approval_matches(row, report):
    approval = row["provenance"].get("quality_approval", {})
    return (approval.get("policy_version") == POLICY_VERSION and approval.get("source_sha256") == row["sha256"]
        and approval.get("parsed_sha256") == report["parsed_sha256"]
        and approval.get("report_sha256") == report["report_sha256"]
        and approval.get("decision") == "approve" and report["status"] == "quality_review")
