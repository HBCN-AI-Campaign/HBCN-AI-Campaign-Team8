"""Read-only access to the operator's local real-material sets.

Materials are referenced in place from BUSINESS_MATERIALS_ROOT: never copied into
the repository, never mounted statically (see routers/files.py for the same
principle), and never persisted as a document path — jobs.py only accepts
`uploads/...` originals, so loaded bytes must go through the normal upload route.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..business_review.material_sets import (
    MATERIAL_SETS,
    MaterialSetError,
    describe_documents,
    describe_set,
    material_set,
    normalize_case_code,
    resolve_document,
    resolve_root,
)
from ..models import Role, User
from ..security import require_role

router = APIRouter(prefix="/api/materials", tags=["materials"])

_FILE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _unavailable(reason: str) -> list[dict]:
    return [
        {
            "case_code": item.code,
            "title": f"第{int(item.code)}套",
            "focus": item.focus,
            "expected_documents": item.expected_documents,
            "available": False,
            "reason": reason,
        }
        for item in MATERIAL_SETS
    ]


@router.get("/sets")
def list_material_sets(user: User = Depends(require_role(Role.OPERATOR))):
    """Available material sets. Reports availability only — never the folder layout."""
    try:
        root = resolve_root()
    except MaterialSetError as exc:
        return {"configured": False, "reason": str(exc), "sets": _unavailable(str(exc))}
    return {"configured": True, "reason": "", "sets": [describe_set(root, item) for item in MATERIAL_SETS]}


def _resolved_set(code: str):
    normalized = normalize_case_code(code)
    if normalized is None:
        raise HTTPException(404, "材料套不存在")
    try:
        return resolve_root(), material_set(normalized)
    except MaterialSetError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/sets/{code}/documents")
def list_material_documents(code: str, user: User = Depends(require_role(Role.OPERATOR))):
    """Ordered documents of one set. Byte size is omitted; the operator decides from the list."""
    root, item = _resolved_set(code)
    try:
        documents = describe_documents(root, item)
    except MaterialSetError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"case_code": item.code, "focus": item.focus, "documents": documents}


@router.get("/sets/{code}/documents/{index}")
def material_document(code: str, index: int, user: User = Depends(require_role(Role.OPERATOR))):
    """Stream one original. Only indices into the freshly computed list are accepted."""
    root, item = _resolved_set(code)
    try:
        path = resolve_document(root, item, index)
    except MaterialSetError as exc:
        raise HTTPException(404, str(exc)) from None
    return FileResponse(path, filename=path.name, media_type="application/pdf", headers=_FILE_HEADERS)