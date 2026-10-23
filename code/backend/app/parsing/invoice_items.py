"""Numbered multi-page invoice adapter using existing typed cell validation."""
from .contracts import ParseError
from .records import row_schema, validate_record, merge_records
from .normalization import compact


def extract_invoice_items(pages, semantic, cfg, progress, *, document_errors=(), expected_rows=None, scope_issues=(), context_note=None,
                          expected_description_sources=None, document_total_pages=None):
    spec=dict(key='line_items',label='货物明细', row_schema=row_schema('numbered_invoice_items'),
              cell_source_keys=['line_no','description','quantity','unit','unit_price','amount','currency'],
              note='仅有原件明确行号的商品行；不含合计。保留原文描述及跨页续文；不得计算、更正或用合计反推商品行。')
    if context_note:spec['note']+=' '+context_note
    records=[];attempts=[];issues=list(scope_issues)
    extract=getattr(semantic,'extract_records',None)
    if not callable(extract):issues.append('STRUCTURE_PROVIDER_NOT_AVAILABLE')
    for index,page in enumerate(pages if callable(extract) else []):
        if index>=cfg.max_structure_calls:
            issues.append('STRUCTURE_CALL_BUDGET_EXCEEDED');break
        # Include both neighbours: a final row description can continue on the
        # next page, while the header for the first row may be on the previous.
        context=pages[max(0,index-1):index+2]
        attempt=dict(key='line_items',focus_page=page.number,context_pages=[p.number for p in context],status='started')
        attempts.append(attempt)
        try:
            progress(stage='invoice_items',page=page.number,total_pages=document_total_pages or len(pages))
            focus_spec=spec
            following=[r for r in (expected_rows or []) if r['page']==page.number+1]
            if following:
                first_y=min(r['bbox'][1] for r in following)
                leading=[s for s in (expected_description_sources or [])
                         if s['page']==page.number+1 and s['bbox'][3]<first_y]
                if leading:
                    # These are actual input blocks above the next page's first
                    # number, not an expected value or an automatic row merge.
                    focus_spec=dict(spec,possible_continuation_sources=leading,
                        note=spec['note']+' possible_continuation_sources为下一页首个行号前的实际描述块。请对照两页图像确认是否续接焦点页末行；属于续文时必须完整引用，不确定则complete=false。不得仅因该提示而拼接。')
            response=extract(context,focus_spec,focus_page=page.number)
            if not isinstance(response,dict) or not isinstance(response.get('records'),list) or type(response.get('complete')) is not bool:
                raise ParseError('RECORDS_INVALID_RESPONSE')
            if len(response['records'])>200:raise ParseError('RECORDS_ROW_LIMIT')
            if not response['complete']:issues.append('STRUCTURE_PAGE_INCOMPLETE')
            ignored=0
            for row in response['records']:
                validated=validate_record(row,'numbered_invoice_items',context)
                anchors=validated['cells'].get('line_no',{}).get('sources',[])
                if anchors and not any(s['page']==page.number for s in anchors):
                    ignored+=1;continue
                validated['focus_page']=page.number;records.append(validated)
            attempt.update(status='completed',rows=len(response['records']),complete=response['complete'],ignored_context_rows=ignored)
        except ParseError as exc:
            issues.append(str(exc));attempt.update(status='failed',code=str(exc))
    rows=merge_records('numbered_invoice_items',records)
    issues.extend(i for r in rows for i in r['issues'])
    if expected_rows is not None:
        expected={(r['page'],r['line_no']):r for r in expected_rows}
        observed=[]
        for row in rows:
            value=row.get('value') or {}
            anchors=row['cells'].get('line_no',{}).get('sources',[])
            identity=(row['focus_page'],value.get('line_no'))
            observed.append(identity)
            native=expected.get(identity)
            def overlaps(source):
                if not native or source['page']!=native['page']:return False
                a=source['bbox'];b=native['bbox']
                return (max(a[0],b[0])<=min(a[2],b[2])+.003 and
                        max(a[1],b[1])<=min(a[3],b[3])+.003)
            if not native or not any(overlaps(s) for s in anchors):
                issues.append('TABLE_ROW_ANCHOR_MISMATCH')
        if set(observed)!=set(expected) or len(observed)!=len(expected_rows):
            issues.append('TABLE_ROW_COVERAGE_INCOMPLETE')
    uncovered=[]
    if expected_description_sources is not None:
        for original in expected_description_sources:
            claims=[r['cells'].get('description',{}) for r in rows]
            # Merely citing a block with a partial quote is not complete cell
            # evidence. Every original description block must be fully quoted.
            if not any(original['block_id'] in {s['block_id'] for s in c.get('sources',[])} and
                       compact(original['text']) in compact(c.get('raw_value') or '') for c in claims):
                uncovered.append(original)
        if uncovered:issues.append('TABLE_DESCRIPTION_COVERAGE_INCOMPLETE')
    if not rows:issues.append('STRUCTURE_NOT_FOUND')
    numbers=sorted(int(r['value']['line_no']) for r in rows if r.get('value'))
    if numbers and numbers!=list(range(1,max(numbers)+1)):
        issues.append('INVOICE_ROW_SEQUENCE_INCOMPLETE')
    if document_errors:issues.append('DOCUMENT_INCOMPLETE')
    accepted=bool(rows) and not issues
    sources=[s for r in rows for c in r['cells'].values() for s in c['sources']]
    source=None
    if sources:
        first=sources[0];boxes=[s['bbox'] for s in sources if s['page']==first['page']]
        source=dict(page=first['page'],bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)])
    field=dict(key='line_items',label='货物明细',kind='json',data_type='rows',required=False,
               value=[r['value'] for r in rows] if accepted else None,
               status='accepted' if accepted else 'needs_review',confidence=.9 if accepted else 0.0,
               source=source,raw_value=None,method='vision_records',row_results=rows,
               issues=list(dict.fromkeys(issues)),candidates=[],choices=[])
    if expected_description_sources is not None:field['uncovered_description_sources']=uncovered
    return field,attempts
