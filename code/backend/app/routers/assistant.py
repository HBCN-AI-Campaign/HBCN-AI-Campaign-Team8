"""AI 助手 API：用户级会话、SSE 流式事件和任务上下文。"""
from __future__ import annotations

import json
import logging
import httpx
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import func

from .. import models
from ..assistant_schemas import (
    AssistantCapabilities,
    AssistantChatIn,
    AssistantMessageOut,
    AssistantSessionCreate,
    AssistantSessionDetail,
    AssistantSessionOut,
    AssistantSkillOut,
    AssistantRunDetail,
)
from ..assistant_service import _safe_final_answer, sdk_configured, stream_assistant, task_for_user
from ..assistant_readiness import rag_readiness, runtime_readiness, runtime_problem
from ..assistant_skills import get_skill_for_user, list_available_skills
from ..config import settings
from ..database import get_db
from ..security import get_current_user, require_role
from ..assistant_collaboration import (admit_run, author_out, expire_runs, is_shared, public_event,
    session_for_user, visible_sessions, run_out, commit_run_event)
from ..assistant_models import AssistantAudit, AssistantEvent, AssistantMember, AssistantMessageAuthor, AssistantRun
from ..assistant_contract import (ASSISTANT_RUN_TIMEOUT_SECONDS, CONTRACT_VERSION,
    AssistantContractOut, AssistantHTTPError, contract_info)
from .assistant_collaboration import router as collaboration_router

router = APIRouter(
    tags=["assistant"],
    dependencies=[Depends(require_role(models.Role.REVIEWER))],
    responses={code: {"model": AssistantHTTPError} for code in (401, 403, 404, 409)},
)
logger = logging.getLogger(__name__)
router.include_router(collaboration_router)


@router.get("/contract", response_model=AssistantContractOut)
def contract(user: models.User = Depends(get_current_user)):
    del user
    return contract_info()


def _session_for_user(db: Session, session_id: int, user: models.User) -> models.AssistantSession:
    return session_for_user(db, session_id, user)


def _session_out(session: models.AssistantSession, db: Session, user: models.User) -> AssistantSessionOut:
    return AssistantSessionOut(
        id=session.id,
        title=session.title,
        task_code=session.task_code,
        message_count=len(session.messages),
        updated_at=session.updated_at,
        owner_id=session.user_id,
        shared=is_shared(db, session.id),
        can_manage=session.user_id == user.id,
    )


def _message_out(message: models.AssistantMessage, db: Session) -> AssistantMessageOut:
    result = AssistantMessageOut.model_validate(message, from_attributes=True)
    result = result.model_copy(update=author_out(db, message))
    if message.role == "assistant" and _safe_final_answer(message.content) is None:
        return result.model_copy(update={
            "content": "这条历史答复包含不可展示的内部过程，已隐藏。请重新发送问题以获取审核辅助答复。"
        })
    return result


@router.get("/sessions/{session_id}/runs/{run_id}", response_model=AssistantRunDetail)
def get_run(session_id: int, run_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session_for_user(db, session_id, user)
    expire_runs(db, session_id)
    run = db.get(AssistantRun, run_id)
    if not run or run.session_id != session_id:
        raise HTTPException(404, "运行不存在或无权访问")
    message = None
    if run.status == "completed":
        stored = db.query(models.AssistantMessage).join(
            AssistantMessageAuthor, models.AssistantMessage.id == AssistantMessageAuthor.message_id,
        ).filter(
            AssistantMessageAuthor.run_id == run.id,
            models.AssistantMessage.session_id == session_id,
            models.AssistantMessage.role == "assistant",
        ).order_by(models.AssistantMessage.id.desc()).first()
        if stored:
            message = _message_out(stored, db)
    return {**run_out(run), "message": message}


@router.get("/capabilities", response_model=AssistantCapabilities)
async def capabilities(user: models.User = Depends(get_current_user)):
    del user
    runtime_available = False
    runtime_model = None
    rag_available = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5)) as client:
        runtime_info = await runtime_readiness(client, settings.ASSISTANT_RUNTIME_URL, settings.ASSISTANT_RUNTIME_TOKEN)
        runtime_available = runtime_info["ready"]
        runtime_model = runtime_info["model"]
        rag_info = await rag_readiness(client, settings.RAG_BASE_URL, settings.RAG_SERVICE_TOKEN)
        rag_available = rag_info['ready']

    assistant_available = sdk_configured() and runtime_available
    if not sdk_configured():
        message = "OpenCode runtime 或汇丰模型 API 配置未完成"
    elif not runtime_available:
        message = runtime_problem(runtime_info['code'])
    elif settings.RAG_BASE_URL and not rag_available:
        if rag_info.get('code') == 'contract_mismatch':
            message = "助手可用；知识库 API 版本不兼容，需使用 RAG 契约 1.2.0 或更新的 1.x 版本"
        elif rag_info.get('code') == 'contract_missing':
            message = "助手可用；知识库未返回受支持的 API 契约版本，检索结果可能受限"
        else:
            message = "助手可用；知识库尚未通过鉴权就绪检查，检索结果可能受限"
    elif rag_available:
        message = "助手内部服务鉴权与模型配置就绪；知识库在线，实际问答以调用结果为准"
    else:
        message = "助手内部服务鉴权与模型配置就绪；知识库未配置，实际问答以调用结果为准"
    return AssistantCapabilities(
        sdk="opencode-sdk@2.0.32",
        configured=assistant_available,
        model=runtime_model,
        rag_available=rag_available,
        message=message,
    )


