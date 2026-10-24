"""Versioned FOL business-template projection, rebuilt from receipt-owned rows.

Not a general contract parser. Only full, evidenced clauses match templates;
unknown wording and incomplete registers remain explicit review gaps.
"""
from copy import deepcopy
from datetime import date
import re
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field

from .normalization import compact
from .records import column_value

VERSION='facility-term-facts/1.0'


class StrictValue(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')


class Period(StrictValue):
    count: int=Field(gt=0,le=1200)
    unit: Literal['days','months']


class CurrencyScope(StrictValue):
    currencies: list[Literal['CNY','USD','EUR','HKD','GBP','JPY']]=Field(min_length=1)
    aggregate_limit_currency: Literal['CNY','USD','EUR','HKD','GBP','JPY']|None=None
    aggregate_limit_condition: str


class TenorPolicy(StrictValue):
    standard_periods: list[Period]=Field(default_factory=list)
    other_period_requires_lender_agreement: bool|None=None
    absolute_maximum: Period|None=None
    maximum_includes_extensions_and_rollovers: bool|None=None
    maximum_scope: Literal['each_loan','each_utilization','each_draft']
    instrument_maxima: dict[str,Period]=Field(default_factory=dict)


REVOLVER='''(a) Utilization may be made in either {ccy1} or {ccy2} provided that {limit_ccy} equivalent of the aggregate
outstanding Loans shall in no time exceed the amount of this Facility.
(b) The Borrower may borrow a Loan by delivering a Utilization Request in form and substance
satisfactory to the Lender not later than {notice} Business Days prior to the proposed Utilization Date.
(c) The term of each Loan will be {period1}, {period2} or {period3} months or such other period as agreed by the Lender. The
term of a Loan (including any extension or rollover) shall not exceed {maximum} months in any case.'''

IMPORT='''1. Utilization may be made in either {ccy1} or {ccy2} provided that {limit_ccy} equivalent of the aggregate
outstanding Utilizations shall in no time exceed the amount of this Facility.
2. Facility for Clean Import Loan ("CIL")
The tenor of each Utilization of this Facility shall not exceed {cil_days} days.
3. Facility for Reimbursement Finance
The tenor of each Utilization of this Facility shall not exceed {reimbursement_days} days.
The Borrower shall submit a Utilization Request in form and substance satisfactory to the Lender, and shall,
together with the Utilization Request or promptly upon request by the Lender at its sole discretion before
or after the Utilization, provide the Lender with the relevant transaction documents, including without
limitation copies of invoices, sales contracts, purchase orders and other trading documents.
The Borrower represents and warrants that any required import or export licenses applicable to each
underlying transaction have been obtained and certifies its compliance in all material respects with foreign
and domestic laws and regulations pertaining to each jurisdiction in which it operates and to each
instrument it instructs the Lender to issue and the subject matter of such instrument, including, if
applicable, the relevant shipment and financing of the goods.'''

ACCEPTANCE='''1. Maximum Tenor
The Lender may accept an RMB bank acceptance draft issued by the Borrower with usance
period up to (in case of a paper-based RMB bank acceptance draft) {paper_months} months or (in case of an
electronic RMB bank acceptance draft) {electronic_months} months from the date of that commercial draft.
2. Settlement
The Lender is authorized to debit any account maintained by the Borrower with AA Bank (China) Company Limited or any of its branches or offices for payment under or in relation to each
commercial draft accepted by the Lender under this Facility.
3. Application
The Borrower may request a Utilization of this Facility by delivering a Utilization Request in form and
substance satisfactory to the Lender. The Borrower acknowledges that the Utilization Request or
Application Form for Acceptance sent by the Borrower via E-Channels or Electronic Commercial Draft
System is the true and valid application made by the Borrower and is bound by the Borrower. The
Borrower further acknowledges that the contract, invoice, certification, confirmation and any other
documents (whether it is affixed with the borrower's company chop or not) submitted via E-Channels
to prove the genuine underlying transaction in respect of the draft are submitted or made by the Borrower,
and can be deemed as a true copy certified by the Borrower.
4. Other Conditions
Each Utilization Request of this Facility must be accompanied by the relevant VAT invoice,
commercial contract or other documentary proof acceptable to the Lender relating to the
underlying trade transaction.
Any commercial drafts presented for the Lender's acceptance must be properly and fully completed,
and no alteration is allowed to the amount, date and beneficiary name appearing on that commercial draft.'''


def _match(template,text):
    pattern=re.escape(compact(template))
    for key in re.findall(r'\{(\w+)\}',template):
        values='(?:rmb|cny|usd|eur|hkd|gbp|jpy)' if key in {'ccy1','ccy2','limit_ccy'} else r'[1-9]\d{0,3}'
        pattern=pattern.replace(re.escape('{'+key+'}'),f'(?P<{key}>{values})')
    match=re.fullmatch(pattern,compact(text))
    return match.groupdict() if match else None


def _currency(value):
    return 'CNY' if value.casefold()=='rmb' else value.upper()


def _proof(row):
    """Row status alone is insufficient, especially after manual corrections."""
    value=row.get('value')
    if row.get('status') not in {'accepted','confirmed'} or row.get('issues') or not isinstance(value,dict):return False
    cells=row.get('cells')
    if not isinstance(cells,dict):return False
    for key in ('facility_name','clause_heading','clause_text'):
        cell=cells.get(key,{})
        if not isinstance(cell,dict):return False
        sources=cell.get('sources') or []
        if cell.get('issues') or not sources or compact(cell.get('value'))!=compact(value.get(key)):return False
        try:
            raw=cell['raw_value'];text=' '.join(s['text'] for s in sources)
            if compact(column_value(raw,key))!=compact(value[key]):return False
            if key=='clause_text' and compact(raw)!=compact(text):return False
            if key!='clause_text' and compact(raw) not in compact(text):return False
            if any(s['score']<.85 or len(s['bbox'])!=4 or not 0<=s['bbox'][0]<s['bbox'][2]<=1 or
                   not 0<=s['bbox'][1]<s['bbox'][3]<=1 or type(s['page']) is not int or s['page']<1 for s in sources):return False
        except (KeyError,TypeError,ValueError):return False
    return True


def _fact(row,value=None,issue=None):
    proven=bool(row) and _proof(row) and issue is None
    return dict(status='accepted' if proven else 'needs_review',value=deepcopy(value) if proven else None,
        issues=[] if proven else [issue or 'TERMS_CLAUSE_UNVERIFIED'],
        clause_heading=(row or {}).get('value',{}).get('clause_heading') if (row or {}).get('value') else None,
        evidence=deepcopy((row or {}).get('cells',{})) if proven else {})


def derive_term_facts(rows,collection_status,document_errors=None):
    """Return readonly facts for all schedule names; no source rows are mutated."""
    groups={}
    for row in rows:
        value=row.get('value') or {}
        name=value.get('facility_name')
        if isinstance(name,str) and name.strip():groups.setdefault(name,[]).append(row)
    derived=[]
    for name,group in groups.items():
        issues=[]
        if collection_status not in {'accepted','confirmed'}:issues.append('TERMS_REGISTER_INCOMPLETE')
        if document_errors:issues.append('DOCUMENT_INCOMPLETE')
        if any(not isinstance(r.get('value'),dict) or not r['value'].get('facility_name') for r in rows):
            issues.append('TERMS_REGISTER_INVALID')
        by_heading={}
        for row in group:by_heading.setdefault(compact(row['value'].get('clause_heading')),[]).append(row)
        if any(len(rs)!=1 for rs in by_heading.values()):issues.append('TERMS_DUPLICATE_CLAUSE_HEADING')
        facts={}
        for key,heading in [('purpose','Purpose'),('interest','Interest'),('default_interest','Default Interest'),
                            ('fees','Fees'),('disbursement','Disbursement of Loan Proceeds')]:
            matches=by_heading.get(compact(heading),[])
            if len(matches)==1:facts[key]=_fact(matches[0],dict(clause_text=matches[0]['value']['clause_text']))
        matches=by_heading.get(compact('Utilization'),[])
        row=matches[0] if len(matches)==1 else None
        children=[];method=None
        facts['permitted_currencies']=_fact(row,issue='TERMS_TEMPLATE_UNRECOGNIZED')
        facts['loan_tenor']=_fact(row,issue='TERMS_TEMPLATE_UNRECOGNIZED')
        if row and _proof(row):
            text=row['value']['clause_text']
            rev=_match(REVOLVER,text);imp=_match(IMPORT,text);acc=_match(ACCEPTANCE,text)
            match=rev or imp
            try:
                if match:
                    limit_ccy=_currency(match['limit_ccy'])
                    currency=CurrencyScope(currencies=list(dict.fromkeys([_currency(match['ccy1']),_currency(match['ccy2'])])),
                        aggregate_limit_currency=limit_ccy,
                        aggregate_limit_condition='Aggregate outstanding utilization/loans must not exceed the facility amount in its stated equivalent currency; conversion basis is not supplied here.')
                    facts['permitted_currencies']=_fact(row,currency.model_dump())
                if rev:
                    standard=[Period(count=int(rev[k]),unit='months') for k in ('period1','period2','period3')]
                    maximum=Period(count=int(rev['maximum']),unit='months')
                    if len({p.count for p in standard})!=3 or any(p.count>maximum.count for p in standard):raise ValueError('inconsistent tenor')
                    facts['loan_tenor']=_fact(row,TenorPolicy(standard_periods=standard,
                        other_period_requires_lender_agreement=True,absolute_maximum=maximum,
                        maximum_includes_extensions_and_rollovers=True,maximum_scope='each_loan').model_dump())
                    method='registered_revolver_utilization/1.0'
                elif imp:
                    for child,key in [('Facility for Clean Import Loan','cil_days'),('Facility for Reimbursement Finance','reimbursement_days')]:
                        policy=TenorPolicy(absolute_maximum=Period(count=int(imp[key]),unit='days'),maximum_scope='each_utilization')
                        children.append((child,_fact(row,policy.model_dump())))
                    # The parent has distinct product limits; do not invent a
                    # single loan tenor when their numbers happen to agree.
                    facts['loan_tenor']=_fact(row,issue='TERMS_SUBFACILITY_REQUIRED')
                    method='registered_import_utilization/1.0'
                elif acc:
                    facts['permitted_currencies']=_fact(row,CurrencyScope(currencies=['CNY'],
                        aggregate_limit_condition='RMB bank acceptance draft; draft-specific conditions remain in the complete clause.').model_dump())
                    facts['loan_tenor']=_fact(row,TenorPolicy(maximum_scope='each_draft',instrument_maxima={
                        'paper':Period(count=int(acc['paper_months']),unit='months'),
                        'electronic':Period(count=int(acc['electronic_months']),unit='months')}).model_dump())
                    method='registered_acceptance_utilization/1.0'
            except ValueError:
                facts['permitted_currencies']=_fact(row,issue='TERMS_TYPED_VALUE_INVALID')
                facts['loan_tenor']=_fact(row,issue='TERMS_TYPED_VALUE_INVALID');children=[];method=None
        elif row:
            facts['permitted_currencies']=_fact(row)
            facts['loan_tenor']=_fact(row)
        entry=dict(facility_name=name,schedule_name=name,scope_method='exact_schedule_name',
            status='accepted' if not issues else 'needs_review',issues=issues,facts=facts,mapping_method=method)
        derived.append(entry)
        for child,tenor in children:
            child_entry=deepcopy(entry);child_entry.update(facility_name=child,scope_method='explicit_named_subfacility')
            child_entry['facts']['loan_tenor']=tenor;derived.append(child_entry)
    return dict(schema_version=VERSION,facilities=derived)


def applicable_terms(derived,facility_name):
    matches=[r for r in derived['facilities'] if compact(r['facility_name'])==compact(facility_name)]
    if len(matches)!=1:return dict(status='needs_review',facility_name=facility_name,
        issues=['TERMS_FACILITY_NOT_UNIQUE'],facts={},schema_version=VERSION)
    return dict(deepcopy(matches[0]),schema_version=VERSION)


def date_span_observation(drawdown_date,maturity_date):
    """Calendar date subtraction is an observation, not a contractual tenor."""
    try:
        start=date.fromisoformat(drawdown_date);end=date.fromisoformat(maturity_date)
    except (ValueError,TypeError):return dict(status='needs_review',elapsed_days=None,issue='TENOR_DATES_UNVERIFIED')
    days=(end-start).days
    return dict(status='needs_review',drawdown_date=drawdown_date,maturity_date=maturity_date,elapsed_days=days,
        issue='TENOR_DATE_ORDER_INVALID' if days<0 else 'TENOR_CONVENTION_UNVERIFIED',
        note='Calendar difference only; loan tenor, interest period, inclusion of dates, extension origin and business-day adjustment are separate facts.')
