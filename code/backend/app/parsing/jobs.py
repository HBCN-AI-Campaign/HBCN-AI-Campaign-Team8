"""Bounded single-process jobs. Disk receipts survive; interrupted jobs need retry."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import uuid

from .pipeline import ParsingPipeline

DATA_DIR=Path(__file__).resolve().parents[2]/"parser_data"/"runs"
_WORKER=ThreadPoolExecutor(max_workers=1,thread_name_prefix="document-parser")
_CAPACITY=threading.BoundedSemaphore(2)
_LOCK=threading.RLock()
_PROCESS=uuid.uuid4().hex


def now(): return datetime.now(timezone.utc).isoformat()


def _path(run_id):
    if len(run_id)!=32 or any(c not in "0123456789abcdef" for c in run_id): raise FileNotFoundError
    return DATA_DIR/(run_id+".json")


def _write(run):
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    dest=_path(run["id"])
    temp=dest.with_suffix(".tmp")
    with _LOCK:
        temp.write_text(json.dumps(run,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        temp.replace(dest)


def read_run(run_id,owner_id):
    with _LOCK:
        run=json.loads(_path(run_id).read_text(encoding="utf-8"))
        if run["owner_id"]!=owner_id: raise FileNotFoundError
        if run["state"] in {"queued","running"} and run["process"]!=_PROCESS:
            run.update(state="interrupted",error="解析进程已重启，请重新提交材料",updated_at=now())
            _write(run)
        return run


def submit(uploads,owner_id):
    if not _CAPACITY.acquire(blocking=False): return None
    run=dict(id=uuid.uuid4().hex,owner_id=owner_id,process=_PROCESS,state="queued",created_at=now(),updated_at=now(),result=None)
    try:
        _write(run)
        _WORKER.submit(_execute,run,uploads)
    except Exception:
        _CAPACITY.release()
        raise
    return run["id"]


def save_completed(result,owner_id):
    """Give synchronous compatibility callers the same immutable receipt."""
    run_id=uuid.uuid4().hex
    result["parse_run_id"]=run_id
    _write(dict(id=run_id,owner_id=owner_id,process=_PROCESS,state="completed",
                created_at=now(),updated_at=now(),result=result))
    return result


def _execute(run,uploads):
    def progress(**event):
        run.update(state="running",progress=event,updated_at=now())
        _write(run)
    pipeline=None
    try:
        progress(stage="preparing")
        pipeline=ParsingPipeline(progress=progress)
        result=pipeline.parse(uploads)
        result["parse_run_id"]=run["id"]
        run.update(state="completed",result=result,updated_at=now())
    except Exception:
        run.update(state="failed",error="PARSING_FAILED",updated_at=now())
    finally:
        if pipeline: pipeline.close()
        _write(run)
        _CAPACITY.release()


def verified_document(document,owner_id):
    """Bind editable task input to an immutable, server-owned parsing receipt."""
    if not document.parse_run_id:
        # Legacy/manual entry stays possible, with explicit unverified quality.
        fields={k:v for k,v in document.fields.items() if k!="_parsing"}
        fields["_parsing"]=dict(document_errors=["NO_SERVER_PARSING_RECEIPT"],fields={})
        return fields,document.field_sources
    run=read_run(document.parse_run_id,owner_id)
    if run["state"]!="completed": raise ValueError("解析尚未完成")
    matches=[d for d in run["result"]["documents"] if d["doc_code"]==document.doc_code]
    if len(matches)!=1: raise ValueError("识别凭据与单据不匹配")
    original=matches[0]
    if original["type_code"]!=document.type_code or original.get("pdf_file")!=document.pdf_file:
        raise ValueError("识别凭据与原件不匹配")
    if document.type_code=="UNKNOWN" or not original["fields"]:
        raise ValueError("文件尚未完成识别，请核实后重新解析")
    # Do not accept a replaced original under the same receipt.
    from ..config import UPLOAD_DIR
    relative=Path(document.pdf_file or "")
    if not relative.parts or relative.parts[0]!="uploads": raise ValueError("原件路径无效")
    source=UPLOAD_DIR.joinpath(*relative.parts[1:]).resolve()
    if not source.is_relative_to(UPLOAD_DIR.resolve()) or not source.is_file(): raise ValueError("原件不存在")
    if hashlib.sha256(source.read_bytes()).hexdigest()!=original.get("source_sha256"):
        raise ValueError("原件已变化，必须重新解析")
    fields={};sources={};audit={};unresolved=[];pending=[]
    for f in original["fields"]:
        key=f["key"]
        supplied=document.fields.get(key)
        reason=document.field_confirmations.get(key,"").strip()
        changed=supplied!=f["value"]
        confirmed=bool(reason) and supplied is not None and supplied!=""
        if changed and not confirmed: raise ValueError(f"字段 {f['label']} 更正需填写核实说明")
        if confirmed:
            from .normalization import normalize, normalize_choice
            try:
                supplied=normalize(supplied,f["data_type"])
                if f['data_type']=='rows':
                    from .records import ROW_MODELS,normalize_records
                    if key in ROW_MODELS:supplied=normalize_records(supplied,key)
                if f.get('choices'):
                    supplied=normalize_choice(supplied,{'choices':{v:[] for v in f['choices']}})
            except (ValueError,TypeError): raise ValueError(f"字段 {f['label']} 格式不正确") from None
        else:
            supplied=f["value"]
        status="confirmed" if confirmed else f["status"]
        fields[key]=supplied
        if f.get("source"): sources[key]=f["source"]
        if f["required"] and status not in {"accepted","confirmed"}: unresolved.append(key)
        if status in {"needs_review","conflict"}: pending.append(key)
        audit[key]=dict(machine=f,final_value=supplied,status=status,confirmation_reason=reason if confirmed else None,
            confirmed_by=owner_id if confirmed else None,confirmed_at=now() if confirmed else None)
    fields["_parsing"]=dict(run_id=run["id"],source_sha256=original["source_sha256"],schema_version=original["schema_version"],
        fields=audit,unresolved_required=unresolved,unresolved_fields=pending,document_errors=original.get("issues",[]))
    if original.get('classification'):
        from copy import deepcopy
        fields['_parsing']['classification']=deepcopy(original['classification'])
    return fields,sources
