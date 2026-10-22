"""Assistant resource access, durable public events and a single AI run per room.

Database constraints coordinate admission. The worker is local to this API process;
on a process crash expired runs fail explicitly, rather than silently rerunning AI.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import models
from .assistant_models import AssistantAudit, AssistantEvent, AssistantMember, AssistantMessageAuthor, AssistantRun
from .assistant_service import task_for_user
from .assistant_contract import ASSISTANT_RUN_EXPIRY_SECONDS, ASSISTANT_RUN_TIMEOUT_SECONDS

log = logging.getLogger(__name__)
workers: dict[str, asyncio.Task] = {}


def session_for_user(db: Session, session_id: int, user: models.User) -> models.AssistantSession:
    db.refresh(user)
    session = db.get(models.AssistantSession, session_id)
    if not user.is_active or user.role != models.Role.REVIEWER or not session:
        raise HTTPException(404, "助手会话不存在或无权访问")
    if session.user_id != user.id:
        member = db.query(AssistantMember).populate_existing().filter_by(session_id=session_id, user_id=user.id).first()
        if not member or user.role != models.Role.REVIEWER:
            raise HTTPException(404, "助手会话不存在或无权访问")
    if session.task_code and not task_for_user(db, user, session.task_code):
        raise HTTPException(404, "任务不存在或无权访问")
    if user.role != models.Role.REVIEWER and is_shared(db, session.id):
        raise HTTPException(404, "助手会话不存在或无权访问")
    return session


def is_shared(db: Session, session_id: int) -> bool:
    return db.query(AssistantMember).filter_by(session_id=session_id).first() is not None


def visible_sessions(db: Session, user: models.User):
    joined = db.query(AssistantMember.session_id).filter_by(user_id=user.id)
    rows = db.query(models.AssistantSession).filter(or_(
        models.AssistantSession.user_id == user.id,
        models.AssistantSession.id.in_(joined) if user.role == models.Role.REVIEWER else False,
    )).order_by(models.AssistantSession.updated_at.desc()).all()
    return [row for row in rows
            if (not row.task_code or task_for_user(db, user, row.task_code))
            and (user.role == models.Role.REVIEWER or not is_shared(db, row.id))]


def author_out(db: Session, message: models.AssistantMessage) -> dict:
    identity = db.get(AssistantMessageAuthor, message.id)
    if identity:
        return {"author_id": identity.user_id, "author_name": identity.display_name, "run_id": identity.run_id}
    # Before collaboration existed, every user message belonged to its owner.
    owner = db.get(models.User, message.session.user_id) if message.role == "user" else None
    return {"author_id": owner.id if owner else None, "author_name": owner.display_name if owner else "慧眼助手", "run_id": None}


def public_event(db: Session, session_id: int, payload: dict, run_id: str | None = None):
    row = AssistantEvent(session_id=session_id, run_id=run_id, payload=payload)
    db.add(row)
    db.flush()
    return row


def commit_run_event(db: Session, run: AssistantRun, payload: dict):
    """Commit the final message, events and terminal run as one DB transaction.

    stream_assistant leaves its final message pending for this caller. Neither
    history readers nor event/result readers may observe a partial completion.
    """
    public_event(db, run.session_id, payload, run.id)
    if payload.get('event') == 'message_end':
        run.status = 'completed'
        run.active_session_id = None
        public_event(db, run.session_id, {'event': 'run_end', 'status': 'completed'}, run.id)
    db.commit()


def expire_runs(db: Session, session_id: int):
    rows = db.query(AssistantRun).filter(
        AssistantRun.active_session_id == session_id, AssistantRun.expires_at < datetime.now(timezone.utc)
    ).all()
    for run in rows:
        run.status = "error"
        run.active_session_id = None
        public_event(db, session_id, {"event": "error", "message": "运行超时或服务已重启，请重新发起问题。"}, run.id)
        public_event(db, session_id, {"event": "run_end", "status": "error"}, run.id)
    if rows:
        db.commit()


def admit_run(db: Session, user: models.User, session: models.AssistantSession, payload) -> tuple[AssistantRun, bool]:
    expire_runs(db, session.id)
    client_id = payload.client_message_id or str(uuid4())
    digest = hashlib.sha256(json.dumps({
        "content": payload.content, "task_code": session.task_code, "skill_id": payload.skill_id,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = db.query(AssistantRun).filter_by(session_id=session.id, user_id=user.id, client_message_id=client_id).first()
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(409, "同一请求标识不能用于不同消息")
        return existing, False
    active = db.query(AssistantRun).filter_by(active_session_id=session.id).first()
    if active:
        # Another transaction may admit this same request between our first
        # lookup and the active-slot query. It is a retry, not a busy conflict.
        if (active.user_id == user.id and active.client_message_id == client_id
                and active.request_hash == digest):
            return active, False
        raise HTTPException(409, "当前会话的 AI 正在工作；可继续发送讨论消息，稍后再提问")
    run = AssistantRun(
        id=str(uuid4()), session_id=session.id, user_id=user.id, client_message_id=client_id,
        request_hash=digest, active_session_id=session.id, status="running",
        # Enhanced RAG retrieval may use its full 240s budget before the model
        # call; leave time for model completion and event persistence.
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ASSISTANT_RUN_EXPIRY_SECONDS),
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(AssistantRun).filter_by(session_id=session.id, user_id=user.id, client_message_id=client_id).first()
        if existing and existing.request_hash == digest:
            return existing, False
        raise HTTPException(409, "当前会话已有运行，请刷新后重试")
    db.refresh(run)
    return run, True


def run_out(run: AssistantRun) -> dict:
    return {"id": run.id, "status": run.status, "session_id": run.session_id, "user_id": run.user_id,
            "client_message_id": run.client_message_id}


async def execute_run(factory, run_id: str, content: str, skill_id: str | None):
    from .assistant_service import stream_assistant
    terminal = "error"
    with factory() as db:
        run = db.get(AssistantRun, run_id)
        if not run or run.status != "running":
            return
        user = db.get(models.User, run.user_id)
        try:
            session = session_for_user(db, run.session_id, user)
            # wait_for bounds both model access and retrieval; no immortal room lock.
            async with asyncio.timeout(ASSISTANT_RUN_TIMEOUT_SECONDS):
                async for event in stream_assistant(db, user, session, content, session.task_code, skill_id, run_id=run.id):
                    db.refresh(run)
                    if run.status != "running":
                        terminal = run.status
                        break
                    session_for_user(db, session.id, user)
                    commit_run_event(db, run, event)
                    if event.get("event") == "message_end":
                        terminal = "completed"
                        break
        except asyncio.CancelledError:
            terminal = "cancelled"
            db.rollback()
        except Exception:
            db.rollback()
            log.exception("Assistant collaboration run failed")
            public_event(db, run.session_id, {"event": "error", "message": "助手运行未完成，请检查模型或知识库状态后重试。"}, run.id)
        finally:
            db.refresh(run)
            if run.status != "running":
                terminal = run.status
            if run.active_session_id is not None:
                run.status = terminal
                run.active_session_id = None
                public_event(db, run.session_id, {"event": "run_end", "status": terminal}, run.id)
                db.commit()


def launch_run(db: Session, run: AssistantRun, content: str, skill_id: str | None):
    # New sessions per worker: never retain the HTTP dependency's DB session.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    task = asyncio.create_task(execute_run(factory, run.id, content, skill_id))
    workers[run.id] = task
    def finished(done):
        workers.pop(run.id, None)
        # Cancellation may happen before the coroutine starts, so its finally
        # block is not guaranteed to run. Release the persisted slot here too.
        with factory() as cleanup:
            stored = cleanup.get(AssistantRun, run.id)
            if stored and stored.active_session_id is not None:
                stored.status = "cancelled" if done.cancelled() else "error"
                stored.active_session_id = None
                public_event(cleanup, stored.session_id, {"event": "run_end", "status": stored.status}, stored.id)
                cleanup.commit()
        if not done.cancelled() and done.exception():
            log.error("Assistant worker exited unexpectedly; the persisted run will expire", exc_info=done.exception())
    task.add_done_callback(finished)


def add_discussion(db: Session, session: models.AssistantSession, user: models.User, content: str):
    message = models.AssistantMessage(session_id=session.id, role="user", content=content)
    db.add(message)
    db.flush()
    db.add(AssistantMessageAuthor(message_id=message.id, user_id=user.id, display_name=user.display_name))
    session.updated_at = datetime.now(timezone.utc)
    db.flush()
    return message
