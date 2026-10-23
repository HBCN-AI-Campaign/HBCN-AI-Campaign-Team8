"""OCR -> field semantics -> targeted pixel verification -> validated evidence DTO."""
from collections import defaultdict
from pathlib import Path
import hashlib
import time
import uuid

from .config import ParserSettings, get_settings
from .contracts import ParseError
from .normalization import compact, equivalent, field_equivalent, identifier_source_check, normalize, normalize_source, normalize_choice, selection_label
from .preprocess import prepare
from .providers import HSBCSemanticProvider, PaddleHttpProvider
from .registry import FIELDS, SCHEMA_VERSION, TYPE_LABELS, guess_type
from .regional import crop_page,remap_blocks,upscale_page
from .visual_correction import correction_crop,validate_transcription
from .structured import extract_structures
from .terms import extract_terms


def _chunks(items,size):
    return [items[i:i+size] for i in range(0,len(items),size)]


def validate_candidate(candidate,spec,pages,method):
    """Provider output never supplies source coordinates or a trusted quality score."""
    by_id={b.id:(p,b) for p in pages for b in p.blocks}
    result=dict(candidate)
    result["method"]=method
    result["issues"]=[]
    result.pop('identifier_boundary', None)
    ids=result.get("block_ids",[])
    if not isinstance(ids,list) or not ids or not all(isinstance(i,str) and i in by_id for i in ids):
        result["issues"].append("EVIDENCE_MISSING_OR_UNKNOWN")
        ids=[]
    result["block_ids"]=ids
    state=result.get("visual_state","not_checked")
    if not isinstance(state,str): state="ambiguous"
    if state not in {"clear","selected","unselected","deleted","ambiguous","not_checked"}:
        state="ambiguous"
    result["visual_state"]=state
    if state in {"ambiguous","unselected","deleted"}:
        result["issues"].append("VISUAL_"+state.upper())
    if spec["visual"] and (method!="vision" or state=="not_checked"):
        result["issues"].append("VISUAL_REVIEW_REQUIRED")
    if spec.get('choices') and state!='selected':
        result['issues'].append('SELECTION_NOT_CONFIRMED')
    try:
        value=normalize(result.get("value"),spec["data_type"])
        if value is not None and spec.get('choices'):value=normalize_choice(value,spec)
    except (ValueError,TypeError,OverflowError):
        value=None
        result["issues"].append("INVALID_FIELD_TYPE")
    if value is None:
        result["issues"].append("NO_VALUE")
    result["normalized_value"]=value
    raw=result.get("raw_value")
    if not isinstance(raw,str): result["raw_value"]=None
    evidence=" ".join(by_id[i][1].text for i in ids)
    grounded=isinstance(raw,str) and bool(raw.strip()) and compact(raw) in compact(evidence)
    if not grounded and isinstance(raw,str) and method=='vision' and state=='selected' and spec.get('choices'):
        # The OCR proves the option label; only pixels prove its effective mark.
        label=selection_label(raw)
        grounded=bool(label.strip()) and compact(label) in compact(evidence)
    if not grounded:
        result["issues"].append("RAW_VALUE_NOT_GROUNDED")
    else:
        identifier_check = identifier_source_check(raw, spec, [by_id[i][1].text for i in ids])
        if not identifier_check['complete']:
            result['issues'].append('IDENTIFIER_SOURCE_INCOMPLETE')
            if identifier_check.get('boundary'):
                result['identifier_boundary'] = identifier_check['boundary']
    # This gate checks OCR grounding. A separate, auditable blind pixel pass can
    # support a correction; this function never silently rewrites OCR tokens.
    if grounded and spec["data_type"] in {"money","decimal","date","account","currency_code","unit"}:
        try:
            if not field_equivalent(normalize_source(raw,spec),value,spec):
                result["issues"].append("VALUE_SOURCE_MISMATCH")
        except (ValueError,TypeError):
            result["issues"].append("VALUE_SOURCE_MISMATCH")
    if grounded and spec["data_type"]=="text":
        try:
            if compact(value)!=compact(normalize_source(raw,spec)):
                result["issues"].append("VALUE_SOURCE_MISMATCH")
        except (ValueError,TypeError):
            result["issues"].append("VALUE_SOURCE_MISMATCH")
    if value and spec["data_type"]=="list":
        for item in value:
            # Currency aliases may normalize, but every member needs its own token.
            tokens=compact(evidence)
            aliases={"CNY":["CNY","RMB","人民币"],"USD":["USD","美元"]}.get(item,[item])
            if not any(compact(a) in tokens for a in aliases):
                result["issues"].append("LIST_ITEM_NOT_GROUNDED")
    if value and spec["data_type"]=="rows":
        numeric={"amount":"money","quantity":"decimal","unit_price":"decimal","facility_amount":"money","currency":"currency_code"}
        for row in value:
            row_ids=row.get("block_ids",[])
            if not isinstance(row_ids,list) or not row_ids or not all(isinstance(i,str) and i in ids for i in row_ids):
                result["issues"].append("ROW_EVIDENCE_MISSING")
                continue
            row_text=" ".join(by_id[i][1].text for i in row_ids)
            raw_values=row.get("raw_values",{})
            for key,cell in row.items():
                if key in {"block_ids","raw_values"} or cell is None or cell=="": continue
                cell_raw=raw_values.get(key,cell) if isinstance(raw_values,dict) else cell
                if not isinstance(cell_raw,str) or compact(cell_raw) not in compact(row_text):
                    result["issues"].append("ROW_CELL_NOT_GROUNDED")
                    continue
                try:
                    if not equivalent(normalize(cell_raw,numeric.get(key,"text")),normalize(cell,numeric.get(key,"text"))):
                        result["issues"].append("ROW_VALUE_SOURCE_MISMATCH")
                except (ValueError,TypeError): result["issues"].append("ROW_VALUE_SOURCE_MISMATCH")
    if ids and min(by_id[i][1].score for i in ids)<0.85:
        result["issues"].append("LOW_OCR_SCORE")
    result["evidence"]=[dict(block_id=i,page=by_id[i][0].number,bbox=by_id[i][1].bbox,
        text=by_id[i][1].text,score=by_id[i][1].score,method=by_id[i][1].method) for i in ids]
    result["source"]=None
    if ids:
        page=by_id[ids[0]][0].number
        boxes=[by_id[i][1].bbox for i in ids if by_id[i][0].number==page]
        result["source"]=dict(page=page,bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)])
    return result


