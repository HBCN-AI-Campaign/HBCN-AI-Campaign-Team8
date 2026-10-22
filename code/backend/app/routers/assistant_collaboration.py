"""Resource-scoped collaboration endpoints; no alternate authentication stack."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .. import models
from ..assistant_collaboration import (
    add_discussion, admit_run, author_out, expire_runs, launch_run, public_event,
    run_out, session_for_user, workers,
)
from ..assistant_models import AssistantAudit, AssistantEvent, AssistantExpertProfile, AssistantMember, AssistantRun, AssistantUserSkill
from ..assistant_schemas import (AssistantChatIn, AssistantMessageOut, AssistantRunOut,
    AssistantEventPage, AssistantExpertOut, AssistantMemberOut, AssistantLibrarySkillOut)
from ..assistant_service import task_for_user
from ..assistant_skills import get_skill, list_skills
from ..database import get_db
from ..security import get_current_user

router = APIRouter()


@router.get("/skill-library", response_model=list[AssistantLibrarySkillOut])
def skill_library(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    installed = {row.skill_id: row for row in db.query(AssistantUserSkill).filter_by(user_id=user.id)}
    result = []
    for skill in list_skills():
        digest = hashlib.sha256(skill['instructions'].encode()).hexdigest()
        saved = installed.get(skill['id'])
        result.append({**{key: value for key, value in skill.items() if key != 'instructions'},
                       "source": "项目审核目录 · 随版本发布", "installed": saved is not None,
                       "update_available": bool(saved and (saved.version != skill['version'] or saved.content_hash != digest))})
    return result


@router.put("/skill-library/{skill_id}")
def install_skill(skill_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "技能不存在或未通过项目发布审核")
    saved = db.get(AssistantUserSkill, (user.id, skill_id)) or AssistantUserSkill(user_id=user.id, skill_id=skill_id)
    saved.version = skill['version']
    saved.content_hash = hashlib.sha256(skill['instructions'].encode()).hexdigest()
    db.add(saved); db.commit()
    return {"installed": True, "version": saved.version}


@router.delete("/skill-library/{skill_id}")
def uninstall_skill(skill_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    saved = db.get(AssistantUserSkill, (user.id, skill_id))
    if saved:
        db.delete(saved); db.commit()
    return {"installed": False}


def owner_session(db, user, session_id):
    session = session_for_user(db, session_id, user)
    if session.user_id != user.id or user.role != models.Role.REVIEWER:
        raise HTTPException(403, "仅会话创建审核人员可管理成员")
    return session


class MemberIn(BaseModel):
    user_id: int = Field(gt=0)


class ProfileIn(BaseModel):
    specialty: str = Field(default="", max_length=128)
    bio: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=8)


@router.get("/experts/me", response_model=ProfileIn)
def my_profile(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if user.role != models.Role.REVIEWER:
        raise HTTPException(403, "专家目录仅面向审核人员")
    row = db.get(AssistantExpertProfile, user.id)
    return {"specialty": row.specialty, "bio": row.bio, "tags": row.tags} if row else ProfileIn()


@router.put("/experts/me")
def update_profile(payload: ProfileIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if user.role != models.Role.REVIEWER:
        raise HTTPException(403, "专家目录仅面向审核人员")
    row = db.get(AssistantExpertProfile, user.id) or AssistantExpertProfile(user_id=user.id)
    row.specialty = payload.specialty.strip()
    row.bio = payload.bio.strip()
    row.tags = list(dict.fromkeys(tag.strip()[:40] for tag in payload.tags if tag.strip()))
    db.add(row)
    db.commit()
    return {"saved": True}


@router.get("/experts", response_model=list[AssistantExpertOut])
def experts(session_id: int | None = None, q: str = Query(default="", max_length=128),
            db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if user.role != models.Role.REVIEWER:
        raise HTTPException(403, "专家目录仅面向审核人员")
    session = session_for_user(db, session_id, user) if session_id else None
    candidates = db.query(models.User, AssistantExpertProfile).outerjoin(
        AssistantExpertProfile, models.User.id == AssistantExpertProfile.user_id
    ).filter(models.User.is_active.is_(True), models.User.role == models.Role.REVIEWER).order_by(models.User.id).all()
    result = []
    needle = q.strip().casefold()
    for target, profile in candidates:
        if session and session.task_code and not task_for_user(db, target, session.task_code):
            continue
        tags = profile.tags if profile else []
        specialty = profile.specialty if profile else ""
        bio = profile.bio if profile else ""
        searchable = " ".join([target.display_name, specialty, bio, *tags]).casefold()
        if needle and needle not in searchable:
            continue
        joined = bool(session and (target.id == session.user_id or db.get(AssistantMember, (session.id, target.id))))
        result.append({"user_id": target.id, "name": target.display_name, "specialty": specialty,
                       "bio": bio, "tags": tags, "profile_source": "本人维护" if profile else "未填写专业资料",
                       "joined": joined, "is_self": target.id == user.id})
        if len(result) >= 50:
            break
    return result


@router.get("/sessions/{session_id}/members", response_model=list[AssistantMemberOut])
def members(session_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = session_for_user(db, session_id, user)
    ids = [session.user_id, *[row.user_id for row in db.query(AssistantMember).filter_by(session_id=session_id)]]
    people = db.query(models.User).filter(models.User.id.in_(ids)).order_by(models.User.id).all()
    return [{"user_id": person.id, "name": person.display_name,
             "role": "owner" if person.id == session.user_id else "contributor",
             "active": person.is_active, "is_self": person.id == user.id} for person in people]


@router.post("/sessions/{session_id}/members", status_code=201)
def invite(session_id: int, payload: MemberIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = owner_session(db, user, session_id)
    if not session.task_code:
        raise HTTPException(409, "请先创建关联审核任务的会话，再邀请专家共享材料")
    target = db.get(models.User, payload.user_id)
    if not target or not target.is_active or target.role != models.Role.REVIEWER or not task_for_user(db, target, session.task_code):
        raise HTTPException(404, "专家不存在或无权访问此任务")
    if target.id == session.user_id or db.get(AssistantMember, (session_id, target.id)):
        return {"joined": True}
    db.add(AssistantMember(session_id=session_id, user_id=target.id, invited_by=user.id))
    db.add(AssistantAudit(session_id=session_id, actor_id=user.id, subject_id=target.id, action="member_invited"))
    public_event(db, session_id, {"event": "members_changed"})
    session.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.get(AssistantMember, (session_id, target.id)):
            raise
    return {"joined": True}


@router.delete("/sessions/{session_id}/members/{user_id}")
async def revoke(session_id: int, user_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    owner_session(db, user, session_id)
    member = db.get(AssistantMember, (session_id, user_id))
    if not member:
        raise HTTPException(404, "会话成员不存在")
    db.delete(member)
    db.add(AssistantAudit(session_id=session_id, actor_id=user.id, subject_id=user_id, action="member_revoked"))
    public_event(db, session_id, {"event": "members_changed"})
    # A revoked initiator cannot keep a model run alive with historical authority.
    for run in db.query(AssistantRun).filter_by(active_session_id=session_id, user_id=user_id):
        run.status = "cancelled"
        task = workers.get(run.id)
        if task:
            task.cancel()
    db.commit()
    return {"removed": True}


@router.post("/sessions/{session_id}/messages", response_model=AssistantMessageOut, status_code=201)
def discuss(session_id: int, payload: AssistantChatIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = session_for_user(db, session_id, user)
    if payload.task_code and payload.task_code != session.task_code:
        raise HTTPException(409, "会话任务固定，请新建会话切换任务")
    message = add_discussion(db, session, user, payload.content)
    result = AssistantMessageOut.model_validate(message).model_copy(update=author_out(db, message))
    public_event(db, session_id, {"event": "discussion", "message": result.model_dump(mode="json")})
    db.commit()
    return result


@router.post("/sessions/{session_id}/runs", status_code=202, response_model=AssistantRunOut)
async def start_run(session_id: int, payload: AssistantChatIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = session_for_user(db, session_id, user)
    if payload.task_code and payload.task_code != session.task_code:
        raise HTTPException(409, "会话任务固定，请新建会话切换任务")
    if payload.skill_id and not get_skill(payload.skill_id):
        raise HTTPException(404, "审核技能不存在或未发布")
    run, created = admit_run(db, user, session, payload)
    if created:
        launch_run(db, run, payload.content, payload.skill_id)
    return run_out(run)


@router.get("/sessions/{session_id}/events", response_model=AssistantEventPage)
def events(session_id: int, after_id: int = Query(default=0, ge=0), run_id: str | None = None,
           db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session_for_user(db, session_id, user)
    expire_runs(db, session_id)
    query = db.query(AssistantEvent).filter(AssistantEvent.session_id == session_id, AssistantEvent.id > after_id)
    if run_id:
        query = query.filter(AssistantEvent.run_id == run_id)
    rows = query.order_by(AssistantEvent.id).limit(100).all()
    active = db.query(AssistantRun).filter_by(active_session_id=session_id).first()
    return {"events": [{"id": row.id, "run_id": row.run_id, **row.payload} for row in rows],
            "cursor": rows[-1].id if rows else after_id, "has_more": len(rows) == 100,
            "active_run": run_out(active) if active else None}


@router.post("/sessions/{session_id}/runs/{run_id}/cancel", response_model=AssistantRunOut)
async def cancel_run(session_id: int, run_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = session_for_user(db, session_id, user)
    run = db.get(AssistantRun, run_id)
    if not run or run.session_id != session_id:
        raise HTTPException(404, "运行不存在")
    if user.id not in (run.user_id, session.user_id):
        raise HTTPException(403, "仅发起者或会话创建者可停止运行")
    if run.status == "running":
        run.status = "cancelled"
        db.add(AssistantAudit(session_id=session_id, actor_id=user.id, action="run_cancelled"))
        task = workers.get(run.id)
        if task:
            task.cancel()
        else:
            run.active_session_id = None
            public_event(db, session_id, {"event": "run_end", "status": "cancelled"}, run.id)
        db.commit()
    return run_out(run)


@router.get("/sessions/{session_id}/audit")
def audit(session_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    owner_session(db, user, session_id)
    return [{"id": row.id, "actor_id": row.actor_id, "subject_id": row.subject_id,
             "action": row.action, "created_at": row.created_at} for row in db.query(AssistantAudit).filter_by(session_id=session_id).order_by(AssistantAudit.id.desc()).limit(100)]
