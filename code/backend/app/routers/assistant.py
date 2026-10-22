"""AI 助手 API：用户级会话、SSE 流式事件和任务上下文。"""
from __future__ import annotations

import json
import logging
import httpx

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
    AssistantSkillOut,
)
from ..assistant_service import _safe_final_answer, sdk_configured, stream_assistant, task_for_user
from ..assistant_skills import get_skill, list_skills
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


def _message_out(message: models.AssistantMessage) -> AssistantMessageOut:
    result = AssistantMessageOut.model_validate(message, from_attributes=True)
    if message.role == "assistant" and _safe_final_answer(message.content) is None:
        return result.model_copy(update={
            "content": "这条历史答复包含不可展示的内部过程，已隐藏。请重新发送问题以获取审核辅助答复。"
        })
    return result


@router.get("/capabilities", response_model=AssistantCapabilities)
async def capabilities(user: models.User = Depends(get_current_user)):
    del user
    runtime_available = False
    runtime_model = None
    rag_available = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5)) as client:
        if settings.ASSISTANT_RUNTIME_URL:
            try:
                response = await client.get(f"{settings.ASSISTANT_RUNTIME_URL.rstrip('/')}/healthz")
                runtime_info = response.json()
                runtime_available = (
                    response.is_success
                    and isinstance(runtime_info, dict)
                    and runtime_info.get("configured") is True
                )
                if runtime_available and isinstance(runtime_info.get("model"), str):
                    runtime_model = runtime_info["model"]
            except (httpx.HTTPError, ValueError):
                runtime_available = False
        if settings.RAG_BASE_URL:
            try:
                response = await client.get(f"{settings.RAG_BASE_URL.rstrip('/')}/health")
                health = response.json()
                rag_available = response.is_success and health.get("status") == "ok"
            except (httpx.HTTPError, ValueError):
                rag_available = False

    assistant_available = sdk_configured() and runtime_available
    if not sdk_configured():
        message = "OpenCode runtime 或汇丰模型 API 配置未完成"
    elif not runtime_available:
        message = "OpenCode runtime 未就绪，请检查运行时和汇丰模型配置"
    elif settings.RAG_BASE_URL and not rag_available:
        message = "助手可用；知识库暂不可用，本次仅能使用当前任务证据"
    elif rag_available:
        message = "OpenCode runtime、汇丰模型 API 与知识库均可用"
    else:
        message = "OpenCode runtime 与汇丰模型 API 可用，知识库未配置"
    return AssistantCapabilities(
        sdk="opencode-sdk@2.0.32",
        configured=assistant_available,
        model=runtime_model,
        rag_available=rag_available,
        message=message,
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


@router.get("/skills", response_model=list[AssistantSkillOut])
def skills(user: models.User = Depends(get_current_user)):
    del user
    fields = ("id", "name", "desc", "version", "owner", "license", "permissions")
    return [{key: skill[key] for key in fields} for skill in list_skills()]


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
        messages=[_message_out(item) for item in session.messages],
    )


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = _session_for_user(db, session_id, user)
    db.delete(session)
    db.commit()
    return {"deleted": True}


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
    if payload.skill_id and not get_skill(payload.skill_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="审核技能不存在或未发布")

    async def event_stream():
        try:
            async for item in stream_assistant(
                db, user, session, payload.content, task_code, payload.skill_id
            ):
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
