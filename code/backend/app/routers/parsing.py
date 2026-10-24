"""Parsing-run API; only operators upload and only the owner reads results."""
from pathlib import Path
import json
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..config import UPLOAD_DIR
from ..models import Role, User
from ..security import require_role
from ..parsing.config import get_settings
from ..parsing import jobs
from ..schemas import FacilityContextIn

router=APIRouter(prefix="/api/parsing",tags=["parsing"])


async def save_uploads(files,owner_id):
    cfg=get_settings()
    if not 0<len(files)<=cfg.max_files: raise HTTPException(400,"文件数量超限")
    batch=uuid.uuid4().hex
    folder=UPLOAD_DIR/batch
    folder.mkdir(parents=True,exist_ok=False)
    try:
        return await _save_batch(files,folder,batch,cfg,owner_id)
    except Exception:
        _remove_batch(folder)
        raise


def _remove_batch(folder):
    target=folder.resolve()
    if target.parent!=UPLOAD_DIR.resolve() or len(target.name)!=32 or any(c not in '0123456789abcdef' for c in target.name):
        raise ValueError('INVALID_UPLOAD_CLEANUP_PATH')
    if target.is_dir():shutil.rmtree(target)


async def _save_batch(files,folder,batch,cfg,owner_id):
    saved=[];total=0
    for i,f in enumerate(files):
        original=f.filename or f"document-{i+1}.pdf"
        extension=Path(original).suffix.lower()
        if extension not in {".pdf",".png",".jpg",".jpeg",".webp"}:
            raise HTTPException(400,"请上传 PDF 或图片；其他格式请先转成 PDF")
        name=f"{i+1:02d}-{uuid.uuid4().hex[:12]}{extension}"
        dest=folder/name
        size=0
        with dest.open("wb") as target:
            while chunk:=await f.read(1024*1024):
                size+=len(chunk);total+=len(chunk)
                if size>cfg.max_file_bytes or total>cfg.max_batch_bytes:
                    raise HTTPException(413,"上传文件体积超限")
                target.write(chunk)
        if not size: raise HTTPException(400,"文件不能为空")
        saved.append(dict(filename=original,path=str(dest),pdf_url=f"uploads/{batch}/{name}"))
    (folder/'.owner.json').write_text(json.dumps({'owner_id':owner_id}),encoding='utf-8')
    return saved


@router.post("/runs",status_code=202)
async def create_run(files:list[UploadFile]=File(...),document_types:str|None=Form(default=None),user:User=Depends(require_role(Role.OPERATOR))):
    from ..parsing.classification import parse_selections
    try:selections=parse_selections(document_types,len(files))
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    saved=await save_uploads(files,user.id)
    for item,selection in zip(saved,selections):
        if selection.type_code:
            item['type_code']=selection.type_code
            item['classification']=dict(method='operator_selected',type_code=selection.type_code,
                reason=selection.reason,selected_by=user.id,selected_at=jobs.now())
    try:run_id=jobs.submit(saved,user.id)
    except Exception:
        _remove_batch(Path(saved[0]['path']).parent)
        raise
    if run_id is None:
        _remove_batch(Path(saved[0]['path']).parent)
        raise HTTPException(429,"解析队列已满，请稍后提交")
    return dict(run_id=run_id,state="queued")


@router.get("/runs/{run_id}")
def get_run(run_id:str,user:User=Depends(require_role(Role.OPERATOR))):
    try: run=jobs.read_run(run_id,user.id)
    except (FileNotFoundError,ValueError,KeyError): raise HTTPException(404,"解析任务不存在") from None
    if run.get('result') is not None:
        from ..parsing.facility import analyze_facility
        run['result']['facility_context']=analyze_facility(run['result'].get('documents', []))
        if any(d['type_code']=='FACILITY_LETTER' for d in run['result'].get('documents', [])) and run['result']['facility_context']['status']!='ready':
            run['result']['status']='needs_review'
    return {k:v for k,v in run.items() if k not in {"owner_id","process"}}


@router.post('/facility-context')
def check_facility_context(payload:FacilityContextIn,user:User=Depends(require_role(Role.OPERATOR))):
    from types import SimpleNamespace
    from ..parsing.facility import analyze_facility,verified_dtos
    documents=[]
    try:
        for doc in payload.documents:
            fields,_=jobs.verified_document(doc,user.id)
            documents.append(SimpleNamespace(doc_code=doc.doc_code,type_code=doc.type_code,fields=fields))
        return analyze_facility(verified_dtos(documents),
            payload.facility_selection.model_dump() if payload.facility_selection else None,
            payload.model_dump(mode='json', include={'borrower','drawdown_currency','drawdown_amount'}) if payload.borrower is not None else None)
    except FileNotFoundError:raise HTTPException(404,'解析凭据不存在') from None
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
