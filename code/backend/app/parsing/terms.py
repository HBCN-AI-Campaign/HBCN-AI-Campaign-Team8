"""FOL schedule business adapter: complete literal clauses and scoped provenance.

This is a bounded adapter for registered FOL headings, not a layout framework or
an interpretation of loan terms. Uncertain scope/coverage remains reviewable.
"""
import re
from collections import Counter
from dataclasses import dataclass, replace

from .contracts import ParseError
from .normalization import compact
from .records import column_value, merge_records, row_schema, validate_record


HEADINGS=('Purpose','Utilization','Interest','Default Interest','Prepayment',
          'Disbursement of Loan Proceeds','Non-Business Day','Fees','Undertakings')
_HEADINGS={compact(s):s for s in HEADINGS}
KEY='facility_terms'
LABEL='逐授信附表条款'


@dataclass
class Clause:
    title: list
    heading: tuple
    body: list

    @property
    def facility(self):
        return column_value(' '.join(b.text for _,b in self.title),'facility_name')

    @property
    def name(self):
        return self.heading[1].text

    @property
    def focus(self):
        return self.heading[0].number

    def blocks(self):
        return [*self.title,self.heading,*self.body]


def clause_scopes(pages):
    """Conservative exact registered headings, preserving cross-page bodies."""
    ordered=[];margins=[]
    for page in sorted(pages,key=lambda p:p.number):
        for block in page.blocks:
            if block.method.endswith('_region'):continue
            center=(block.bbox[0]+block.bbox[2])/2
            if block.bbox[1]>=.82 and (compact(block.text)=='internal' or
                    (.35<=center<=.65 and re.fullmatch(r'\d{1,3}',block.text.strip()))):
                continue
            if block.bbox[1]>=.90:
                margins.append(dict(block_id=block.id,page=page.number,bbox=block.bbox,text=block.text))
                continue
            ordered.append((page,block))
    starts=[i for i,(_,b) in enumerate(ordered) if compact(b.text)=='scheduleoffacilities']
    issues=[];clauses=[]
    if not starts:return [],['TERMS_SCHEDULE_NOT_FOUND'],[]
    schedule_pages=set()
    for idx,start in enumerate(starts):
        next_start=starts[idx+1] if idx+1<len(starts) else None
        end=next((i for i in range(start+1,len(ordered)) if
            compact(ordered[i][1].text)=='scheduleoffacilities' or
            compact(ordered[i][1].text).startswith('generaltermsandconditionsforfacilities')),None)
        if end is None:
            issues.append('TERMS_SCHEDULE_END_NOT_FOUND');continue
        # A later schedule after a general-terms chapter is not silently linked.
        if next_start is not None and end!=next_start:
            issues.append('TERMS_SCHEDULE_ORDER_UNRESOLVED')
        section=ordered[start+1:end]
        schedule_pages.update(p.number for p,_ in ordered[start:end])
        headings=[i for i,(_,b) in enumerate(section) if compact(b.text) in _HEADINGS]
        if not headings or headings[0]==0:
            issues.append('TERMS_FACILITY_TITLE_NOT_FOUND');continue
        title=section[:headings[0]]
        if any(p.number!=title[0][0].number for p,_ in title) or len(title)>3:
            issues.append('TERMS_FACILITY_TITLE_UNRESOLVED');continue
        counts=Counter(compact(section[i][1].text) for i in headings)
        if max(counts.values())>1:issues.append('TERMS_DUPLICATE_CLAUSE_HEADING')
        for n,position in enumerate(headings):
            stop=headings[n+1] if n+1<len(headings) else len(section)
            body=section[position+1:stop]
            if not body:issues.append('TERMS_CLAUSE_BODY_NOT_FOUND')
            clauses.append(Clause(title,section[position],body))
    margins=[m for m in margins if m['page'] in schedule_pages]
    if margins:issues.append('TERMS_MARGIN_REVIEW_REQUIRED')
    return clauses,list(dict.fromkeys(issues)),margins


def literal_row(clause):
    """OCR candidate only; this function does not confer model verification."""
    groups={'facility_name':clause.title,'clause_heading':[clause.heading],'clause_text':clause.body}
    sources={key:dict(raw_value=' '.join(b.text for _,b in blocks),
                      block_ids=[b.id for _,b in blocks]) for key,blocks in groups.items()}
    return dict(facility_name=clause.facility,clause_heading=clause.name,
                clause_text=sources['clause_text']['raw_value'],cell_sources=sources)


def _validate(row,clause,pages):
    result=validate_record(row,KEY,pages)
    expected=literal_row(clause)
    for column in ('facility_name','clause_heading','clause_text'):
        cell=result['cells'].get(column,{})
        ids=[s['block_id'] for s in cell.get('sources',[])]
        want=expected['cell_sources'][column]
        # An in-block substring alone cannot establish the whole legal clause.
        if ids!=want['block_ids'] or compact(cell.get('raw_value') or '')!=compact(want['raw_value']):
            code='TERMS_CLAUSE_NOT_COMPLETE' if column=='clause_text' else 'TERMS_SCOPE_MISMATCH'
            result['issues'].append(code)
    if result['issues']:result['status']='needs_review'
    result['issues']=list(dict.fromkeys(result['issues']))
    result['focus_page']=clause.focus
    return result


