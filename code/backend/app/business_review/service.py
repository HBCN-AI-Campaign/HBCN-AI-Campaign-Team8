from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from ..rule_engine.base import RuleResult
from ..rule_engine.runner import run_all


REVIEW_REQUIRED_RULES = {
    "SUPPORTING__CONTRACT_NO",
    "SUPPORTING__BILL_OF_LADING_NO",
    "SUPPORTING__SELLER",
    "SUPPORTING__BUYER",
    "SUPPORTING__AMOUNT",
    "SUPPORTING__QUANTITY",
    "SUPPORTING__UNIT_PRICE",
}

BUYER_CONFLICT_EVIDENCE = [
    {
        "rule_id": "BUYER_BORROWER_RULE_CONFLICT",
        "rule_name": "V2 买方行正文",
        "source": "贷款文件比对要求- V2 20261013.xlsx / Sheet1 / 买方规则行正文",
        "status": "source_conflict",
        "why": "贷款文件比对要求 V2：同一套商业合同、商业订单、运单和形式发票的所有销售方名称都要相符，且与借款人相符。",
        "suggestion": "该段位于买方规则行，但正文使用销售方。",
    },
    {
        "rule_id": "BUYER_BORROWER_RULE_CONFLICT_FIELD_MAP",
        "rule_name": "字段梳理表收货方/买方/服务接收方",
        "source": "贷款文件比对要求-字段梳理（诸葛）.xlsx / 支持性文件交叉校验",
        "status": "source_conflict",
        "why": "字段梳理表：同一套商业合同、商业订单、运单和形式发票的所有收货方名称都要相符，且与借款人相符。",
        "suggestion": "该表将买方/收货方与借款人关联。",
    },
]


def _json_safe(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_decimal(value) -> str:
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (ArithmeticError, TypeError, ValueError):
        return str(value)


def _has_complete_source_location(source) -> bool:
    if not isinstance(source, dict):
        return False
    page = source.get("page")
    if isinstance(page, bool):
        return False
    try:
        page_number = int(page)
    except (OverflowError, TypeError, ValueError):
        return False
    if page_number < 1:
        return False
    bbox = source.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(value) for value in bbox)
    except (OverflowError, TypeError, ValueError):
        return False
    return all(math.isfinite(value) for value in (x0, y0, x1, y1)) and x1 > x0 and y1 > y0


