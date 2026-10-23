"""Score independently annotated typed candidates; never a business approval metric."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.parsing.term_facts import derive_term_facts,applicable_terms


def score(gold,result):
    if result.get('source_sha256')!=gold['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
    field=next((f for f in result['fields'] if f['key']=='facility_terms'),{})
    # Rebuild from source rows, ignoring any saved projection entirely.
    derived=derive_term_facts(field.get('row_results',[]),field.get('status'),result.get('issues'))
    details=[]
    for expected in gold['facilities']:
        application=applicable_terms(derived,expected['name']);facts=application['facts'];checks={}
        ccy=facts.get('permitted_currencies',{});tenor=facts.get('loan_tenor',{})
        cv=ccy.get('value');tv=tenor.get('value');wanted=expected['tenor']
        checks['scope_safe']=not gold['scope_must_remain_unresolved'] or application['status']=='needs_review'
        checks['currency']=cv is None if expected['currencies'] is None else (
            ccy.get('status')=='accepted' and bool(cv) and cv['currencies']==expected['currencies'] and
            cv.get('aggregate_limit_currency')==expected['limit_currency'])
        checks['tenor']=tv is None if wanted is None else (tenor.get('status')=='accepted' and bool(tv) and
            tv['standard_periods']==[dict(count=n,unit='months') for n in wanted['standard_months']] and
            tv['absolute_maximum']==wanted['maximum'] and
            tv['other_period_requires_lender_agreement']==wanted['other_requires_agreement'] and
            tv['maximum_includes_extensions_and_rollovers']==wanted['includes_extensions'])
        if expected.get('pages'):
            checks['currency_sources']=sorted({s['page'] for s in ccy.get('evidence',{}).get('clause_text',{}).get('sources',[])})==expected['pages']
            if wanted is not None:
                checks['tenor_sources']=sorted({s['page'] for s in tenor.get('evidence',{}).get('clause_text',{}).get('sources',[])})==expected['pages']
        if expected.get('parent'):
            checks['subfacility_scope']=application.get('schedule_name')==expected['parent'] and application.get('scope_method')=='explicit_named_subfacility'
        checks['no_invented_rate']='interest_rate' not in facts
        details.append(dict(facility=expected['name'],checks=checks,correct=all(checks.values())))
    no_extra=len(derived['facilities'])==len(gold['facilities'])
    return dict(metric='typed candidate facts, scope and evidence only; not business approval',
        expected_facilities=len(details),correct_candidates=sum(d['correct'] for d in details),
        scope_unresolved=sum(a['status']=='needs_review' for a in derived['facilities']),
        no_extra_facilities=no_extra,passed=no_extra and all(d['correct'] for d in details),details=details)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold',default='tests/fixtures/parser_set8_term_facts.json')
    p.add_argument('--result',default='parser_data/evaluation/set8/FOL-编造完.result.json')
    p.add_argument('--output',default='parser_data/evaluation/set8/term-facts-score.json')
    args=p.parse_args()
    report=score(json.loads(Path(args.gold).read_text(encoding='utf8')),json.loads(Path(args.result).read_text(encoding='utf8')))
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
