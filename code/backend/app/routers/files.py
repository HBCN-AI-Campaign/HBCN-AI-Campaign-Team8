"""Authenticated original preview. Never expose the upload directory statically."""
import hashlib
import json
from pathlib import Path
import re
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import String, cast
from ..config import UPLOAD_DIR
from ..database import get_db
from ..models import Document,ReviewTask,Role,User
from ..security import get_current_user

router=APIRouter(tags=['originals'])


def _historical_original(db, relative, owner_id, source):
    """Reuse the server-written supplement snapshot; free text grants no access."""
    try:
        from ..business_review.storage import BusinessReviewAudit
    except ImportError:
        # Historical access is granted only when the audit module is integrated.
        return False
    rows=db.query(BusinessReviewAudit.data).join(ReviewTask,ReviewTask.id==BusinessReviewAudit.task_id).filter(
        ReviewTask.submitted_by==owner_id,BusinessReviewAudit.kind=='supplement',
        cast(BusinessReviewAudit.data,String).contains(relative,autoescape=True))
    digest=None
    for (data,) in rows.yield_per(50):
        snapshot=data.get('previous_snapshot') if isinstance(data,dict) else None
        documents=snapshot.get('documents') if isinstance(snapshot,dict) else None
        if not isinstance(documents,list):continue
        for doc in documents:
            if not isinstance(doc,dict):continue
            sources=doc.get('sources')
            if not isinstance(sources,dict) or not any(isinstance(s,dict) and s.get('file')==relative for s in sources.values()):continue
            if digest is None:digest=hashlib.sha256(source.read_bytes()).hexdigest()
            if doc.get('file_sha256')==digest:return True
    return False


@router.get('/uploads/{batch}/{filename}')
def original(batch:str,filename:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not re.fullmatch(r'[a-f0-9]{32}',batch) or Path(filename).name!=filename or Path(filename).suffix.lower() not in {'.pdf','.png','.jpg','.jpeg','.webp'}:
        raise HTTPException(404,'原件不存在')
    path=(UPLOAD_DIR/batch/filename).resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(404,'原件不存在')
    allowed=False;owner=None
    try:
        owner=json.loads((path.parent/'.owner.json').read_text(encoding='utf-8'))['owner_id']
        if not isinstance(owner,int) or isinstance(owner,bool):owner=None
        allowed=user.role==Role.OPERATOR and owner==user.id
    except (OSError,ValueError,KeyError,TypeError):pass
    if user.role==Role.REVIEWER and owner is not None:
        # The submitted task must belong to the uploader, including old versions.
        relative=f'uploads/{batch}/{filename}'
        allowed=db.query(Document.id).join(ReviewTask).filter(
            Document.pdf_file==relative,ReviewTask.submitted_by==owner).first() is not None
        if not allowed:allowed=_historical_original(db,relative,owner,path)
    if not allowed:raise HTTPException(404,'原件不存在')
    return FileResponse(path,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
