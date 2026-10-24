"""Typed business rows and per-cell provenance; no inferred scalar aggregation."""
from copy import deepcopy
from typing import Annotated
import re
import unicodedata

from pydantic import BaseModel,BeforeValidator,ConfigDict,Field,ValidationError

from .normalization import compact,equivalent,normalize


Money=Annotated[str,BeforeValidator(lambda v:normalize(v,'money'))]
Currency=Annotated[str,BeforeValidator(lambda v:normalize(v,'currency_code'))]
def _text(value):
    if not isinstance(value,str):raise ValueError('text required')
    return value.strip()


def column_value(value,column):
    if column in ROW_TYPES:return normalize(value,ROW_TYPES[column])
    text=unicodedata.normalize('NFKC',_text(value))
    if column in {'name_local','short_name'}:
        # These columns exclude the printed wrapping label parentheses, but retain
        # parentheses that are part of the legal name or alias itself.
        if text.startswith('(') and text.endswith(')'):
            depth=0;outer=True
            for char in text[:-1]:
                depth+=(char=='(')-(char==')')
                if depth==0:outer=False;break
            if outer:text=text[1:-1].strip()
        elif text.endswith(')') and text.count(')')==text.count('(')+1:text=text[:-1].strip()
        elif text.startswith('(') and text.count('(')==text.count(')')+1:text=text[1:].strip()
    if column=='facility_name':
        text=re.sub(r'^\s*\((?:\d+|[a-zA-Z])\)\s*','',text).rstrip(' :：')
        if compact(text)=='anaggregatefacilityamountof':text='aggregate Facility amount'
    return text


Text=Annotated[str,BeforeValidator(_text),Field(min_length=1,max_length=4000)]
Alias=Annotated[Text,BeforeValidator(lambda v:column_value(v,'short_name'))]
LocalName=Annotated[Text,BeforeValidator(lambda v:column_value(v,'name_local'))]
FacilityName=Annotated[Text,BeforeValidator(lambda v:column_value(v,'facility_name'))]


