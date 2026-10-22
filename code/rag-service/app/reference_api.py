"""Private, separately authorized case/experience curation and reference reads."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .reference_contracts import ReferenceCandidate, ReferenceReview, ReferenceSearch, ReferenceWithdrawal
from .reference_security import ReferenceForbidden, require_reference_principal
from .reference_store import ReferenceConflict, get_reference_store


router = APIRouter(prefix="/api/v1/references", tags=["reviewed-references"])


def operation(method, actor, *args, **kwargs):
    try:
        return method(actor, *args, **kwargs)
    except ReferenceForbidden:
        raise HTTPException(403, "参考库权限不足") from None
    except LookupError:
        raise HTTPException(404, "参考版本不存在或当前不可用") from None
    except ReferenceConflict:
        raise HTTPException(409, "状态、版本、来源或复核条件不满足；请重新读取并复核") from None


@router.post("/candidates", status_code=201)
def create_candidate(payload: ReferenceCandidate, response: Response,
                     actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return operation(store.create, actor, payload)


@router.post("/search")
def search_references(payload: ReferenceSearch, response: Response,
                      actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return {"references": operation(store.search, actor, payload), "source_type": payload.kind,
            "normative_evidence": False, "retrieval_mode": "structured_filters_then_lexical",
            "notice": "历史参考与经验不证明本案事实，不替代规范依据或最终审批"}


@router.get("/versions/{version_id}")
def get_version(version_id: UUID, response: Response, namespace: str = Query(min_length=3, max_length=64),
                inspect_candidate: bool = False, actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return operation(store.get, actor, namespace, version_id, inspect_candidate=inspect_candidate)


@router.post("/versions/{version_id}/approve")
def approve_version(version_id: UUID, payload: ReferenceReview, response: Response,
                    namespace: str = Query(min_length=3, max_length=64),
                    actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return operation(store.approve, actor, namespace, version_id, payload)


@router.post("/versions/{version_id}/withdraw")
def withdraw_version(version_id: UUID, payload: ReferenceWithdrawal, response: Response,
                     namespace: str = Query(min_length=3, max_length=64),
                     actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return operation(store.withdraw, actor, namespace, version_id, payload)


@router.post("/purge-expired")
def purge_expired(response: Response, namespace: str = Query(min_length=3, max_length=64),
                  actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return operation(store.purge_expired, actor, namespace)


@router.get("/audit")
def read_audit(response: Response, namespace: str = Query(min_length=3, max_length=64),
                after: int = Query(default=0, ge=0),
                actor=Depends(require_reference_principal), store=Depends(get_reference_store)):
    response.headers["Cache-Control"] = "no-store"
    return {"events": operation(store.audit, actor, namespace, after=after)}
