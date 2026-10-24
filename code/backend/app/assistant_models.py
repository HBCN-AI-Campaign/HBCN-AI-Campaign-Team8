"""Additive assistant tables. Existing task/user/message columns are untouched."""
import datetime as dt

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import _now
from .assistant_timestamps import AssistantUTCDateTime


class AssistantMember(Base):
    __tablename__ = "assistant_members"
    session_id: Mapped[int] = mapped_column(ForeignKey("assistant_sessions.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)


class AssistantExpertProfile(Base):
    __tablename__ = "assistant_expert_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    specialty: Mapped[str] = mapped_column(String(128), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)


class AssistantRun(Base):
    __tablename__ = "assistant_runs"
    __table_args__ = (UniqueConstraint("session_id", "user_id", "client_message_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assistant_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_message_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    # NULL for terminal runs. A database unique constraint coordinates workers.
    active_session_id: Mapped[int | None] = mapped_column(unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)
    expires_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime())


class AssistantMessageAuthor(Base):
    __tablename__ = "assistant_message_authors"
    message_id: Mapped[int] = mapped_column(ForeignKey("assistant_messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AssistantEvent(Base):
    __tablename__ = "assistant_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assistant_sessions.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)


class AssistantAudit(Base):
    __tablename__ = "assistant_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assistant_sessions.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)


class AssistantUserSkill(Base):
    __tablename__ = "assistant_user_skills"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)


class AssistantCustomSkill(Base):
    """Personal instruction-only skills; they never execute code or grant tools."""
    __tablename__ = "assistant_custom_skills"
    __table_args__ = (Index("ix_assistant_custom_skills_user_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(AssistantUTCDateTime(), default=_now, onupdate=_now)
