"""Reviewed historical references are separate from rules and task documents."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceLink(ReferenceModel):
    source_id: str = Field(min_length=3, max_length=100)
    source_version: str = Field(min_length=1, max_length=100)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    relation: Literal["supporting", "contradicting"]


class ReferenceCandidate(ReferenceModel):
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    logical_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._:-]{2,79}$")
    kind: Literal["case_reference", "experience_memory"]
    product: str = Field(min_length=1, max_length=100)
    jurisdiction: str = Field(min_length=1, max_length=100)
    issue_type: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    business_date: date
    source_reviewed_at: datetime
    retain_until: datetime
    facts_summary: str = Field(min_length=10, max_length=5000)
    handling: str = Field(min_length=10, max_length=5000)
    evidence: list[EvidenceLink] = Field(min_length=1, max_length=40)
    conclusion_status: Literal["confirmed", "disputed", "revoked"]
    redaction_confirmed: bool
    sharing_authorized: bool
    leakage_group_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._:-]{7,99}$")
    evaluation_only: bool = False
    memory_type: Literal["checklist", "query_strategy"] | None = None
    parent_version_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("source_reviewed_at", "retain_until")
    @classmethod
    def aware_time(cls, value):
        if value.utcoffset() is None:
            raise ValueError("timestamps require an explicit timezone")
        return value

    @field_validator("product", "jurisdiction", "issue_type", "policy_version", "facts_summary", "handling")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("reference fields cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def memory_boundary(self):
        if len(set(self.parent_version_ids)) != len(self.parent_version_ids):
            raise ValueError("parent versions must be unique")
        if self.kind == "case_reference" and (self.parent_version_ids or self.memory_type):
            raise ValueError("case references cannot contain memory instructions or parents")
        if self.kind == "experience_memory" and (len(self.parent_version_ids) < 2 or self.memory_type is None):
            raise ValueError("experience memory requires at least two case versions and a bounded memory type")
        return self


class ReferenceReview(ReferenceModel):
    expected_revision: int = Field(ge=1, strict=True)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReferenceWithdrawal(ReferenceReview):
    reason: Literal["correction", "revoked", "permission_changed", "policy_changed"]


class ReferenceSearch(ReferenceModel):
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    kind: Literal["case_reference", "experience_memory"]
    query: str = Field(min_length=1, max_length=1000)
    product: str = Field(min_length=1, max_length=100)
    jurisdiction: str = Field(min_length=1, max_length=100)
    issue_type: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    # Required curation-issued exclusions when the caller evaluates held-out cases.
    excluded_leakage_groups: list[str] = Field(default_factory=list, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20, strict=True)
