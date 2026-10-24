"""Score image-verified facts; never label model output as gold."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.parsing.normalization import equivalent


def score(gold,root,source_root=None):
    totals=Counter();details=[]
    for doc in gold['documents']:
        path=root/(Path(doc['filename']).stem+'.result.json')
        if source_root:
            original=source_root/doc['filename']
            if hashlib.sha256(original.read_bytes()).hexdigest()!=doc['sha256']:
                raise ValueError('SOURCE_HASH_MISMATCH: '+doc['filename'])
        result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if result is not None:
            if result.get('source_sha256')!=doc['sha256']:
                raise ValueError('RESULT_SOURCE_HASH_MISMATCH: '+doc['filename'])
            if result.get('source_filename')!=doc['filename'] or result.get('page_count')!=doc['pages']:
                raise ValueError('RESULT_SOURCE_IDENTITY_MISMATCH: '+doc['filename'])
        fields={f['key']:f for f in (result or {}).get('fields',[])}
        totals['documents_expected']+=1;totals['documents_present']+=bool(result)
        for expected in doc['fields']:
            f=fields.get(expected['key'],{})
            accepted=f.get('status')=='accepted' and f.get('value') is not None
            correct=accepted and equivalent(f['value'],expected['value'])
            totals['annotated_facts']+=1
            totals['accepted']+=accepted;totals['correct_accepted']+=correct
            totals['wrong_accepted']+=accepted and not correct
            totals['unresolved']+=not accepted
            box=(f.get('source') or {}).get('bbox',[])
            located=correct and (f.get('source') or {}).get('page')==expected['page'] and len(box)==4 and 0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1
            totals['correct_with_page_and_valid_box']+=bool(located)
            details.append(dict(filename=doc['filename'],key=expected['key'],expected=expected['value'],actual=f.get('value'),status=f.get('status','not_run'),correct=bool(correct),valid_source=bool(located)))
        for key in doc.get('must_remain_unresolved',[]):
            totals['ambiguity_cases']+=1
            field=fields.get(key)
            safe=bool(result is not None and not result.get('issues') and result.get('status')!='failed'
                and field is not None and field.get('value') is None
                and field.get('status') in ('missing','needs_review','conflict'))
            totals['ambiguity_safe']+=safe
            if not safe:details.append(dict(filename=doc['filename'],key=key,error='AMBIGUITY_NOT_SAFELY_UNRESOLVED'))
        for case in doc.get('visual_cases',[]):
            f=fields.get(case['field'],{})
            correct=f.get('status')=='accepted' and equivalent(f.get('value'),case['expected'])
            visual=any(c.get('method')=='vision' and c.get('visual_state')=='selected' and not c.get('issues') for c in f.get('candidates',[]))
            located=(f.get('source') or {}).get('page')==case['page']
            totals['visual_cases']+=1;totals['visual_correct_accepted']+=bool(correct and visual and located)
            totals['visual_wrong_accepted']+=f.get('status')=='accepted' and not correct
            details.append(dict(filename=doc['filename'],key=case['field'],group='visual',correct=bool(correct and visual and located),actual=f.get('value')))
        for expected in doc.get('measurements',[]):
            f=fields.get(expected['key'],{})
            accepted=f.get('status')=='accepted' and f.get('value') is not None
            correct=accepted and equivalent(f['value'],expected['value'])
            totals['measurement_facts']+=1;totals['measurement_correct_accepted']+=correct
            totals['measurement_wrong_accepted']+=accepted and not correct
            details.append(dict(filename=doc['filename'],key=expected['key'],group='measurement',correct=bool(correct),actual=f.get('value'),status=f.get('status','not_run')))
    return dict(scope=gold['scope'],annotation_version=gold.get('annotation_version'),
        annotation_status=gold.get('annotation_status'),counts=dict(totals),
        accepted_precision=totals['correct_accepted']/totals['accepted'] if totals['accepted'] else None,
        automatic_coverage=totals['correct_accepted']/totals['annotated_facts'] if totals['annotated_facts'] else None,
        localization_scope='页码及合法框，不代表框IoU或全文覆盖率',details=details)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',default='parser_data/evaluation/set8')
    p.add_argument('--gold',default='tests/fixtures/parser_set8.json');p.add_argument('--source-root')
    a=p.parse_args();root=Path(a.results)
    gold_bytes=Path(a.gold).read_bytes()
    result=score(json.loads(gold_bytes.decode('utf-8')),root,Path(a.source_root) if a.source_root else None)
    result['gold_sha256']=hashlib.sha256(gold_bytes).hexdigest()
    dest=root/'metrics.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='details'},ensure_ascii=False,indent=2))
