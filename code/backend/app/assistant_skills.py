"""Read the project Agent Skills catalog shipped with the OpenCode runtime."""
from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from .assistant_models import AssistantCustomSkill

logger = logging.getLogger(__name__)
SKILLS_DIR = Path(__file__).resolve().parents[2] / "assistant-runtime" / ".opencode" / "skills"
_SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _parse_skill(skill_id: str, raw: str) -> dict[str, Any] | None:
    if not _SKILL_ID.fullmatch(skill_id):
        return None
    if not raw.startswith("---\n"):
        logger.warning("Ignoring skill without YAML frontmatter: %s", skill_id)
        return None
    frontmatter, separator, instructions = raw[4:].partition("\n---\n")
    if not separator:
        logger.warning("Ignoring skill with malformed frontmatter: %s", skill_id)
        return None
    try:
        metadata = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError:
        logger.warning("Ignoring skill with invalid YAML frontmatter: %s", skill_id)
        return None
    if not isinstance(metadata, dict) or metadata.get("name") != skill_id:
        logger.warning("Ignoring skill whose name does not match its identifier: %s", skill_id)
        return None
    extra = metadata.get("metadata") or {}
    permissions = extra.get("permissions") or metadata.get("allowed-tools") or []
    if isinstance(permissions, str):
        permissions = [item.strip() for item in permissions.split(",") if item.strip()]
    description = metadata.get("description")
    if (
        not isinstance(extra, dict)
        or not isinstance(permissions, list)
        or any(not isinstance(item, str) for item in permissions)
        or not isinstance(description, str)
        or not description.strip()
    ):
        return None
    return {
        "id": skill_id,
        "name": str(extra.get("displayName") or skill_id),
        "desc": str(extra.get("shortDescription") or description),
        "version": str(extra.get("version") or "1.0.0"),
        "owner": str(extra.get("owner") or "AI 助手团队"),
        "license": str(metadata.get("license") or "Internal"),
        "permissions": permissions,
        "instructions": instructions.strip(),
    }


def _read_skill(path: Path) -> dict[str, Any] | None:
    if not _SKILL_ID.fullmatch(path.name) or not path.is_dir():
        return None
    try:
        raw = (path / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_skill(path.name, raw)


def list_skills() -> list[dict[str, Any]]:
    if not SKILLS_DIR.is_dir():
        return []
    skills = [_read_skill(path) for path in sorted(SKILLS_DIR.iterdir())]
    return [skill for skill in skills if skill is not None]


def get_skill(skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id or not _SKILL_ID.fullmatch(skill_id):
        return None
    return _read_skill(SKILLS_DIR / skill_id)


def new_custom_skill_id(user_id: int) -> str:
    return f"private-{user_id}-{secrets.token_hex(5)}"


def custom_skill_document(skill_id: str, name: str, description: str, instructions: str, revision: int) -> str:
    metadata = {
        "name": skill_id,
        "description": description,
        "metadata": {
            "displayName": name,
            "version": f"1.0.{revision}",
            "owner": "个人创建",
        },
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{frontmatter}\n---\n\n{instructions.strip()}\n"


def list_user_skills(db: Session, user_id: int) -> list[dict[str, Any]]:
    result = []
    rows = db.query(AssistantCustomSkill).filter_by(user_id=user_id).order_by(
        AssistantCustomSkill.updated_at.desc(), AssistantCustomSkill.id
    ).all()
    for row in rows:
        skill = _parse_skill(row.id, row.document)
        if skill:
            skill.update(is_custom=True, editable=True, revision=row.revision)
            result.append(skill)
    return result


def list_available_skills(db: Session, user_id: int) -> list[dict[str, Any]]:
    shipped = [dict(skill, is_custom=False, editable=False) for skill in list_skills()]
    return shipped + list_user_skills(db, user_id)


def get_user_skill(db: Session, user_id: int, skill_id: str) -> dict[str, Any] | None:
    if not skill_id.startswith(f"private-{user_id}-"):
        return None
    row = db.get(AssistantCustomSkill, skill_id)
    if row is None or row.user_id != user_id:
        return None
    skill = _parse_skill(row.id, row.document)
    if skill:
        skill.update(is_custom=True, editable=True, revision=row.revision)
    return skill


def get_skill_for_user(db: Session, user_id: int, skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id:
        return None
    shipped = get_skill(skill_id)
    if shipped:
        return dict(shipped, is_custom=False, editable=False)
    return get_user_skill(db, user_id, skill_id)
