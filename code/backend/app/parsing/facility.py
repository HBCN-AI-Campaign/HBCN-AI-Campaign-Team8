"""Receipt-bound borrower/facility associations, separate from extracted facts.

An allocation is a nominal limit, never an available balance. No translation,
currency conversion, fuzzy company matching or borrowing from task metadata.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class FacilitySelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    borrower_id: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    allocation_id: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    reason: str = Field(min_length=1, max_length=4000)


def _identity(value):
    if not isinstance(value, str):return ''
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


def _field(doc, key):
    return next((f for f in doc.get('fields', []) if f['key'] == key), {})


def _value(doc, key):
    field = _field(doc, key)
    return field.get('value') if field.get('status') in {'accepted', 'confirmed'} else None


def _rows(doc, key):
    field = _field(doc, key)
    rows = field.get('row_results') or []
    # Human corrections remain human assertions. Do not reuse old per-cell
    # coordinates for a changed row; its original machine evidence is retained.
    if field.get('status') == 'confirmed':
        rows = [dict(value=v, status='confirmed', issues=[], cells=next(
            (r.get('cells', {}) for r in rows if r.get('value') == v), {}))
            for v in field.get('value') or []]
    result = []
    for index, row in enumerate(rows):
        raw = dict(doc_code=doc['doc_code'], source_sha256=doc.get('source_sha256'),
                   field_key=key, index=index, value=row.get('value'),cells=row.get('cells',{}))
        record_id = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result.append(dict(id=record_id, doc_code=doc['doc_code'], field_key=key,
            row_index=index, value=deepcopy(row.get('value')), status=row.get('status', 'needs_review'),
            cells=deepcopy(row.get('cells', {})), issues=deepcopy(row.get('issues', []))))
    return result


def _aliases(row):
    value = row.get('value') or {}
    return {_identity(value.get(k)) for k in ('name', 'name_local', 'short_name')} - {''}


def analyze_facility(documents, selection=None, task_request=None):
    """Analyze parsed DTOs, or verified DTOs produced by verified_dtos()."""
    fols = [d for d in documents if d['type_code'] == 'FACILITY_LETTER']
    dds = [d for d in documents if d['type_code'] == 'DRAWDOWN_INSTRUCTION']
    issues = []

    def issue(code, message):
        if not any(i['code'] == code for i in issues):issues.append(dict(code=code, message=message))

    borrowers = [r for d in fols for r in _rows(d, 'borrowers')]
    allocations = [r for d in fols for r in _rows(d, 'borrower_allocations')]
    limits = [r for d in fols for r in _rows(d, 'facility_limits')]
    valid_borrowers = [r for r in borrowers if r['status'] in {'accepted', 'confirmed'} and r['value']]
    for allocation in allocations:
        name = _identity((allocation['value'] or {}).get('borrower_name'))
        allocation['borrower_ids'] = [b['id'] for b in valid_borrowers if b['doc_code'] == allocation['doc_code'] and name in _aliases(b)]
    dd = dds[0] if len(dds) == 1 else None
    request = {key: dict(value=_value(dd, key), source=deepcopy(_field(dd, key).get('source')),
                        doc_code=dd['doc_code']) for key in ('borrower', 'facility', 'currency', 'amount')} if dd else {}
    result = dict(schema_version='facility-context/1.0',status='needs_review', issues=issues, drawdown_doc_code=dd['doc_code'] if dd else None,
        request=request, borrowers=borrowers, allocations=allocations, selected_borrower_id=None,
        selected_allocation_id=None, association_method=None, selection=None, nominal_limit=None,
        comparison=None, available_balance=None,term_application=None)
    if not fols:issue('FOL_MISSING', '缺少授信函，无法确定授信依据。')
    elif len(fols)!=1:issue('MULTIPLE_FACILITY_LETTERS', '存在多份授信函，须明确修订、优先顺序及适用文件，不能默认采用第一份。')
    if not dds:issue('DRAWDOWN_MISSING', '缺少提款指令，无法确定本次借款主体和授信。')
    elif len(dds) != 1:issue('MULTIPLE_DRAWDOWNS', '存在多份提款指令，须拆分或明确逐笔关系，不能默认取第一份。')
    if selection:
        selected = FacilitySelection.model_validate(selection).model_dump()
        if not selected['reason'].strip():raise ValueError('授信关联需填写核实依据')
        borrower = next((r for r in valid_borrowers if r['id'] == selected['borrower_id']), None)
        allocation = next((r for r in allocations if r['id'] == selected['allocation_id']), None)
        if not borrower or not allocation:raise ValueError('授信关联候选已失效，请重新核对原件')
        if allocation['status'] not in {'accepted', 'confirmed'} or not allocation['value']:
            raise ValueError('不能确认原文未决或冲突的授信分配')
        if allocation['borrower_ids'] != [borrower['id']]:
            raise ValueError('授信分配与法定借款人不唯一对应，请核实简称和主体')
        result.update(selection=selected, association_method='human_confirmed')
    else:
        name = _identity(_value(dd, 'borrower')) if dd else ''
        matched = [r for r in valid_borrowers if name and name in _aliases(r)]
        borrower = matched[0] if len(matched) == 1 else None
        requested = _identity(_value(dd, 'facility')) if dd else ''
        candidates = [r for r in allocations if borrower and r['borrower_ids'] == [borrower['id']]
            and r['status'] in {'accepted', 'confirmed'} and r['value']
            and _identity(r['value'].get('facility_name')) == requested]
        allocation = candidates[0] if len(candidates) == 1 else None
        if borrower and allocation:result['association_method'] = 'exact_registered_name'
    if not dd or not fols:return result
    if task_request:
        names=_aliases(borrower) if borrower else {_identity(_value(dd,'borrower'))}
        if _identity(task_request.get('borrower')) not in names or not _value(dd,'borrower'):
            issue('TASK_BORROWER_MISMATCH','任务借款主体与已核实的提款主体未对应，选定客户或修改任务名称不能替代核实。')
        if task_request.get('drawdown_currency')!=_value(dd,'currency'):
            issue('TASK_CURRENCY_MISMATCH','任务币种与提款指令已核实币种不一致。')
        try:amount_matches=Decimal(str(task_request.get('drawdown_amount')))==Decimal(str(_value(dd,'amount')))
        except Exception:amount_matches=False
        if not amount_matches:issue('TASK_AMOUNT_MISMATCH','任务金额与提款指令已核实金额不一致。')
    if not _value(dd, 'borrower'):
        issue('DRAWDOWN_BORROWER_UNRESOLVED', '提款指令借款人尚未核实；任务名称或选定客户不能替代原件中的借款主体。')
    elif not borrower:
        issue('BORROWER_NOT_UNIQUE', '提款指令借款人未与FOL法定名称、已登记中文名或简称唯一匹配；不做模糊名称补全。')
    if borrower:
        result['selected_borrower_id'] = borrower['id']
        if _value(dd, 'borrower') and _identity(_value(dd, 'borrower')) not in _aliases(borrower):
            issue('BORROWER_MISMATCH', '所选FOL主体与提款指令借款人不符，填写关联说明不能覆盖主体差异。')
    if not _value(dd, 'facility'):
        issue('DRAWDOWN_FACILITY_UNRESOLVED', '提款指令授信品种尚未核实。')
    if not allocation:
        issue('FACILITY_ASSOCIATION_UNRESOLVED', '授信品种及主体分配尚未唯一关联；中英文名称差异须对照原件明确确认对应关系。')
        return result
    result['selected_allocation_id'] = allocation['id']
    fol = next(d for d in fols if d['doc_code'] == allocation['doc_code'])
    for key, code, message in [
        ('borrowers', 'BORROWER_REGISTER_INCOMPLETE', 'FOL借款人名单仍有未决项，须核实名单完整性及别名。'),
        ('borrower_allocations', 'ALLOCATION_REGISTER_INCOMPLETE', 'FOL主体分配表仍有未决项，所选明细不能代表完整条款已核实。'),
    ]:
        if _field(fol, key).get('status') not in {'accepted', 'confirmed'}:issue(code, message)
    chosen_limits = [r for r in limits if r['doc_code'] == allocation['doc_code'] and r['value'] and
        _identity(r['value'].get('facility_name')) == _identity(allocation['value'].get('facility_name'))]
    if len(chosen_limits) != 1 or chosen_limits[0]['status'] not in {'accepted', 'confirmed'}:
        issue('FACILITY_LIMIT_CONFLICT', '所选授信品种的组额度缺失或存在冲突，不能用较大值覆盖另一处条款。')
    else:
        group = chosen_limits[0]['value']; allotted = allocation['value']
        if group['currency'] != allotted['currency']:
            issue('GROUP_ALLOCATION_CURRENCY_MISMATCH', '组额度与主体分配的计价币种不同，须核实条款和折算依据。')
        elif Decimal(allotted['amount']) > Decimal(group['amount']):
            issue('ALLOCATION_EXCEEDS_GROUP', '主体分配额大于该组额度，须核实原件，不能把多个额度相加。')
    limit = allocation['value']
    result['nominal_limit'] = dict(amount=limit['amount'], currency=limit['currency'],
        facility_name=limit['facility_name'], doc_code=allocation['doc_code'], cells=allocation['cells'])
    currency = _value(dd, 'currency'); amount = _value(dd, 'amount')
    if not currency or amount is None:issue('DRAWDOWN_AMOUNT_UNRESOLVED', '提款币种或金额尚未核实，不能以零参与比较。')
    elif currency != limit['currency']:
        issue('CROSS_CURRENCY_COMPARISON', f"提款币种{currency}与额度计价币种{limit['currency']}不同，需核实允许币种及汇率折算依据，暂不比较数字大小。")
    else:
        result['comparison'] = 'within_nominal_limit' if Decimal(amount) <= Decimal(limit['amount']) else 'exceeds_nominal_limit'
    if _field(fol,'facility_terms'):
        from .term_facts import derive_term_facts,applicable_terms,date_span_observation
        derived=derive_term_facts(_rows(fol,'facility_terms'),_field(fol,'facility_terms').get('status'),fol.get('issues'))
        application=applicable_terms(derived,limit['facility_name'])
        application['doc_code']=fol['doc_code']
        application['date_span']=date_span_observation(_value(dd,'drawdown_date'),_value(dd,'maturity_date'))
        result['term_application']=application
        if application['status']!='accepted':
            issue('FACILITY_TERMS_UNVERIFIED','所选授信附表条款尚未完整核实；已读到的单项事实不能替代完整条款和范围。')
        permitted=application.get('facts',{}).get('permitted_currencies',{})
        allowed=(permitted.get('value') or {}).get('currencies') if permitted.get('status')=='accepted' else None
    else:
        allowed = _value(fol, 'allowed_currencies')
    if not isinstance(allowed, list) or currency not in allowed:
        issue('PERMITTED_CURRENCY_UNVERIFIED', '本次提款币种的授信条款依据尚未核实；额度计价币种不等于全部允许提款币种。')
    if fol.get('issues') or dd.get('issues'):issue('DOCUMENT_INCOMPLETE', '原件页面或解析过程不完整，须先核实完整材料。')
    if not issues:result['status'] = 'ready'
    return result


def verified_dtos(documents):
    result = []
    for doc in documents:
        fields = doc.fields or {}; parsing = fields.get('_parsing') or {}
        verified = []
        for key, audit in parsing.get('fields', {}).items():
            machine = deepcopy(audit['machine'])
            unchanged = fields.get(key) == audit.get('final_value')
            machine.update(value=fields.get(key), status=audit.get('status') if unchanged else 'needs_review')
            verified.append(machine)
        result.append(dict(doc_code=doc.doc_code, type_code=doc.type_code.value if hasattr(doc.type_code, 'value') else doc.type_code,
            source_sha256=parsing.get('source_sha256'), fields=verified, issues=parsing.get('document_errors', [])))
    return result


def saved_selection(documents):
    found = [((d.fields or {}).get('_parsing') or {}).get('facility_context', {}).get('selection') for d in documents]
    selected = [s for s in found if s]
    if selected and any(s != selected[0] for s in selected):raise ValueError('授信关联记录不一致')
    return selected[0] if selected else None


def attach_facility_context(documents, selection, owner_id, task_request=None):
    if not any(d.type_code == 'FACILITY_LETTER' for d in documents):
        if selection:raise ValueError('缺少授信函，不能提交授信关联')
        return
    from .jobs import now
    context = analyze_facility(verified_dtos(documents), selection, task_request)
    context['task_request']=deepcopy(task_request)
    context.update(confirmed_by=owner_id if selection else None, confirmed_at=now() if selection else None)
    for doc in documents:
        if doc.type_code == 'FACILITY_LETTER':doc.fields['_parsing']['facility_context'] = deepcopy(context)