def extract_terms(pages,semantic,cfg,progress):
    clauses,issues,margins=clause_scopes(pages)
    attempts=[];records=[];extract=getattr(semantic,'extract_records',None)
    if not callable(extract):issues.append('TERMS_PROVIDER_NOT_AVAILABLE')
    for focus in sorted({c.focus for c in clauses}):
        group=[c for c in clauses if c.focus==focus]
        allowed={b.id for c in group for _,b in c.blocks()}
        context=[replace(p,blocks=[b for b in p.blocks if b.id in allowed]) for p in pages
                 if any(b.id in allowed for b in p.blocks)]
        failure=None;response=None
        if not callable(extract):failure='TERMS_PROVIDER_NOT_AVAILABLE'
        elif len(attempts)>=cfg.max_terms_calls:failure='TERMS_CALL_BUDGET_EXCEEDED'
        elif len(context)>cfg.max_vision_pages_per_call:failure='TERMS_CONTEXT_PAGE_LIMIT'
        else:
            spec=dict(key=KEY,label=LABEL,row_schema=row_schema(KEY),
                note='按expected_clauses逐项逐字转录完整条款，一项一行，不概括、不翻译、不遗漏任何限制或子项。'
                '正文包括下一页续文，但不包括其他条款。facility_name仅引用本附表标题。'
                '提供的块是正文范围，图片中范围外内容不要带入。'
                '若原图有删除、打叉、涂改、未识别条款标题或OCR与原图不符，complete=false，不能自行纠正或忽略。'
                '没有固定利率/期限不补造；罚息、费用、总协议引用保持原文。'
                '每列cell_sources列出有序全部块ID，raw_value为整列完整原文；正文不可仅引一个片段。',
                expected_clauses=[dict(facility_name=c.facility,clause_heading=c.name,
                    body_block_ids=[b.id for _,b in c.body]) for c in group])
            for retry in range(2):
                if len(attempts)>=cfg.max_terms_calls:
                    failure='TERMS_CALL_BUDGET_EXCEEDED';response=None;break
                attempt=dict(key=KEY,focus_page=focus,context_pages=[p.number for p in context],status='started',format_retry=bool(retry))
                attempts.append(attempt)
                try:
                    progress(stage='terms',page=focus,total_pages=len(pages))
                    response=extract(context,spec,focus_page=focus)
                    if not isinstance(response,dict) or not isinstance(response.get('records'),list) or type(response.get('complete')) is not bool:
                        raise ParseError('RECORDS_INVALID_RESPONSE')
                    if len(response['records'])>200:raise ParseError('RECORDS_ROW_LIMIT')
                    attempt.update(status='completed',rows=len(response['records']),complete=response['complete'])
                    malformed=any(not isinstance(r,dict) or
                        not all(isinstance(r.get(k),str) for k in ('facility_name','clause_heading','clause_text')) or
                        not isinstance(r.get('cell_sources'),dict) for r in response['records'])
                    if malformed and response['complete']:
                        attempt.update(status='invalid_format',code='TERMS_INVALID_ROW_FORMAT')
                        response=None
                        if retry==0:
                            # A format-only retry cannot relax evidence or override
                            # a model's explicit visual incompleteness decision.
                            spec=dict(spec,format_repair='上一回答的字段形状错误。每行facility_name、clause_heading、clause_text必须是字符串，不能是对象。'
                                '另设cell_sources对象，其同名各列为{raw_value:完整原文字符串,block_ids:有序块ID数组}。'
                                '仍须检查原图；不得为了格式正确而宣称不清楚的条款完整。')
                            continue
                        failure='TERMS_INVALID_ROW_FORMAT'
                    elif not response['complete']:failure='TERMS_PAGE_INCOMPLETE'
                    break
                except ParseError as exc:
                    failure=str(exc);response=None;attempt.update(status='failed',code=failure);break
        if failure:issues.append(failure)
        seen=set()
        for row in (response or {}).get('records',[]):
            if not isinstance(row,dict):
                issues.append('TERMS_UNEXPECTED_ROW');continue
            match=next((c for c in group if compact(row.get('facility_name',''))==compact(c.facility) and
                        compact(row.get('clause_heading',''))==compact(c.name)),None)
            if match is None:
                issues.append('TERMS_UNEXPECTED_ROW');continue
            seen.add(id(match))
            result=_validate(row,match,context)
            if failure:
                result['issues'].append(failure);result['status']='needs_review'
            records.append(result)
        for clause in group:
            if id(clause) in seen:continue
            # Show the source candidate to the operator but never accept an
            # omitted/unverified clause through deterministic copying.
            result=validate_record(literal_row(clause),KEY,context)
            result.update(value=None,status='needs_review',focus_page=focus,candidate_method='ocr_scope')
            result['issues'].extend([failure or 'TERMS_CLAUSE_MISSING'])
            records.append(result)
    rows=merge_records(KEY,records)
    issues.extend(code for r in rows for code in r['issues'])
    if not rows:issues.append('TERMS_NOT_FOUND')
    accepted=bool(rows) and not issues
    source=None
    if clauses:
        p,b=clauses[0].title[0];source=dict(page=p.number,bbox=b.bbox)
    field=dict(key=KEY,label=LABEL,kind='json',data_type='rows',required=False,
        value=[r['value'] for r in rows] if accepted else None,status='accepted' if accepted else 'needs_review',
        confidence=.9 if accepted else 0.0,source=source,raw_value=None,method='vision_scoped_clauses',
        row_results=rows,issues=list(dict.fromkeys(issues)),candidates=[],choices=[],margin_blocks=margins)
    return field,attempts
