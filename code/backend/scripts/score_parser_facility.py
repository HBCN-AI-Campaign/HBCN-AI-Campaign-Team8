"""Reproduce set8 association decisions from hash-bound parsed artifacts."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.parsing.facility import analyze_facility


def score(gold,root,source_root=None):
    documents=[]
    for index,(filename,sha) in enumerate(gold['documents'].items()):
        if source_root and hashlib.sha256((source_root/filename).read_bytes()).hexdigest()!=sha:
            raise ValueError('SOURCE_HASH_MISMATCH')
        doc=json.loads((root/(Path(filename).stem+'.result.json')).read_text(encoding='utf-8'))
        if doc.get('source_sha256')!=sha:raise ValueError('RESULT_SOURCE_HASH_MISMATCH')
        doc['doc_code']=f"{doc['type_code']}-01"
        documents.append(doc)
    original=deepcopy(documents);initial=analyze_facility(documents);details=[]
    for case in gold['cases']:
        chosen=None
        if case.get('borrower_alias'):
            b=next((b for b in initial['borrowers'] if (b['value'] or {}).get('short_name')==case['borrower_alias']),None)
            a=next((a for a in initial['allocations'] if (a['value'] or {}).get('facility_name')==case['facility_name']
                and (a['value'] or {}).get('borrower_name')==case.get('allocation_borrower',case['borrower_alias'])),None)
            if not b or not a:raise ValueError('EVALUATION_CANDIDATE_MISSING')
            chosen=dict(borrower_id=b['id'],allocation_id=a['id'],reason='工程验收：选择候选，保留原件主体、币种和条款未决，不认定业务适用')
        try:
            result=analyze_facility(documents,chosen)
            codes={i['code'] for i in result['issues']}
            safe=(not case.get('rejected') and result['status']==case['status'] and
                set(case['required_issues'])<=codes and result['comparison'] is None and result['available_balance'] is None
                and result['request']['borrower']['value'] is None and documents==original)
            if case.get('term_expectation'):
                expected=case['term_expectation'];application=result.get('term_application') or {}
                fact=application.get('facts',{}).get('permitted_currencies') or {}
                pages=sorted({s['page'] for s in fact.get('evidence',{}).get('clause_text',{}).get('sources',[])})
                safe=safe and application.get('facility_name')==case['facility_name'] and application.get('status')==expected['status'] and (
                    fact.get('value') or {}).get('currencies')==expected['currencies'] and pages==expected['pages']
            details.append(dict(id=case['id'],correct=bool(safe),status=result['status'],issue_codes=sorted(codes),
                comparison=result['comparison'],available_balance=result['available_balance'],fields_unchanged=documents==original))
        except ValueError as exc:
            correct=bool(case.get('rejected')) and str(exc)=='授信分配与法定借款人不唯一对应，请核实简称和主体'
            details.append(dict(id=case['id'],correct=correct,status='rejected',fields_unchanged=documents==original))
    return dict(scope=gold['scope'],annotation_status=gold['annotation_status'],cases=len(details),
        correct=sum(d['correct'] for d in details),details=details,
        interpretation='只证明当前第八套关联决策和未决保持，不代表授信业务适用已通过或全文条款完整。')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--results',default='parser_data/evaluation/set8')
    parser.add_argument('--gold',default='tests/fixtures/parser_set8_facility.json');parser.add_argument('--source-root')
    args=parser.parse_args();root=Path(args.results)
    gold=json.loads(Path(args.gold).read_text(encoding='utf-8'))
    report=score(gold,root,Path(args.source_root) if args.source_root else None)
    (root/'facility-score.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['correct']!=report['cases']:sys.exit(1)
