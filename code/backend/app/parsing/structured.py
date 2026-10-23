"""FOL-specific typed collections, bounded adjacent-page extraction and evidence.

This adapts the HSBC business schema, not a general document layout framework.
Unknown section boundaries remain an explicit extraction gap.
"""
import re
from dataclasses import replace

from .contracts import ParseError
from .records import row_schema,validate_record,merge_records


STRUCTURED_FIELDS=[
    dict(key='borrowers',label='法定借款人清单',note='Borrower标题下的完整中英文法定名称及原文简称，非本次提款适用主体。'),
    dict(key='facility_limits',label='授信品种及组额度',note='Facility/Amount正文及表格的总额度、品种及共享组额度，不含借款人分配金额；保留正文与表格不一致的各行。总额度可用原文aggregate Facility amount作为名称。'),
    dict(key='borrower_allocations',label='借款人授信分配',note='仅Allocation among Borrowers表格：facility_name/borrower_name/amount/currency。组名可含多个品种，不拆成可独立加总的额度。'),
]


def _span(pages,start,stop):
    ordered=[(page,block) for page in pages for block in page.blocks if not block.method.endswith('_region')]
    begins=[i for i,(_,b) in enumerate(ordered) if re.search(start,b.text,re.I)]
    if len(begins)!=1:return [],'STRUCTURE_SECTION_NOT_UNIQUE'
    begin=begins[0]
    end=next((i for i in range(begin+1,len(ordered)) if re.search(stop,ordered[i][1].text,re.I)),None)
    if end is None:return [],'STRUCTURE_SECTION_END_NOT_FOUND'
    return ordered[begin:end],None


def section_scope(pages,key):
    if key=='borrowers':return _span(pages,r'^\s*Borrower\s*:',r'^\s*Lender\s*:')
    return _span(pages,r'^\s*Facility\s*/\s*Amount\s*:',r'^\s*(?:Finance\s+Documents|Security)\s*:')


def section_pages(pages,key):
    selected,gap=section_scope(pages,key)
    return sorted({p.number for p,_ in selected}),gap


def extract_structures(pages,semantic,cfg,progress):
    fields=[];attempts=[];used=0
    extract=getattr(semantic,'extract_records',None)
    for definition in STRUCTURED_FIELDS:
        key=definition['key'];selected,gap=section_scope(pages,key)
        numbers=sorted({p.number for p,_ in selected})
        allowed={b.id for _,b in selected}
        scoped=[replace(p,blocks=[b for b in p.blocks if b.id in allowed]) for p in pages if p.number in numbers]
        records=[];issues=[gap] if gap else []
        spec=dict(definition,row_schema=row_schema(key))
        if not callable(extract):issues.append('STRUCTURE_PROVIDER_NOT_AVAILABLE')
        for number in numbers if callable(extract) else []:
            # Two pages retain carry-over group names and split legal names without
            # treating every chunk as a complete, competing value of the collection.
            if key=='borrowers':
                context=[p for p in scoped if p.number in {number,number+1}]
                # A continuation whose beginning was in the previous page needs it too.
                if number!=numbers[0]:context=[p for p in scoped if p.number in {number-1,number}]
            else:
                context=[p for p in scoped if p.number in ({number,number+1} if number==numbers[0] else {number-1,number})]
            if used>=cfg.max_structure_calls:
                issues.append('STRUCTURE_CALL_BUDGET_EXCEEDED');break
            used+=1
            attempt=dict(key=key,focus_page=number,context_pages=[p.number for p in context],status='started')
            attempts.append(attempt)
            try:
                progress(stage='structure',page=number,total_pages=len(pages))
                response=extract(context,spec,focus_page=number)
                if not isinstance(response,dict) or not isinstance(response.get('records'),list) or type(response.get('complete')) is not bool:
                    raise ParseError('RECORDS_INVALID_RESPONSE')
                if not response['complete']:issues.append('STRUCTURE_PAGE_INCOMPLETE')
                if len(response['records'])>200:raise ParseError('RECORDS_ROW_LIMIT')
                ignored=0
                for row in response['records']:
                    result=validate_record(row,key,context)
                    sources=[s for c in result['cells'].values() for s in c['sources']]
                    if sources and not any(s['page']==number for s in sources):
                        ignored+=1;continue
                    result['focus_page']=number
                    records.append(result)
                attempt.update(status='completed',rows=len(response['records']),complete=response['complete'],ignored_context_rows=ignored)
            except ParseError as exc:
                issues.append(str(exc));attempt.update(status='failed',code=str(exc))
        rows=merge_records(key,records)
        issues.extend(i for r in rows for i in r['issues'])
        if not rows:issues.append('STRUCTURE_NOT_FOUND')
        accepted=bool(rows) and not issues
        # Locations come solely from registered blocks, one source per cell.
        sources=[s for r in rows for c in r['cells'].values() for s in c['sources']]
        source=None
        if sources:
            first=sources[0];boxes=[s['bbox'] for s in sources if s['page']==first['page']]
            source=dict(page=first['page'],bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)])
        fields.append(dict(key=key,label=definition['label'],kind='json',data_type='rows',required=False,
            value=[r['value'] for r in rows] if accepted else None,status='accepted' if accepted else 'needs_review',
            confidence=.9 if accepted else 0.0,source=source,raw_value=None,
            method='vision_records',row_results=rows,issues=list(dict.fromkeys(issues)),
            candidates=[],choices=[]))
    return fields,attempts
