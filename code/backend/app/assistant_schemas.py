"""AI 助手的独立通信契约。

这些 DTO 与现有任务审核 DTO 分开，方便前端工作台或其他 Agent 通过稳定的
JSON/SSE 协议接入，而不需要依赖某个具体的页面实现。
"""
from __future__ import annotations

import datetime as dt

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


class AssistantMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    status: str
    steps: list = Field(default_factory=list)
    citations: list = Field(default_factory=list)
    created_at: dt.datetime


class AssistantSessionDetail(AssistantSessionOut):
    messages: list[AssistantMessageOut] = Field(default_factory=list)


class AssistantChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    task_code: str | None = Field(default=None, max_length=64)

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