class BusinessRow(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Borrower(BusinessRow):
    name: Text
    short_name: Alias|None=None
    name_local: LocalName|None=None


class FacilityLimit(BusinessRow):
    facility_name: FacilityName
    amount: Money
    currency: Currency


class BorrowerAllocation(FacilityLimit):
    borrower_name: Text


class FacilityTerm(BusinessRow):
    facility_name: FacilityName
    clause_heading: Text
    clause_text: Annotated[str,BeforeValidator(_text),Field(min_length=1,max_length=16000)]


class InvoiceItem(BusinessRow):
    line_no: Annotated[Text, Field(pattern=r'^[1-9][0-9]{0,3}$')]
    description: Text
    quantity: Annotated[str, BeforeValidator(lambda v:normalize(v,'decimal'))]
    unit: Annotated[str, BeforeValidator(lambda v:normalize(v,'unit'))]
    unit_price: Annotated[str, BeforeValidator(lambda v:normalize(v,'decimal'))]
    amount: Money
    currency: Currency


ROW_MODELS={'borrowers':Borrower,'facility_limits':FacilityLimit,'borrower_allocations':BorrowerAllocation,
            'facility_terms':FacilityTerm, 'numbered_invoice_items':InvoiceItem}
ROW_TYPES={'amount':'money','currency':'currency_code','quantity':'decimal',
           'unit_price':'decimal','unit':'unit'}
ROW_KEYS={'borrowers':('name',),'facility_limits':('facility_name',),
          'borrower_allocations':('facility_name','borrower_name'),
          'facility_terms':('facility_name','clause_heading'), 'numbered_invoice_items':('line_no',)}
PROVENANCE={'block_ids','raw_values','cell_sources'}


def row_schema(key):
    return ROW_MODELS[key].model_json_schema()


def normalize_record(row,key):
    if not isinstance(row,dict):raise ValueError('invalid business row')
    values={k:v for k,v in row.items() if k not in PROVENANCE}
    try:normalized=ROW_MODELS[key].model_validate(values).model_dump(exclude_none=True)
    except ValidationError:raise ValueError('invalid business row') from None
    return {**normalized,**{k:deepcopy(v) for k,v in row.items() if k in PROVENANCE}}


def normalize_records(value,key):
    if not isinstance(value,list) or len(value)>200:raise ValueError('invalid business rows')
    return [normalize_record(row,key) for row in value]


def validate_record(row,key,pages):
    by_id={b.id:(p,b) for p in pages for b in p.blocks}
    issues=[];values={};evidence={};valid_schema=True
    try:normalized=normalize_record(row,key)
    except ValueError:
        # A malformed amount must not hide the party and its registered source.
        # Partial cells are display-only; the row never obtains a typed value.
        valid_schema=False;issues.append('INVALID_ROW_SCHEMA')
        normalized={k:v for k,v in (row.items() if isinstance(row,dict) else [])
                    if k in ROW_MODELS[key].model_fields and isinstance(v,str)}
    if not isinstance(row,dict):row={}
    cell_sources=row.get('cell_sources',{})
    if not isinstance(cell_sources,dict):cell_sources={}
    for column,value in normalized.items():
        if column in PROVENANCE:continue
        source=cell_sources.get(column)
        if not isinstance(source,dict):source={}
        ids=source.get('block_ids',[]);raw=source.get('raw_value')
        cell_issues=[]
        if not isinstance(ids,list) or not ids or not all(isinstance(i,str) and i in by_id for i in ids):
            cell_issues.append('CELL_EVIDENCE_MISSING');ids=[]
        text=' '.join(by_id[i][1].text for i in ids)
        grounded=isinstance(raw,str) and bool(raw.strip()) and compact(raw) in compact(text)
        if grounded and (column in {'line_no','quantity','unit_price','amount'}):
            # A quote of "1" inside "14", or "2,000" inside "12,000",
            # cannot establish a numeric cell even when the digits align.
            grounded=bool(re.search(r'(?<![0-9])(?<![0-9][.,])'+re.escape(compact(raw))+r'(?![0-9]|[.,][0-9])',compact(text)))
        if not grounded:
            cell_issues.append('CELL_QUOTE_NOT_GROUNDED')
        else:
            try:
                if not equivalent(column_value(raw,column),value):
                    cell_issues.append('CELL_VALUE_SOURCE_MISMATCH')
            except (ValueError,TypeError):cell_issues.append('CELL_VALUE_SOURCE_MISMATCH')
        if ids and min(by_id[i][1].score for i in ids)<.85:cell_issues.append('LOW_OCR_SCORE')
        evidence[column]=dict(value=value,raw_value=raw,issues=cell_issues,
            sources=[dict(block_id=i,page=by_id[i][0].number,bbox=by_id[i][1].bbox,text=by_id[i][1].text,
                          method=by_id[i][1].method,score=by_id[i][1].score) for i in ids])
        issues.extend(cell_issues);values[column]=value
    if 'amount' in evidence and 'currency' in evidence:
        amount_raw=evidence['amount'].get('raw_value')
        explicit=re.match(r'^\s*(USD|CNY|RMB|EUR|HKD|GBP|JPY|人民币|美元|欧元|港币|英镑|日元)',amount_raw if isinstance(amount_raw,str) else '',re.I)
        if explicit and normalize(explicit.group(1),'currency_code')!=values['currency']:
            issues.append('AMOUNT_CURRENCY_MISMATCH')
    # Keep typed values and their literal source quotes; coordinates are server-owned.
    values['cell_sources']=deepcopy(cell_sources)
    values['block_ids']=list(dict.fromkeys(s['block_id'] for e in evidence.values() for s in e['sources']))
    if key=='borrower_allocations':
        names=evidence.get('borrower_name',{}).get('sources',[])
        amounts=evidence.get('amount',{}).get('sources',[])
        # Borrower and its amount must be in the same physical table row; the
        # facility heading may legitimately be on the previous page.
        aligned=bool(names and amounts) and any(
            n['page']==a['page'] and max(n['bbox'][1],a['bbox'][1])<=min(n['bbox'][3],a['bbox'][3])+.003
            for n in names for a in amounts)
        if not aligned:issues.append('ALLOCATION_ROW_ALIGNMENT_UNPROVEN')
    if key=='numbered_invoice_items':
        # Description can continue on the next page, and unit/currency can be
        # in the table header. The row number and three numeric cells must align.
        columns=[evidence.get(k,{}).get('sources',[]) for k in ('line_no','quantity','unit_price','amount')]
        anchors=columns[0]
        aligned=bool(anchors) and all(any(
            a['page']==s['page'] and max(a['bbox'][1],s['bbox'][1]) <= min(a['bbox'][3],s['bbox'][3])+.003
            for a in anchors for s in sources) for sources in columns[1:])
        if not aligned:issues.append('INVOICE_ROW_ALIGNMENT_UNPROVEN')
    return dict(value=values if valid_schema else None,status='accepted' if not issues else 'needs_review',issues=list(dict.fromkeys(issues)),
                original=deepcopy(row),cells=evidence)


def merge_records(key,records):
    """Deduplicate exact repeats; different rows append, contradictory cells conflict.

    Two chunks with different sets of rows are not two competing scalar values.
    No missing cell is filled from another row or document.
    """
    merged=[]
    for record in records:
        value=record.get('value')
        identity=tuple(compact(value.get(k,'')) for k in ROW_KEYS[key]) if value else None
        duplicate=next((r for r in merged if value and r.get('value') and
            equivalent({k:v for k,v in value.items() if k not in PROVENANCE},
                       {k:v for k,v in r['value'].items() if k not in PROVENANCE})),None)
        if duplicate:
            if duplicate['status']=='needs_review' and record['status']=='accepted':
                previous=deepcopy(duplicate);duplicate.clear();duplicate.update(deepcopy(record))
                duplicate['identity']=list(identity)
                duplicate['repeated_evidence']=[previous]
            else:duplicate.setdefault('repeated_evidence',[]).append(deepcopy(record))
            continue
        current=deepcopy(record)
        current['identity']=list(identity) if identity else None
        for previous in merged:
            if identity and previous.get('identity')==list(identity):
                for r in (previous,current):
                    r['status']='conflict'
                    if 'CONFLICTING_ROW_VALUES' not in r['issues']:r['issues'].append('CONFLICTING_ROW_VALUES')
        merged.append(current)
    return merged