def resolve(spec,candidates):
    def inactive(c):
        state=c.get('visual_state')
        return bool(spec.get('choices')) and c.get('method')=='vision' and state in {'deleted','unselected'} and set(c['issues']).issubset({'VISUAL_'+state.upper(),'SELECTION_NOT_CONFIRMED'})
    meaningful=[c for c in candidates if c.get("normalized_value") is not None and not inactive(c)]
    valid=[c for c in meaningful if not c["issues"]]
    chosen=valid[0] if valid else (meaningful[0] if meaningful else None)
    values=[]
    for c in meaningful:
        if not any(field_equivalent(c["normalized_value"],v,spec) for v in values): values.append(c["normalized_value"])
    conflict=len(values)>1
    # A deleted option is evidence of a possible old value, never an automatic fact.
    if conflict:
        status="conflict"
    elif chosen is None:
        status="missing"
    elif chosen["issues"]:
        status="needs_review"
    else:
        status="accepted"
    value=chosen["normalized_value"] if chosen and status=="accepted" else None
    kind={"money":"currency","decimal":"number","list":"list","rows":"json"}.get(spec["data_type"],"text")
    return dict(key=spec["key"],label=spec["label"],value=value,kind=kind,
        data_type=spec["data_type"],status=status,required=spec["required"],
        confidence=0.9 if status=="accepted" else 0.0,
        source=chosen.get("source") if chosen else None,
        raw_value=chosen.get("raw_value") if chosen else None,
        candidates=candidates,
        issues=[] if status=="accepted" else ((["CONFLICTING_VALUES"] if conflict else list(dict.fromkeys(i for c in candidates for i in c["issues"]))) or ([] if chosen else ["NOT_FOUND"])),
        method=chosen.get("method") if chosen else None,choices=list(spec.get('choices',{})))


