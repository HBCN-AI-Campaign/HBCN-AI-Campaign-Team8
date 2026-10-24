"""AI 助手的独立通信契约。

这些 DTO 与现有任务审核 DTO 分开，方便前端工作台或其他 Agent 通过稳定的
JSON/SSE 协议接入，而不需要依赖某个具体的页面实现。
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantSessionCreate(BaseModel):
    title: str = Field(default="新会话", max_length=128)
    task_code: str | None = Field(default=None, max_length=64)


class AssistantSessionOut(BaseModel):
    id: int
    title: str
    task_code: str | None = None
    message_count: int = 0
    updated_at: dt.datetime
    owner_id: int = 0
    shared: bool = False
    can_manage: bool = False


class AssistantMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    status: str
    steps: list = Field(default_factory=list)
    citations: list = Field(default_factory=list)
    created_at: dt.datetime
    author_id: int | None = None
    author_name: str = ""
    run_id: str | None = None

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: dt.datetime) -> dt.datetime:
        # SQLite drops offsets from DateTime; all model timestamps are UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class AssistantRunOut(BaseModel):
    """Retry a POST using the original client_message_id to resume this run."""
    id: str
    status: Literal["running", "completed", "error", "cancelled"]
    session_id: int
    user_id: int
    client_message_id: str


class AssistantRunDetail(AssistantRunOut):
    """Final message is available only for a completed run, never a partial answer."""
    message: AssistantMessageOut | None = None


class AssistantRoomEvent(BaseModel):
    """Durable public envelope; additional fields follow the event name.

    step/tool/delta/citations/message_end use the existing SSE bodies;
    discussion carries a message, run_end carries status. Never reasoning.
    """
    model_config = ConfigDict(extra="allow")
    id: int
    run_id: str | None = None
    event: str


class AssistantEventPage(BaseModel):
    events: list[AssistantRoomEvent]
    cursor: int = Field(description="Pass as after_id on the next read; not an authorization token")
    has_more: bool
    active_run: AssistantRunOut | None = None


class AssistantSessionDetail(AssistantSessionOut):
    messages: list[AssistantMessageOut] = Field(default_factory=list)
    event_cursor: int = 0
    active_run: AssistantRunOut | None = None


class AssistantChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    task_code: str | None = Field(default=None, max_length=64)
    skill_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    client_message_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空")
        return value


class AssistantCapabilities(BaseModel):
    sdk: str
    configured: bool
    model: str | None = None
    rag_available: bool
    supports_stream: bool = True
    message: str


class AssistantSkillOut(BaseModel):
    id: str
    name: str
    desc: str
    version: str
    owner: str
    license: str
    permissions: list[str] = Field(default_factory=list)
    is_custom: bool = False
    editable: bool = False
    revision: int | None = None


class AssistantLibrarySkillOut(AssistantSkillOut):
    source: str
    installed: bool
    update_available: bool


class AssistantCustomSkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    desc: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=12000)

    @field_validator("name", "desc", "instructions")
    @classmethod
    def trim_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("技能名称、说明和指令均不能为空")
        return value


class AssistantCustomSkillUpdate(AssistantCustomSkillIn):
    expected_revision: int = Field(ge=1)


class AssistantCustomSkillOut(AssistantSkillOut):
    revision: int


class AssistantCustomSkillDetail(AssistantCustomSkillOut):
    instructions: str


class AssistantExpertOut(BaseModel):
    user_id: int
    name: str
    specialty: str
    bio: str
    tags: list[str]
    profile_source: str
    joined: bool
    is_self: bool


class AssistantMemberOut(BaseModel):
    user_id: int
    name: str
    role: Literal["owner", "contributor"]
    active: bool
    is_self: bool
