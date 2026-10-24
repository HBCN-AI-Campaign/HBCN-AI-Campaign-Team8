"""Independent clause anchor/page checks, NOT full literal/interpretation accuracy."""
import argparse
import json
from pathlib import Path
import re
import unicodedata


def compact(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).casefold()


def score(gold,result):
    if result.get('source_sha256')!=gold['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
    field=next((f for f in result['fields'] if f['key']=='facility_terms'),{})
    rows=field.get('row_results',[]);details=[];unsafe=[];matched=set()
    for expected in gold['clauses']:
        matches=[]
        for i,row in enumerate(rows):
            value=row.get('value') or {k:c.get('value') for k,c in row.get('cells',{}).items()}
            if compact(value.get('facility_name'))!=compact(gold['facilities'][expected['facility']]):continue
            if compact(value.get('clause_heading'))!=compact(expected['heading']):continue
            text=compact(value.get('clause_text',''))
            pages=sorted({s['page'] for s in row.get('cells',{}).get('clause_text',{}).get('sources',[])})
            checks=all(compact(q) in text for q in expected['must_include']) and not any(
                compact(q) in text for q in expected.get('must_not_include',[])) and pages==expected['pages']
            matches.append(dict(row=i,anchors_and_pages_correct=checks,status=row['status']))
            matched.add(i)
            if row['status']=='accepted' and not checks:unsafe.append(i)
        details.append(dict(facility=expected['facility'],heading=expected['heading'],matches=matches,
            anchor_candidate_found=any(m['anchors_and_pages_correct'] for m in matches),
            validated_anchor_row=any(m['anchors_and_pages_correct'] and m['status']=='accepted' for m in matches)))
    unsafe.extend(i for i,r in enumerate(rows) if i not in matched and r['status']=='accepted')
    safe_collection=not gold.get('collection_must_remain_unresolved') or (field.get('value') is None and field.get('status')!='accepted')
    margins=sorted({b['page'] for b in field.get('margin_blocks',[])})
    return dict(metric='clause anchors and source pages only; not full transcription or legal interpretation accuracy',
        expected_clauses=len(details),candidate_anchor_matches=sum(d['anchor_candidate_found'] for d in details),
        validated_anchor_rows=sum(d['validated_anchor_row'] for d in details),
        accepted_rows_failing_gold_checks=len(set(unsafe)),collection_unresolved_safe=safe_collection,
        margin_pages_correct=margins==gold['margin_review_pages'],details=details)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold',default='tests/fixtures/parser_set8_fol_terms.json')
    p.add_argument('--result',default='parser_data/evaluation/set8/FOL-编造完.result.json')
    p.add_argument('--output',default='parser_data/evaluation/set8/terms-score.json')
    args=p.parse_args()
    report=score(json.loads(Path(args.gold).read_text(encoding='utf8')),json.loads(Path(args.result).read_text(encoding='utf8')))
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False))


if __name__=='__main__':main()
