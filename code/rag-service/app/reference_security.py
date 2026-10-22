"""Service principals for controlled curation, not a substitute for user/task ACL.

The service credential is still required by the router. A separate, server-owned
registry binds a high-entropy reference key to a principal and exact namespaces.
No identity/role supplied in the request body is trusted. Reload on every call.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import Field, field_validator, model_validator

from .config import settings
from .reference_contracts import ReferenceModel


@dataclass(frozen=True)
class ReferencePrincipal:
    subject: str
    namespaces: frozenset[str]
    roles: frozenset[str]

    def require(self, namespace, role):
        if namespace not in self.namespaces or role not in self.roles:
            raise ReferenceForbidden("reference permission denied")


class ReferenceForbidden(PermissionError):
    pass


class PrincipalEntry(ReferenceModel):
    subject: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,99}$")
    key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    namespaces: list[str] = Field(min_length=1, max_length=50)
    roles: list[Literal["reader", "author", "reviewer"]] = Field(min_length=1, max_length=3)
    valid_until: datetime

    @field_validator("valid_until")
    @classmethod
    def aware_expiry(cls, value):
        if value.utcoffset() is None:
            raise ValueError("principal expiry requires a timezone")
        return value


class PrincipalRegistry(ReferenceModel):
    principals: list[PrincipalEntry] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_keys(self):
        import re
        if len({item.key_sha256 for item in self.principals}) != len(self.principals):
            raise ValueError("principal keys must be unique")
        if len({item.subject for item in self.principals}) != len(self.principals):
            raise ValueError("one key per subject; rotate by replacing the registry entry")
        for item in self.principals:
            if any(not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", namespace) for namespace in item.namespaces):
                raise ValueError("invalid namespace")
        return self


def require_reference_principal(x_reference_key: str | None = Header(default=None)):
    if not settings.RAG_REFERENCES_ENABLED:
        raise HTTPException(404, "参考库接口未开放")
    if not x_reference_key or not 32 <= len(x_reference_key) <= 256:
        raise HTTPException(401, "参考库凭证无效")
    try:
        path = Path(settings.RAG_REFERENCE_PRINCIPALS_FILE)
        if not settings.RAG_REFERENCE_PRINCIPALS_FILE or path.stat().st_size > 256_000:
            raise ValueError("invalid registry")
        registry = PrincipalRegistry.model_validate_json(path.read_bytes())
    except Exception:
        raise HTTPException(503, "参考库主体注册表未就绪") from None
    digest = hashlib.sha256(x_reference_key.encode()).hexdigest()
    for entry in registry.principals:
        if hmac.compare_digest(digest, entry.key_sha256):
            if entry.valid_until <= datetime.now(timezone.utc):
                raise HTTPException(401, "参考库凭证无效")
            return ReferencePrincipal(entry.subject, frozenset(entry.namespaces), frozenset(entry.roles))
    raise HTTPException(401, "参考库凭证无效")
