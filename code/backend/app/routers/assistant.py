"""AI 助手 API：用户级会话、SSE 流式事件和任务上下文。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models
from ..assistant_schemas import (
    AssistantCapabilities,
    AssistantChatIn,
    AssistantMessageOut,
    AssistantSessionCreate,
    AssistantSessionDetail,
    AssistantSessionOut,
)
from ..assistant_service import sdk_configured, stream_assistant, task_for_user
from ..config import settings
from ..database import get_db
from ..security import get_current_user

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


def _session_for_user(db: Session, session_id: int, user: models.User) -> models.AssistantSession:
    session = db.query(models.AssistantSession).filter_by(id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="助手会话不存在")
    return session


def _session_out(session: models.AssistantSession) -> AssistantSessionOut:
    return AssistantSessionOut(
        id=session.id,
        title=session.title,
        task_code=session.task_code,
        message_count=len(session.messages),
        updated_at=session.updated_at,
    )


@router.get("/capabilities", response_model=AssistantCapabilities)
def capabilities(user: models.User = Depends(get_current_user)):
    del user
    return AssistantCapabilities(
        sdk="openai-agents-python",
        configured=sdk_configured(),
        model=settings.AI_MODEL or None,
        rag_available=bool(getattr(settings, "RAG_BASE_URL", "")),
        message=("Agent SDK 已配置，可调用汇丰百炼 API" if sdk_configured() else "未配置模型 API，当前使用本地演示模式"),
    )


@router.get("/sessions", response_model=list[AssistantSessionOut])
def list_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    sessions = (
        db.query(models.AssistantSession)
        .filter_by(user_id=user.id)
        .order_by(models.AssistantSession.updated_at.desc())
        .all()
    )
    return [_session_out(session) for session in sessions]


@router.post("/sessions", response_model=AssistantSessionOut, status_code=201)
def create_session(
    payload: AssistantSessionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.task_code and not task_for_user(db, user, payload.task_code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问")
    session = models.AssistantSession(
        user_id=user.id,
        title=payload.title.strip()[:128] or "新会话",
        task_code=payload.task_code,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_out(session)


@router.get("/sessions/{session_id}", response_model=AssistantSessionDetail)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = _session_for_user(db, session_id, user)
    return AssistantSessionDetail(
        **_session_out(session).model_dump(),
        messages=[AssistantMessageOut.model_validate(item, from_attributes=True) for item in session.messages],
    )


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: int,
    payload: AssistantChatIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = _session_for_user(db, session_id, user)
    # StreamingResponse consumes the generator after the endpoint returns. Load the
    # relationship now so the generator does not trigger a detached lazy load.
    _ = list(session.messages)
    task_code = payload.task_code or session.task_code
    if task_code and not task_for_user(db, user, task_code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问")

    async def event_stream():
        try:
            async for item in stream_assistant(db, user, session, payload.content, task_code):
                event = item.get("event", "message")
                yield f"event: {event}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        except Exception:
            db.rollback()
            logger.exception("Assistant stream failed")
            yield f"event: error\ndata: {json.dumps({'event': 'error', 'message': '助手请求失败，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
