"""Read the project Agent Skills catalog shipped with the OpenCode runtime."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)
SKILLS_DIR = Path(__file__).resolve().parents[2] / "assistant-runtime" / ".opencode" / "skills"
_SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _read_skill(path: Path) -> dict[str, Any] | None:
    if not _SKILL_ID.fullmatch(path.name) or not path.is_dir():
        return None
    try:
        raw = (path / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.startswith("---\n"):
        logger.warning("Ignoring skill without YAML frontmatter: %s", path.name)
        return None
    frontmatter, separator, instructions = raw[4:].partition("\n---\n")
    if not separator:
        logger.warning("Ignoring skill with malformed frontmatter: %s", path.name)
        return None
    try:
        metadata = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError:
        logger.warning("Ignoring skill with invalid YAML frontmatter: %s", path.name)
        return None
    if not isinstance(metadata, dict) or metadata.get("name") != path.name:
        logger.warning("Ignoring skill whose name does not match its directory: %s", path.name)
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
        "id": path.name,
        "name": str(extra.get("displayName") or path.name),
        "desc": str(extra.get("shortDescription") or description),
        "version": str(extra.get("version") or "1.0.0"),
        "owner": str(extra.get("owner") or "AI 助手团队"),
        "license": str(metadata.get("license") or "Internal"),
        "permissions": permissions,
        "instructions": instructions.strip(),
    }


def list_skills() -> list[dict[str, Any]]:
    if not SKILLS_DIR.is_dir():
        return []
    skills = [_read_skill(path) for path in sorted(SKILLS_DIR.iterdir())]
    return [skill for skill in skills if skill is not None]


def get_skill(skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id or not _SKILL_ID.fullmatch(skill_id):
        return None
    return _read_skill(SKILLS_DIR / skill_id)
