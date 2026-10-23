"""Score independently annotated FOL rows; row validation is not usable collection coverage."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def name(value):
    # Formatting tolerance is declared in the fixture. Never remove hyphens,
    # parentheses or slashes or infer that two different aliases identify a party.
    return re.sub(r'[\s.,]','',unicodedata.normalize('NFKC',str(value))).casefold()


def identity(value,key):
    columns={'borrowers':['name'],'facility_limits':['facility_name'],
             'borrower_allocations':['facility_name','borrower_name']}[key]
    return tuple(name(value.get(c,'')) for c in columns)


def same(row,expected):
    return all(str(row.get(k))==str(v) if k in {'amount','currency'} else name(row.get(k,''))==name(v)
               for k,v in expected.items())


def score(gold,result):
    if result.get('source_sha256')!=gold['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
    fields={f['key']:f for f in result['fields']};details=[];counts={}
    expected_by_key={'borrowers':gold['borrowers'],'facility_limits':[], 'borrower_allocations':[]}
    special={}
    for limit in gold['facility_limits']:
        value={'facility_name':gold['facility_names'][limit['facility']], 'amount':limit['amount'],'currency':limit['currency']}
        expected_by_key['facility_limits'].append(value)
        if limit.get('status')=='conflict':special[('facility_limits',identity(value,'facility_limits'),value['amount'])]='conflict'
    for group in gold['allocation_groups']:
        for borrower in gold['allocation_amounts'] if group['borrowers']=='all' else group['borrowers']:
            value=dict(facility_name=gold['facility_names'][group['facility']],borrower_name=borrower,
                       amount=gold['allocation_amounts'][borrower],currency='USD')
            expected_by_key['borrower_allocations'].append(value)
            if borrower in group.get('must_remain_unresolved',[]):
                special[('borrower_allocations',identity(value,'borrower_allocations'),value['amount'])]='unresolved'
    for key,expected_rows in expected_by_key.items():
        rows=fields.get(key,{}).get('row_results',[]);c=Counter()
        c['expected_rows']=len(expected_rows)
        for expected in expected_rows:
            matches=[r for r in rows if identity(r.get('value') or r.get('original') or {},key)==identity(expected,key)]
            mode=special.get((key,identity(expected,key),expected.get('amount')))
            exact=[r for r in matches if r.get('value') and same(r['value'],expected)]
            accepted=[r for r in exact if r['status']=='accepted']
            if mode=='conflict':
                correct=any(r['status']=='conflict' for r in exact)
                c['expected_conflict_rows']+=1;c['conflict_rows_preserved']+=correct
            elif mode=='unresolved':
                correct=bool(matches) and not any(r['status']=='accepted' for r in matches)
                c['expected_ambiguous_rows']+=1;c['ambiguous_rows_safe']+=correct
            else:
                correct=bool(accepted);c['clear_rows']+=1;c['correct_validated_rows']+=correct
                c['unresolved_clear_rows']+=not correct
            details.append(dict(key=key,expected=expected,expected_state=mode or 'accepted',correct=bool(correct)))
        for row in rows:
            if row['status']!='accepted':continue
            value=row.get('value') or {}
            matching=[e for e in expected_rows if same(value,e)]
            c['wrong_validated_rows']+=not bool(matching)
            cells=row.get('cells',{})
            located=bool(cells) and all(cell.get('sources') and all(
                len(s.get('bbox',[]))==4 and 0<=s['bbox'][0]<s['bbox'][2]<=1 and
                0<=s['bbox'][1]<s['bbox'][3]<=1 and s['page'] in {5,6,7,8}
                for s in cell['sources']) for cell in cells.values())
            c['validated_rows_with_cell_locations']+=located
        c['collection_automatically_usable']=int(fields.get(key,{}).get('status')=='accepted' and fields[key].get('value') is not None)
        counts[key]=dict(c)
    return dict(scope=gold['scope'],annotation_status=gold['annotation_status'],counts=counts,details=details,
        interpretation='validated行仅代表逐格文字/图像证据通过；collection仍需完整性、冲突及适用关系，不能按validated行数声称可直接应用授信。位置只校验页码与框合法性，非IoU。')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--gold',default='tests/fixtures/parser_set8_fol_records.json')
    parser.add_argument('--results',default='parser_data/evaluation/set8');parser.add_argument('--source-root')
    args=parser.parse_args();gold=json.loads(Path(args.gold).read_text(encoding='utf-8'))
    if args.source_root and hashlib.sha256((Path(args.source_root)/gold['filename']).read_bytes()).hexdigest()!=gold['sha256']:
        raise ValueError('SOURCE_HASH_MISMATCH')
    root=Path(args.results);result=json.loads((root/(Path(gold['filename']).stem+'.result.json')).read_text(encoding='utf-8'))
    report=score(gold,result);(root/'records-score.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2))
