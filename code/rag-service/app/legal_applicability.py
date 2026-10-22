"""Deterministic constraints for case-specific use of legal evidence.

Provider metadata and user input cannot approve a legal source. A separate
server-owned review registry must bind approved scope to the original content
hash. Passing these checks is still not an automatic legal/credit approval.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings


def iso_date(value):
    if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return value


class LegalContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    business_date: str
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}(?:-[A-Z0-9]{1,8})?$")
    subject_type: str = Field(min_length=1, max_length=80)
    business_type: str = Field(min_length=1, max_length=80)

    _date = field_validator("business_date")(iso_date)

    @field_validator("subject_type", "business_type")
    @classmethod
    def nonempty(cls, value):
        if value != value.strip() or not value.strip():
            raise ValueError("scope must be a nonempty exact taxonomy value")
        return value


class LegalReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_id: str = Field(min_length=1, max_length=100)
    document_id: str = Field(min_length=1, max_length=300)
    chunk_id: str = Field(min_length=1, max_length=300)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_version: str | None = Field(max_length=300)
    state: Literal["approved", "revoked"]
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_at: str
    review_expires_on: str
    valid_from: str
    # Explicit null means the reviewer approved an open-ended interval;
    # missing validity data is not treated as open-ended.
    valid_to_exclusive: str | None
    jurisdictions: list[str] = Field(min_length=1, max_length=20)
    subject_types: list[str] = Field(min_length=1, max_length=20)
    business_types: list[str] = Field(min_length=1, max_length=20)
    authority_url: str = Field(min_length=1, max_length=2000)

    _dates = field_validator("review_expires_on", "valid_from")(iso_date)

    @field_validator("valid_to_exclusive")
    @classmethod
    def end_date(cls, value):
        return iso_date(value) if value is not None else None

    @model_validator(mode="after")
    def review_constraints(self):
        timestamp = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
            raise ValueError("reviewed_at must be a past timezone-aware timestamp")
        if self.review_expires_on < timestamp.date().isoformat():
            raise ValueError("review expires before it was performed")
        if self.valid_to_exclusive is not None and self.valid_to_exclusive <= self.valid_from:
            raise ValueError("invalid legal validity interval")
        for values in (self.jurisdictions, self.subject_types, self.business_types):
            if any(not value.strip() or value != value.strip() or len(value) > 80 for value in values):
                raise ValueError("invalid review scope")
        if not self.authority_url.startswith("https://"):
            raise ValueError("review authority must use https")
        return self


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    reviews: list[LegalReview] = Field(max_length=10000)


def read_registry():
    if not settings.RAG_LEGAL_REVIEW_FILE:
        return None, "未配置服务端法规复核台账"
    try:
        path = Path(settings.RAG_LEGAL_REVIEW_FILE)
        if path.stat().st_size > 10_000_000:
            raise ValueError("registry too large")
        return Registry.model_validate(json.loads(path.read_text(encoding="utf-8"))), None
    except (OSError, ValueError, TypeError):
        # Never expose curator content, filesystem paths or parsing exceptions.
        return None, "服务端法规复核台账不可用或格式异常"


def binding(item):
    excerpt = item.get("metadata", {}).get("excerpt")
    return (item["document_id"], excerpt["parent_chunk_id"] if excerpt else item.get("chunk_id"),
            excerpt["parent_content_sha256"] if excerpt else hashlib.sha256(item["content"].encode()).hexdigest(),
            item.get("metadata", {}).get("version"))


def check_legal_applicability(items, *, purpose="reference", context=None, today=None, require_legal=False):
    law = [item for item in items if item.get("metadata", {}).get("scope") == "law" or item.get("metadata", {}).get("source_type") == "pkulaw"]
    report = {"purpose": purpose, "status": "not_required", "evidence": [],
              "limitation": "结构化约束通过也不等于法律或信贷审批结论"}
    if not law:
        if purpose == "case_assessment" and require_legal:
            report["status"] = "legal_evidence_required"
            return report, ["本案法规判断缺少已选定的法规原文，不能用其他资料代替法规适用性核验"]
        return report, []
    if purpose != "case_assessment":
        report["status"] = "reference_only"
        report["evidence"] = [{"document_id": item["document_id"], "chunk_id": item.get("chunk_id"), "status": "unverified"} for item in law]
        return report, []
    try:
        context = LegalContext.model_validate(context or {})
    except ValueError:
        report["status"] = "context_required"
        return report, ["本案法规判断需要明确业务日期、司法辖区、适用主体和业务类型；不由模型猜测"]
    registry, error = read_registry()
    if error:
        report["status"] = "review_required"
        return report, [error + "，不能确认本案法规适用范围"]
    today = today or datetime.now(timezone.utc).date().isoformat()
    gaps = []
    for item in law:
        key = binding(item)
        records = [review for review in registry.reviews
                   if (review.document_id, review.chunk_id, review.content_sha256, review.source_version) == key]
        reasons = []
        # Multiple reviews require explicit resolution rather than arbitrary latest-wins.
        if len(records) != 1:
            reasons.append("原文缺少唯一匹配的复核记录或存在复核冲突")
        else:
            review = records[0]
            if review.state != "approved":
                reasons.append("原文复核已撤销")
            if review.review_expires_on < today:
                reasons.append("法规复核记录已过期")
            if context.business_date < review.valid_from or (review.valid_to_exclusive is not None and context.business_date >= review.valid_to_exclusive):
                reasons.append("业务时点不在已复核的法规版本有效区间内")
            if context.jurisdiction not in review.jurisdictions:
                reasons.append("司法辖区不匹配，不能推断跨辖区适用")
            if context.subject_type not in review.subject_types:
                reasons.append("适用主体不匹配")
            if context.business_type not in review.business_types:
                reasons.append("业务类型不匹配")
        entry = {"document_id": item["document_id"], "chunk_id": item.get("chunk_id"),
                 "status": "blocked" if reasons else "reviewed_constraints_match", "reasons": reasons}
        if len(records) == 1:
            entry["review_id"] = records[0].review_id
        report["evidence"].append(entry)
        gaps.extend(reasons)
    report["status"] = "blocked" if gaps else "reviewed_constraints_match"
    return report, list(dict.fromkeys(gaps))