def _pdf_content_fingerprint(pdf_file: str | None) -> str | None:
    if not pdf_file:
        return None

    from ..config import SAMPLE_PDF_DIR, UPLOAD_DIR

    relative = Path(pdf_file)
    if relative.is_absolute():
        return "invalid-path"

    upload_root = Path(UPLOAD_DIR).resolve()
    sample_root = Path(SAMPLE_PDF_DIR).resolve()
    parts = relative.parts
    if parts and parts[0].lower() == "uploads":
        root = upload_root
        candidate = root.joinpath(*parts[1:]).resolve()
    else:
        root = sample_root
        candidate = root.joinpath(*parts).resolve()

    try:
        candidate.relative_to(root)
    except ValueError:
        return "invalid-path"
    if not candidate.is_file():
        return "missing"

    digest = hashlib.sha256()
    with candidate.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_fingerprint(task: models.ReviewTask) -> str:
    documents = []
    for doc in sorted(task.documents, key=lambda item: (str(item.type_code), item.doc_code)):
        documents.append({
            "doc_code": doc.doc_code,
            "type_code": _json_safe(doc.type_code),
            "fields": _json_safe(doc.fields or {}),
            "field_sources": _json_safe(doc.field_sources or {}),
            "pdf_file": doc.pdf_file,
            "pdf_content_sha256": _pdf_content_fingerprint(doc.pdf_file),
        })
    payload = {
        "task_code": task.task_code,
        "borrower": task.borrower,
        "drawdown_currency": task.drawdown_currency,
        "drawdown_amount": _canonical_decimal(task.drawdown_amount),
        "documents": documents,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _finding(result: RuleResult) -> dict:
    raw_status = result.status.value
    if raw_status == "fail":
        state, requires_resolution = "fail", True
    elif raw_status == "warn":
        state, requires_resolution = "needs_review", True
    elif raw_status == "skip" and result.rule_id in REVIEW_REQUIRED_RULES:
        state, requires_resolution = "needs_review", True
    elif raw_status == "skip":
        state, requires_resolution = "not_applicable", False
    else:
        state, requires_resolution = "pass", False

    finding = {
        "finding_id": result.rule_id,
        "tier": "strong_rule",
        "rule_id": result.rule_id,
        "rule_name": result.rule_name,
        "dimension": result.dimension,
        "status": state,
        "raw_status": raw_status,
        "requires_resolution": requires_resolution,
        "why": result.why,
        "suggestion": result.suggestion,
        "evidence": _json_safe(result.detail or []),
        "resolution": None,
    }
    if result.rule_id == "SUPPORTING__BUYER":
        finding["business_conflict"] = "BUYER_BORROWER_RULE_CONFLICT"
    return finding


def _parse_quality_findings(task: models.ReviewTask) -> list[dict]:
    findings = []
    for doc in task.documents:
        sources = doc.field_sources or {}
        for field_key, value in (doc.fields or {}).items():
            if value is None or value == "":
                continue
            source = sources.get(field_key)
            if not isinstance(source, dict):
                source = {}
            method = source.get("method")
            try:
                confidence = float(source["confidence"])
            except (KeyError, TypeError, ValueError):
                confidence = None
            if confidence is not None and not math.isfinite(confidence):
                confidence = None
            is_vision_candidate = method == "vision_ocr"
            is_low_confidence = confidence is not None and confidence < 0.8
            is_missing_location = not _has_complete_source_location(source)
            if not is_missing_location and not is_vision_candidate and not is_low_confidence:
                continue
            finding_id = f"OCR_QUALITY__{doc.doc_code}__{field_key}"[:96]
            reasons = []
            if is_missing_location:
                reasons.append("缺少可核验的页码或有效坐标框")
            elif is_vision_candidate:
                reasons.append("来自多模态 OCR 候选识别，需要人工核验")
            if is_low_confidence:
                reasons.append(f"识别置信度为 {confidence:.0%}，低于人工复核阈值 80%")
            why = f"{doc.doc_code} 的“{field_key}”" + "；".join(reasons) + "。"
            findings.append({
                "finding_id": finding_id,
                "tier": "parse_quality",
                "rule_id": "OCR_PARSE_QUALITY_REVIEW",
                "rule_name": "解析质量复核",
                "dimension": "E",
                "status": "needs_review",
                "raw_status": "warn",
                "requires_resolution": True,
                "why": why,
                "suggestion": "请对照原始 PDF 核实字段；完成核实前不得作为自动通过依据。",
                "evidence": [
                    ["单据", doc.doc_code, ""],
                    ["字段", field_key, ""],
                    ["页码", str(source.get("page") or "待定位"), ""],
                ],
                "resolution": None,
            })
    return findings


def create_review_run(
    db: Session,
    task: models.ReviewTask,
    *,
    results: list[RuleResult] | None = None,
    actor_id: int | None = None,
) -> models.BusinessReviewRun:
    findings = [_finding(item) for item in (results if results is not None else run_all(task.documents))]
    findings.extend(_parse_quality_findings(task))
    blocked = any(item["requires_resolution"] for item in findings)
    row = models.BusinessReviewRun(
        task_id=task.id,
        input_hash=input_fingerprint(task),
        status="needs_review" if blocked else "ready_for_approval",
        findings=findings,
        decision_model={"status": "not_configured", "threshold": 0.9},
        advisories={},
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def latest_review_run(db: Session, task_id: int) -> models.BusinessReviewRun | None:
    return (
        db.query(models.BusinessReviewRun)
        .filter_by(task_id=task_id)
        .order_by(models.BusinessReviewRun.id.desc())
        .first()
    )


def is_current(run: models.BusinessReviewRun, task: models.ReviewTask) -> bool:
    return run.input_hash == input_fingerprint(task)


def lock_task_inputs(db: Session, task: models.ReviewTask) -> models.ReviewTask:
    locked_task = (
        db.query(models.ReviewTask)
        .populate_existing()
        .with_for_update()
        .filter_by(id=task.id)
        .first()
    )
    if locked_task is None:
        raise LookupError("审核任务不存在")
    (
        db.query(models.Document)
        .populate_existing()
        .with_for_update()
        .filter_by(task_id=task.id)
        .order_by(models.Document.id)
        .all()
    )
    db.expire(locked_task, ["documents"])
    return locked_task


def _lock_current_run(db: Session, task: models.ReviewTask, run: models.BusinessReviewRun) -> models.BusinessReviewRun:
    task = lock_task_inputs(db, task)
    locked = (
        db.query(models.BusinessReviewRun)
        .populate_existing()
        .with_for_update()
        .filter_by(id=run.id, task_id=task.id)
        .first()
    )
    if locked is None:
        raise LookupError("审核记录不存在")

    db.expire(task, ["status", "borrower", "drawdown_currency", "drawdown_amount", "documents"])
    if task.status == models.TaskStatus.COMPLETED:
        raise ValueError("已归档任务的审核记录不可变更")
    latest = latest_review_run(db, task.id)
    if latest is None or latest.id != locked.id:
        raise ValueError("审核版本已更新，请刷新后重试")
    if not is_current(locked, task):
        raise ValueError("材料已变化，当前审核结论失效；请重新运行审核")
    return locked


def unresolved_findings(run: models.BusinessReviewRun) -> list[dict]:
    return [
        item for item in (run.findings or [])
        if item.get("requires_resolution") and not item.get("resolution")
    ]


def refresh_run_status(run: models.BusinessReviewRun) -> None:
    run.status = "needs_review" if unresolved_findings(run) else "ready_for_approval"


def run_response(run: models.BusinessReviewRun | None, task: models.ReviewTask) -> dict:
    if run is None:
        return {
            "status": "not_run",
            "is_current": False,
            "findings": [],
            "decision_model": {"status": "not_configured", "threshold": 0.9},
            "advisories": {},
        }
    return {
        "run_id": run.id,
        "task_code": task.task_code,
        "status": run.status,
        "is_current": is_current(run, task),
        "input_hash": run.input_hash,
        "created_at": run.created_at,
        "findings": run.findings or [],
        "decision_model": run.decision_model or {"status": "not_configured", "threshold": 0.9},
        "advisories": run.advisories or {},
    }


def record_resolution(
    db: Session,
    task: models.ReviewTask,
    run: models.BusinessReviewRun,
    *,
    finding_id: str,
    action: str,
    reason: str,
    actor: models.User,
) -> dict:
    if not reason or not reason.strip():
        raise ValueError("处置理由不能为空")
    run = _lock_current_run(db, task, run)
    findings = deepcopy(run.findings or [])
    finding = next((item for item in findings if item.get("finding_id") == finding_id), None)
    if finding is None:
        raise LookupError("审核项不存在")
    if not finding.get("requires_resolution"):
        raise ValueError("该审核项无需处置")
    if finding.get("resolution"):
        raise ValueError("该审核项已处置，请重新运行审核后再操作")
    if finding.get("status") == "fail" and action != "approve_exception":
        raise ValueError("明确不一致项只能更正/补件，或由审核人记录人工例外")
    if finding.get("status") != "fail" and action == "approve_exception":
        raise ValueError("只有明确不一致项可以登记人工例外")

    now = datetime.now(timezone.utc).isoformat()
    finding["resolution"] = {
        "action": action,
        "reason": reason.strip(),
        "actor_id": actor.id,
        "actor_name": actor.display_name,
        "recorded_at": now,
    }
    run.findings = findings
    refresh_run_status(run)
    db.add(models.BusinessReviewEvent(
        run_id=run.id,
        task_id=task.id,
        finding_id=finding_id,
        actor_id=actor.id,
        action=action,
        reason=reason.strip(),
    ))
    return finding


def record_advisory(
    db: Session,
    task: models.ReviewTask,
    run: models.BusinessReviewRun,
    *,
    finding_id: str,
    status: str,
    answer: str | None,
    citations: list[dict],
    actor: models.User,
) -> None:
    run = _lock_current_run(db, task, run)
    if not any(item.get("finding_id") == finding_id for item in (run.findings or [])):
        raise LookupError("审核项不存在")
    advisories = dict(run.advisories or {})
    advisories[finding_id] = {
        "status": status,
        "answer": answer,
        "citations": _json_safe(citations),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor.id,
    }
    run.advisories = advisories
    db.add(models.BusinessReviewEvent(
        run_id=run.id,
        task_id=task.id,
        finding_id=finding_id,
        actor_id=actor.id,
        action="llm_reference",
        reason=status,
        detail={"citations": _json_safe(citations)},
    ))


def archive_review_task(
    db: Session,
    task: models.ReviewTask,
    run: models.BusinessReviewRun,
    *,
    actor: models.User,
    comment: str,
) -> None:
    run = _lock_current_run(db, task, run)
    if task.status != models.TaskStatus.TO_RECHECK:
        raise ValueError("任务尚未进入审核人复核环节")
    unresolved = unresolved_findings(run)
    if unresolved:
        ids = "、".join(item["finding_id"] for item in unresolved[:8])
        raise ValueError(f"仍有未处置的审核项，不能归档：{ids}")

    task.status = models.TaskStatus.COMPLETED
    db.add(models.BusinessReviewEvent(
        run_id=run.id,
        task_id=task.id,
        actor_id=actor.id,
        action="complete",
        reason=comment.strip(),
        detail={"input_hash": run.input_hash},
    ))