@router.get("/sessions", response_model=list[AssistantSessionOut])
def list_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_session_out(session, db, user) for session in visible_sessions(db, user)]


@router.get("/skills", response_model=list[AssistantSkillOut])
def skills(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    fields = ("id", "name", "desc", "version", "owner", "license", "permissions",
              "is_custom", "editable", "revision")
    return [{key: skill.get(key, False if key in {"is_custom", "editable"} else None)
             for key in fields} for skill in list_available_skills(db, user.id)]


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
    return _session_out(session, db, user)


@router.get("/sessions/{session_id}", response_model=AssistantSessionDetail)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = _session_for_user(db, session_id, user)
    expire_runs(db, session_id)
    # Read cursor BEFORE messages: concurrent events after this point will be
    # replayed and deduplicated by message id, never silently skipped.
    cursor = db.query(func.max(AssistantEvent.id)).filter_by(session_id=session_id).scalar() or 0
    active = db.query(AssistantRun).filter_by(active_session_id=session_id).first()
    return AssistantSessionDetail(
        **_session_out(session, db, user).model_dump(),
        messages=[_message_out(item, db) for item in session.messages],
        event_cursor=cursor, active_run=run_out(active) if active else None,
    )


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = _session_for_user(db, session_id, user)
    if session.user_id != user.id:
        raise HTTPException(403, detail="仅会话创建者可删除会话")
    if db.query(AssistantRun).filter_by(active_session_id=session_id).first():
        raise HTTPException(409, detail="请先停止当前 AI 运行再删除会话")
    # Explicit cleanup also works with SQLite deployments without FK cascades.
    ids = db.query(models.AssistantMessage.id).filter_by(session_id=session_id)
    db.query(AssistantMessageAuthor).filter(AssistantMessageAuthor.message_id.in_(ids)).delete(synchronize_session=False)
    for table in (AssistantEvent, AssistantAudit, AssistantMember, AssistantRun):
        db.query(table).filter_by(session_id=session_id).delete(synchronize_session=False)
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
    if is_shared(db, session_id):
        raise HTTPException(409, detail="共享会话请使用 runs 和 events 接口，避免断线重复调用")
    if session.task_code and payload.task_code and payload.task_code != session.task_code:
        raise HTTPException(409, detail="会话任务固定，请新建会话切换任务")
    task_code = payload.task_code or session.task_code
    if task_code and not task_for_user(db, user, task_code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问")
    if payload.skill_id and not get_skill_for_user(db, user.id, payload.skill_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="审核技能不存在或未发布")
    run, created = admit_run(db, user, session, payload)
    if not created:
        raise HTTPException(409, detail="该请求已处理，请通过 events 接口读取结果")
    # FastAPI may close its dependency before StreamingResponse consumes the
    # generator. Capture scalar identities only, and own a DB session for the
    # entire stream, matching the collaboration worker lifecycle.
    actor_id, run_id = user.id, run.id
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    async def event_stream():
        with factory() as stream_db:
            active = stream_db.get(AssistantRun, run_id)
            if active is None:
                return
            try:
                actor = stream_db.get(models.User, actor_id)
                room = session_for_user(stream_db, session_id, actor)
                if active.status != "running":
                    raise HTTPException(409, "运行已经结束")
                async with asyncio.timeout(ASSISTANT_RUN_TIMEOUT_SECONDS):
                    async for item in stream_assistant(
                        stream_db, actor, room, payload.content, task_code, payload.skill_id, run_id=run_id
                    ):
                        stream_db.refresh(active)
                        if active.status != "running":
                            break
                        session_for_user(stream_db, session_id, actor)
                        commit_run_event(stream_db, active, item)
                        event = item.get("event", "message")
                        yield f"event: {event}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                        if event == "message_end":
                            terminal = {"event": "run_end", "run_id": run_id, "status": "completed"}
                            yield f"event: run_end\ndata: {json.dumps(terminal, ensure_ascii=False)}\n\n"
                            break
            except Exception:
                stream_db.rollback()
                logger.exception("Assistant stream failed")
                error = {"event": "error", "message": "助手请求失败，请稍后重试"}
                public_event(stream_db, session_id, error, run_id)
                stream_db.commit()
                yield f"event: error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"
            finally:
                if active.active_session_id is not None:
                    active.status = "error" if active.status == "running" else active.status
                    active.active_session_id = None
                    public_event(stream_db, session_id, {"event": "run_end", "status": active.status}, run_id)
                    stream_db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# One implementation, two mounts. New consumers never call the runtime API.
_implementation = router
router = APIRouter(prefix="/api/assistant")
router.include_router(_implementation)
router.include_router(_implementation, prefix="/v1")


def public_openapi() -> dict:
    """Export only V1, with no app settings or credentials."""
    return get_openapi(
        title="Huiyan Assistant API", version=CONTRACT_VERSION,
        routes=[route for route in router.routes if route.path.startswith("/api/assistant/v1/")],
    )