class ParsingPipeline:
    def __init__(self,cfg:ParserSettings|None=None,ocr=None,semantic=None,progress=None):
        self.cfg=cfg or get_settings()
        self.ocr=ocr or PaddleHttpProvider(self.cfg)
        self.semantic=semantic or HSBCSemanticProvider(self.cfg)
        self.progress=progress or (lambda **kwargs:None)

    def close(self):
        for provider in (self.ocr,self.semantic):
            close=getattr(provider,"close",None)
            if close: close()

    def _retry_regions(self,pages,tcode,specs,candidates):
        regions={};attempts=[]
        for spec in specs:
            choices=bool(spec.get('choices'))
            if spec['data_type'] not in {'money','decimal','unit','date','account'} and not choices:continue
            active=[c for c in candidates[spec['key']] if not c.get('superseded')]
            if resolve(spec,active)['status']=='accepted':continue
            for c in reversed(active):
                if choices and not (c.get('method')=='vision' and c.get('visual_state')=='selected'
                    and set(c['issues'])=={'LOW_OCR_SCORE'}):continue
                if c.get('source') and set(c['issues']) & {'VALUE_SOURCE_MISMATCH','RAW_VALUE_NOT_GROUNDED','LOW_OCR_SCORE'}:
                    source=c['source'];region=regions.setdefault(source['page'],{'boxes':[],'specs':[]})
                    if choices:region['full_page_choices']=True
                    region['boxes'].append(source['bbox'])
                    if spec not in region['specs']:region['specs'].append(spec)
                    break
        for number,region in list(regions.items())[:self.cfg.regional_retry_pages]:
            page=next(p for p in pages if p.number==number)
            boxes=region['boxes']
            bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
            prepared=upscale_page(page,self.cfg.max_pixels) if region.get('full_page_choices') else crop_page(page,bbox,self.cfg.max_pixels)
            if prepared is None:continue
            crop,box=prepared
            attempt=dict(page=number,bbox=[box[0]/page.width,box[1]/page.height,box[2]/page.width,box[3]/page.height],
                         keys=[s['key'] for s in region['specs']],status='started')
            if region.get('full_page_choices'):attempt['context']='full_page_choices'
            attempts.append(attempt)
            try:
                self.progress(stage='ocr_region',page=number,total_pages=len(pages))
                new_blocks=remap_blocks(self.ocr.analyze(crop),page,box,len(attempts))
                page.blocks.extend(new_blocks)
                self.progress(stage='vision_region',page=number,total_pages=len(pages))
                raw=self.semantic.extract([page],tcode,region['specs'],visual=True)
                for candidate in raw:
                    if not isinstance(candidate,dict):continue
                    spec=next((s for s in region['specs'] if s['key']==candidate.get('key')),None)
                    if spec is None:continue
                    c=validate_candidate(candidate,spec,[page],'vision')
                    c['verification']='regional_ocr_and_pixels'
                    # A successful retry must actually cite the new regional OCR.
                    if not any(i in {b.id for b in new_blocks} for i in c['block_ids']):
                        c['issues'].append('REGIONAL_EVIDENCE_NOT_USED')
                    if not c['issues']:
                        for old in candidates[spec['key']]:
                            if field_equivalent(old.get('normalized_value'),c['normalized_value'],spec):
                                old.update(superseded=True,superseded_reason='REGIONAL_OCR_REVALIDATED')
                    candidates[spec['key']].append(c)
                attempt.update(status='completed',blocks=len(new_blocks))
            except ParseError as exc:
                # An optional rescue failure cannot invalidate unrelated, verified fields.
                attempt.update(status='failed',code=str(exc))
        return attempts

    def _correct_from_pixels(self,pages,specs,candidates):
        attempts=[]
        transcribe=getattr(self.semantic,'transcribe_region',None)
        if not callable(transcribe):return attempts
        for spec in specs:
            if len(attempts)>=self.cfg.visual_correction_fields:break
            active=[c for c in candidates[spec['key']] if not c.get('superseded')]
            if spec['data_type'] not in {'money','decimal','unit'} and not any(
                c.get('identifier_boundary', {}).get('kind') == 'possible_following_field_merge' for c in active):continue
            if resolve(spec,active)['status'] in {'accepted','conflict'}:continue
            for original in reversed(active):
                prepared=correction_crop(original,spec,pages,self.cfg.max_pixels)
                if prepared is None:continue
                crop,source=prepared
                attempt=dict(source,keys=[spec['key']],stage='blind_pixel_transcription',status='started')
                attempts.append(attempt)
                try:
                    self.progress(stage='vision_correction',page=crop.number,total_pages=len(pages))
                    transcription=transcribe(crop,spec)
                    c=validate_transcription(original,spec,transcription,source)
                    if not c['issues']:
                        for old in candidates[spec['key']]:
                            if field_equivalent(old.get('normalized_value'),c['normalized_value'],spec):
                                old.update(superseded=True,superseded_reason='BLIND_PIXEL_REVALIDATED')
                    candidates[spec['key']].append(c)
                    attempt.update(status='accepted' if not c['issues'] else 'needs_review',issues=c['issues'])
                except ParseError as exc:attempt.update(status='failed',code=str(exc))
                break
        return attempts

    def parse_document(self,path:Path,filename:str,pdf_url:str|None=None,*,type_code=None):
        start=time.monotonic()
        pages=prepare(path,self.cfg)
        tcode=type_code or guess_type(filename)
        if tcode not in FIELDS:
            # Filename is a routing hint, never a default legal classification.
            return dict(doc_code="",type_code="UNKNOWN",type_label="未识别类型，请核实文件类别",source_filename=filename,
                pdf_file=pdf_url,fields=[],status="needs_review",issues=["UNKNOWN_DOCUMENT_TYPE"],page_count=len(pages),
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),schema_version=SCHEMA_VERSION)
        numbered_invoice = tcode=='PROFORMA_INVOICE' and len(pages)>1
        candidates=defaultdict(list)
        errors=[]
        for page in pages:
            self.progress(stage="ocr",filename=filename,page=page.number,total_pages=len(pages))
            if page.needs_ocr:
                try: page.blocks=self.ocr.analyze(page)
                except ParseError as exc:
                    page.errors.append(str(exc)); errors.append(dict(page=page.number,code=str(exc)))
        goods_scope=None
        if tcode in {'COMMERCIAL_CONTRACT','COMMERCIAL_ORDER'} and len(pages)>1:
            from .goods_tables import native_goods_scope
            goods_scope=native_goods_scope(path,pages)
        numbered_goods=bool(goods_scope and goods_scope['status']=='detected')
        specs=[s for s in FIELDS[tcode] if not ((numbered_invoice or numbered_goods) and s['key']=='line_items')]
        if numbered_goods:
            specs=[dict(s,note=s.get('note','')+' 提取本文件完整合同编号（包括所有后缀），不要截短编号，也不要用正文引用的发票号替代合同号。')
                   if s['key']=='contract_no' else s for s in specs]
        visual_pages=set()
        for chunk in _chunks(pages,self.cfg.max_vision_pages_per_call):
            self.progress(stage="mapping",filename=filename,page=chunk[0].number,total_pages=len(pages))
            try:
                raw=self.semantic.extract(chunk,tcode,specs,visual=False)
                for candidate in raw:
                    if not isinstance(candidate,dict): continue
                    spec=next((s for s in specs if s["key"]==candidate.get("key")),None)
                    if spec is None: continue
                    c=validate_candidate(candidate,spec,chunk,"ocr_semantic")
                    candidates[spec["key"]].append(c)
                    # Pixel verification of every page supporting a business field. This catches
                    # high-score OCR beneath a strike-through, even on text-layer PDFs.
                    visual_pages.update(e["page"] for e in c["evidence"])
            except ParseError as exc:
                errors.append(dict(page=chunk[0].number,code=str(exc)))
            visual_pages.update(p.number for p in chunk if p.needs_ocr or p.errors)
        for chunk in _chunks([p for p in pages if p.number in visual_pages],self.cfg.max_vision_pages_per_call):
            self.progress(stage="vision",filename=filename,page=chunk[0].number,total_pages=len(pages))
            try:
                raw=self.semantic.extract(chunk,tcode,specs,visual=True)
                visual_by_key=defaultdict(list)
                for candidate in raw:
                    if not isinstance(candidate,dict): continue
                    spec=next((s for s in specs if s["key"]==candidate.get("key")),None)
                    if spec:
                        visual_by_key[spec["key"]].append(validate_candidate(candidate,spec,chunk,"vision"))
                for key,items in visual_by_key.items():
                    key_spec=next(s for s in specs if s['key']==key)
                    # Keep both channels when values differ. Otherwise a pixel verification
                    # replaces the same OCR hypothesis; retain its full provenance in candidates.
                    for old in candidates[key]:
                        if any(field_equivalent(old.get("normalized_value"),v.get("normalized_value"),key_spec) for v in items):
                            old["superseded"]=True
                    candidates[key].extend(items)
            except ParseError as exc:
                errors.append(dict(page=chunk[0].number,code=str(exc)))
        regional_attempts=self._retry_regions(pages,tcode,specs,candidates)
        regional_attempts.extend(self._correct_from_pixels(pages,specs,candidates))
        fields=[]
        for spec in specs:
            all_candidates=candidates[spec["key"]]
            active=[c for c in all_candidates if not c.get("superseded")]
            f=resolve(spec,active)
            f["candidates"]=all_candidates
            # Every critical or marked field must pass an actual pixel check.
            if f["status"]=="accepted" and not any(c["method"]=="vision" and not c["issues"] for c in active):
                f.update(status="needs_review",value=None,confidence=0.0)
                f["issues"].append("PIXEL_VERIFICATION_REQUIRED")
            if errors and f["status"]=="accepted":
                # Missing pages/chunks may contain a conflicting or limiting clause.
                f.update(status="needs_review",value=None,confidence=0.0)
                f["issues"].append("DOCUMENT_INCOMPLETE")
            fields.append(f)
        by_key={f['key']:f for f in fields}
        for value_key,unit_key in [('quantity','quantity_unit'),('unit_price','price_unit'),
                                   ('net_weight','weight_unit'),('gross_weight','weight_unit'),('package_count','package_unit')]:
            value_field=by_key.get(value_key);unit_field=by_key.get(unit_key)
            if value_field and unit_field and value_field['status']=='accepted' and unit_field['status']!='accepted':
                value_field.update(status='needs_review',value=None,confidence=0.0)
                value_field['issues'].append('MEASUREMENT_UNIT_UNRESOLVED')
        if tcode=="FACILITY_LETTER":
            borrower=next(f for f in fields if f["key"]=="borrower")
            if borrower["status"]!="accepted":
                for f in fields:
                    if f["key"] in {"facility_amount","allowed_currencies","utilization_currency"} and f["status"]=="accepted":
                        f.update(status="needs_review",value=None,confidence=0.0)
                        f["issues"].append("BORROWER_FACILITY_APPLICABILITY_UNRESOLVED")
        structure_attempts=[]
        if numbered_invoice:
            from .invoice_items import extract_invoice_items
            items,structure_attempts=extract_invoice_items(pages,self.semantic,self.cfg,self.progress,document_errors=errors)
            fields.insert(next(i for i,s in enumerate(FIELDS[tcode]) if s['key']=='line_items'),items)
        if numbered_goods:
            from .goods_tables import scope_pages
            from .invoice_items import extract_invoice_items
            items,structure_attempts=extract_invoice_items(scope_pages(pages,goods_scope),self.semantic,self.cfg,self.progress,
                document_errors=errors,expected_rows=goods_scope['rows'],scope_issues=goods_scope['issues'],
                expected_description_sources=goods_scope['description_sources'],document_total_pages=len(pages),
                context_note='当前文件为商业合同或订单，仅抽取已提供块范围的编号商品表，不将正文条款编号作为商品行。图像中范围之外的正文不进入记录。必须完整引用描述列的全部文字；下一页表头下、首个行号上方的无编号描述可能续接本页末行，应回看并保留，不能只读本页已有的描述开头。')
            items['table_scope']=goods_scope
            fields.insert(next(i for i,s in enumerate(FIELDS[tcode]) if s['key']=='line_items'),items)
        if tcode=='FACILITY_LETTER':
            structured,structure_attempts=extract_structures(pages,self.semantic,self.cfg,self.progress)
            terms,terms_attempts=extract_terms(pages,self.semantic,self.cfg,self.progress)
            structured.append(terms)
            structure_attempts.extend(terms_attempts)
            if errors:
                for f in structured:
                    if f['status']=='accepted':
                        f.update(status='needs_review',value=None,confidence=0.0)
                        f['issues'].append('DOCUMENT_INCOMPLETE')
            from .term_facts import derive_term_facts
            terms['term_facts']=derive_term_facts(terms['row_results'],terms['status'],errors)
            fields.extend(structured)
        unresolved=[f["key"] for f in fields if f["required"] and f["status"]!="accepted"]
        pending=[f["key"] for f in fields if f["status"] in {"conflict","needs_review"}]
        return dict(doc_code="",type_code=tcode,type_label=TYPE_LABELS[tcode],source_filename=filename,
            pdf_file=pdf_url,fields=fields,status="needs_review" if unresolved or pending or errors else "ready",
            issues=errors,unresolved_required=unresolved,page_count=len(pages),
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),schema_version=SCHEMA_VERSION,
            regional_attempts=regional_attempts,
            structure_attempts=structure_attempts,
            **({'goods_table_scope':goods_scope} if goods_scope is not None else {}),
            seconds=round(time.monotonic()-start,3))

    def parse(self,uploads:list[dict]):
        documents=[];type_seq=defaultdict(int)
        for item in uploads:
            try:
                doc=self.parse_document(Path(item["path"]),item["filename"],item.get("pdf_url"),type_code=item.get("type_code"))
            except ParseError as exc:
                doc=dict(doc_code="",type_code=guess_type(item["filename"]) or "UNKNOWN",
                    type_label="文件解析未完成",source_filename=item["filename"],pdf_file=item.get("pdf_url"),
                    fields=[],status="needs_review",issues=[str(exc)])
            type_seq[doc["type_code"]]+=1
            doc["doc_code"]=f"{doc['type_code']}-{type_seq[doc['type_code']]:02d}"
            if item.get('classification'):
                doc['classification']=dict(item['classification'])
            documents.append(doc)
        def find(tcode,key):
            docs=[d for d in documents if d["type_code"]==tcode]
            if len(docs)!=1: return None
            return next((f["value"] for f in docs[0]["fields"] if f["key"]==key),None)
        from .facility import analyze_facility
        context=analyze_facility(documents)
        association_pending=any(d['type_code']=='FACILITY_LETTER' for d in documents) and context['status']!='ready'
        return dict(suggested_task_code="OCR-"+uuid.uuid4().hex[:12].upper(),
            suggested_borrower=find("DRAWDOWN_INSTRUCTION","borrower") or find("FACILITY_LETTER","borrower") or "",
            suggested_currency=find("DRAWDOWN_INSTRUCTION","currency") or "",
            suggested_amount=find("DRAWDOWN_INSTRUCTION","amount"),documents=documents,
            facility_context=context,
            schema_version=SCHEMA_VERSION,status="needs_review" if association_pending or any(d["status"]!="ready" for d in documents) else "ready")
