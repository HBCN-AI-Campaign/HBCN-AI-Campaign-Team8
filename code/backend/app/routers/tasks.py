"""任务路由：创建任务、触发核对、查询结果。体现权限雏形。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..models import Role, TaskStatus, User
from ..parse_agent import parse_files
from ..review_agent import build_session
from ..rule_engine import run_all, summarize
from ..schemas import (
    AIResolveIn,
    AIResolveOut,
    AISession,
    CheckResultOut,
    DashboardStats,
    ParseResult,
    RunSummary,
    StatusAction,
    SupplementIn,
    TaskCreate,
    TaskDetail,
    TaskOut,
)
from ..security import get_current_user, require_role


def _task_out(task: "models.ReviewTask") -> TaskOut:
    """统一构建 TaskOut DTO，避免各处重复。"""
    return TaskOut(
        id=task.id, task_code=task.task_code, borrower=task.borrower,
        drawdown_currency=task.drawdown_currency,
        drawdown_amount=float(task.drawdown_amount), status=task.status.value,
        created_at=task.created_at,
        review_comment=task.review_comment,
        supplement_note=task.supplement_note,
    )

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/parse", response_model=ParseResult)
async def parse_documents(
    files: list[UploadFile] = File(...),
    # 仅业务经办人可上传解析
    user: User = Depends(require_role(Role.OPERATOR)),
):
    """上传材料 → 调用文件解析 Agent（当前为 mock）→ 返回 8 类单据识别字段。

    传输方式：标准 multipart/form-data，前端把 N 个文件以同名字段 `files`
    依次 append，后端 `list[UploadFile]` 自动收成文件数组（数量不限）。

    真实环境这里会把文件二进制转发给 OCR/LLM 解析服务；
    当前为 Mock——内容虽不参与识别，但会按批次落盘，使「定位原文」
    预览到的就是用户本次真实上传的 PDF，而非仓库自带样本。
    """
    import uuid
    from pathlib import Path

    from ..config import UPLOAD_DIR as _UPLOAD_DIR

    batch_id = uuid.uuid4().hex[:12]
    batch_dir = Path(_UPLOAD_DIR) / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 落盘：保存每个上传文件，记录供预览的相对 URL（/uploads/<批次>/<文件名>）
    saved: list[dict] = []
    for i, f in enumerate(files):
        raw_name = f.filename or f"未命名_{i + 1}.pdf"
        # 清洗文件名，避免路径穿越
        safe_name = Path(raw_name).name or f"file_{i + 1}.pdf"
        dest = batch_dir / safe_name
        content = await f.read()
        dest.write_bytes(content)
        saved.append({
            "filename": raw_name,
            "pdf_url": f"uploads/{batch_id}/{safe_name}",
        })

    if not saved:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="未收到任何文件")
    return parse_files(saved)


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(models.ReviewTask)
    # 经办人只统计自己提交的任务；审核人统计全部
    if user.role == Role.OPERATOR:
        q = q.filter_by(submitted_by=user.id)
    return DashboardStats(
        total_tasks=q.count(),
        created=q.filter_by(status=TaskStatus.CREATED).count(),
        reviewing=q.filter_by(status=TaskStatus.REVIEWING).count(),
        need_supplement=q.filter_by(status=TaskStatus.NEED_SUPPLEMENT).count(),
        supplemented=q.filter_by(status=TaskStatus.SUPPLEMENTED).count(),
        completed=q.filter_by(status=TaskStatus.COMPLETED).count(),
    )


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    # 仅业务经办人可创建任务
    user: User = Depends(require_role(Role.OPERATOR)),
):
    if db.query(models.ReviewTask).filter_by(task_code=payload.task_code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="任务编号已存在")

    task = models.ReviewTask(
        task_code=payload.task_code,
        borrower=payload.borrower,
        drawdown_currency=payload.drawdown_currency,
        drawdown_amount=payload.drawdown_amount,
        submitted_by=user.id,
    )
    for d in payload.documents:
        task.documents.append(
            models.Document(
                doc_code=d.doc_code, type_code=d.type_code, fields=d.fields,
                pdf_file=d.pdf_file, field_sources=d.field_sources,
            )
        )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(models.ReviewTask)
    # mine=true：仅返回当前经办人提交的任务（工作台 tab 筛选用）
    if mine:
        q = q.filter_by(submitted_by=user.id)
    tasks = q.order_by(models.ReviewTask.id.desc()).all()
    return [_task_out(t) for t in tasks]


def _get_task(db: Session, task_code: str) -> models.ReviewTask:
    task = db.query(models.ReviewTask).filter_by(task_code=task_code).first()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


def _handoff_meta(task: models.ReviewTask, rule_id: str) -> dict | None:
    """按 rule_id 取专项审核项（规则引擎 [专项] 移交）的元数据，用于首次处置时补建记录。"""
    from ..rule_engine import run_all
    from ..rule_engine.rules import HANDOFF
    for r in run_all(task.documents):
        if r.rule_id == rule_id and r.status.value == "skip" and (r.why or "").startswith(HANDOFF):
            return {
                "rule_id": r.rule_id, "rule_name": r.rule_name, "dimension": r.dimension,
                "why": (r.why or "").removeprefix(HANDOFF).strip(), "suggestion": r.suggestion or "",
            }
    return None


@router.get("/{task_code}", response_model=TaskDetail)
def get_task_detail(
    task_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    task = _get_task(db, task_code)
    counts = {"pass": 0, "fail": 0, "warn": 0}
    for r in task.results:
        key = r.status.value if hasattr(r.status, "value") else str(r.status)
        if key in counts:
            counts[key] += 1
    return TaskDetail(
        id=task.id, task_code=task.task_code, borrower=task.borrower,
        drawdown_currency=task.drawdown_currency,
        drawdown_amount=float(task.drawdown_amount), status=task.status.value,
        created_at=task.created_at,
        review_comment=task.review_comment,
        supplement_note=task.supplement_note,
        documents=[
            {"id": d.id, "doc_code": d.doc_code,
             "type_code": d.type_code.value if hasattr(d.type_code, "value") else str(d.type_code),
             "fields": d.fields,
             "pdf_file": d.pdf_file,
             "field_sources": d.field_sources or {}}
            for d in task.documents
        ],
        result_counts=counts,
    )


@router.post("/{task_code}/run", response_model=RunSummary)
def run_checks(
    task_code: str,
    db: Session = Depends(get_db),
    # 审核人员触发核对
    user: User = Depends(require_role(Role.REVIEWER)),
):
    task = _get_task(db, task_code)

    # 清空历史结果后重跑（幂等）
    db.query(models.CheckResult).filter_by(task_id=task.id).delete()

    results = run_all(task.documents)
    persisted = []
    for r in results:
        if r.status.value == "skip":
            continue  # 不落库 skip，仅保留实际判定
        row = models.CheckResult(
            task_id=task.id, rule_id=r.rule_id, rule_name=r.rule_name,
            dimension=r.dimension, status=r.status.value,
            why=r.why, suggestion=r.suggestion, detail=r.detail,
        )
        db.add(row)
        persisted.append(r)

    task.status = models.TaskStatus.REVIEWING
    db.commit()

    return RunSummary(
        task_code=task_code,
        counts=summarize(results),
        results=[
            CheckResultOut(
                rule_id=r.rule_id, rule_name=r.rule_name, dimension=r.dimension,
                status=r.status.value, why=r.why, suggestion=r.suggestion, detail=r.detail,
            )
            for r in persisted
        ],
    )


@router.post("/{task_code}/return", response_model=TaskOut)
def return_for_supplement(
    task_code: str,
    payload: StatusAction,
    db: Session = Depends(get_db),
    # 审核人退回，催促经办人补件
    user: User = Depends(require_role(Role.REVIEWER)),
):
    task = _get_task(db, task_code)
    task.status = models.TaskStatus.NEED_SUPPLEMENT
    task.review_comment = payload.comment or task.review_comment
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.post("/{task_code}/complete", response_model=TaskOut)
def complete_task(
    task_code: str,
    payload: StatusAction,
    db: Session = Depends(get_db),
    # 审核人确认通过，归档
    user: User = Depends(require_role(Role.REVIEWER)),
):
    task = _get_task(db, task_code)
    task.status = models.TaskStatus.COMPLETED
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.post("/{task_code}/supplement", response_model=TaskOut)
def supplement_task(
    task_code: str,
    payload: SupplementIn,
    db: Session = Depends(get_db),
    # 仅业务经办人可补件
    user: User = Depends(require_role(Role.OPERATOR)),
):
    """经办人补件：可更正单据字段值、登记新补充文件，并附补件说明。

    补件后任务状态置为「已补件」(supplemented)，回到审核人的「待复核」列表；
    同时清空历史规则结果，待审核人重新核对。
    """
    task = _get_task(db, task_code)
    if task.status not in (models.TaskStatus.NEED_SUPPLEMENT, models.TaskStatus.SUPPLEMENTED):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="仅「待补件」的任务可以补件")

    # 1) 字段级更正：按 doc_code 定位单据，重建 fields dict 以触发 JSON 列更新
    docs_by_code = {d.doc_code: d for d in task.documents}
    for upd in payload.field_updates:
        d = docs_by_code.get(upd.doc_code)
        if not d:
            continue
        new_fields = dict(d.fields or {})
        new_fields[upd.field_key] = upd.value
        d.fields = new_fields

    # 2) 登记补充文件（仅记录文件名，便于审核人看到补了哪些件）
    if payload.added_files:
        note_files = "；".join(payload.added_files)
        extra = f"[补充文件] {note_files}"
        payload.note = f"{payload.note}\n{extra}".strip() if payload.note else extra

    # 3) 记录补件说明 + 状态流转
    task.supplement_note = payload.note or task.supplement_note
    task.status = models.TaskStatus.SUPPLEMENTED

    # 4) 清空历史规则结果，等审核人重新核对
    db.query(models.CheckResult).filter_by(task_id=task.id).delete()

    db.commit()
    db.refresh(task)
    return _task_out(task)


# ======================= 智能审核 Agent =======================
@router.post("/{task_code}/ai/start", response_model=AISession)
def ai_start(
    task_code: str,
    db: Session = Depends(get_db),
    # 智能审核由审核人员发起
    user: User = Depends(require_role(Role.REVIEWER)),
):
    """启动 / 重跑智能处理：返回归集树、思考流与待处置项。

    若该任务尚无规则结果，则先执行一次规则核对（后端完成），
    再据此合成智能处理会话。真实环境此处会驱动 LLM/推理引擎流式输出。
    """
    task = _get_task(db, task_code)

    # 无结果则先跑规则，保证思考流有内容
    if not task.results:
        db.query(models.CheckResult).filter_by(task_id=task.id).delete()
        for r in run_all(task.documents):
            if r.status.value == "skip":
                continue
            db.add(models.CheckResult(
                task_id=task.id, rule_id=r.rule_id, rule_name=r.rule_name,
                dimension=r.dimension, status=r.status.value,
                why=r.why, suggestion=r.suggestion, detail=r.detail,
            ))
        task.status = models.TaskStatus.REVIEWING
        db.commit()
        db.refresh(task)

    session = build_session(task)
    return AISession(task_code=task_code, **session)


@router.post("/{task_code}/ai/resolve", response_model=AIResolveOut)
def ai_resolve(
    task_code: str,
    payload: AIResolveIn,
    db: Session = Depends(get_db),
    # 审核人对挂起项回复意见，智能处理方可继续
    user: User = Depends(require_role(Role.REVIEWER)),
):
    """审核人处置某待处理项：
      - accept：确认无实质影响 → 该项判定为 pass（保留原始差异留痕于 why）
      - keep  ：保留异常 → 维持 fail
      - ack   ：已知悉提示 → warn 保持不变
    专项审核项（规则引擎移交、库中原本无记录）在首次处置时按审核人意见落库，
    并同步到「规则审核结果」。返回处置后的最新计数，前端据此继续播放思考流。
    """
    task = _get_task(db, task_code)
    row = (
        db.query(models.CheckResult)
        .filter_by(task_id=task.id, rule_id=payload.pending_id)
        .first()
    )
    if not row:
        # 可能是专项审核项（run_all 中以 [专项] SKIP 移交、未落库）——据实时规则元数据补建
        meta = _handoff_meta(task, payload.pending_id)
        if not meta:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="待处置项不存在")
        row = models.CheckResult(
            task_id=task.id, rule_id=meta["rule_id"], rule_name=meta["rule_name"],
            dimension=meta["dimension"], status="warn",
            why=f"【专项审核】{meta['why']}", suggestion=meta["suggestion"], detail=[],
        )
        db.add(row)

    if payload.kind == "accept":
        row.status = "pass"
        note = f"【人工判定】审核人确认该处异常无实质影响，判定为通过。"
        if payload.comment:
            note += f" 审核意见：{payload.comment}"
        row.why = note + f"（原始判定：{row.why}）"
    # keep / ack 不改变 status，仅记录意见
    elif payload.comment:
        row.why = f"{row.why}【审核意见：{payload.comment}】"

    db.commit()

    # 最新计数
    counts = {"pass": 0, "fail": 0, "warn": 0}
    for r in task.results:
        key = r.status.value if hasattr(r.status, "value") else str(r.status)
        if key in counts:
            counts[key] += 1

    return AIResolveOut(
        pending_id=payload.pending_id,
        kind=payload.kind,
        new_status=row.status if isinstance(row.status, str) else row.status.value,
        counts=counts,
    )


@router.get("/{task_code}/results", response_model=list[CheckResultOut])
def get_results(
    task_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    task = _get_task(db, task_code)
    rows = db.query(models.CheckResult).filter_by(task_id=task.id).all()
    return [
        CheckResultOut(
            rule_id=r.rule_id, rule_name=r.rule_name, dimension=r.dimension,
            status=r.status.value, why=r.why, suggestion=r.suggestion, detail=r.detail,
        )
        for r in rows
    ]
