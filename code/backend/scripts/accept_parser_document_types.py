"""Actual multipart -> worker -> cached real parser -> receipt -> task audit.

The controlled upload name tests unclear filenames. Original bytes are unchanged.
No external inference, default database lifespan, deployment or browser automation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app import models
from app.database import Base,get_db
from app.parsing import jobs
from app.parsing.config import ParserSettings
from app.parsing.pipeline import ParsingPipeline
from app.parsing.providers import HSBCSemanticProvider,PaddleHttpProvider
from app.security import create_access_token
from evaluate_parser import CachedOcr,CachedSemantic,env_file,implementation_hash


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True)
    p.add_argument('--cache',default='parser_data/evaluation/set6-invoice-verified')
    p.add_argument('--output',default='parser_data/evaluation/document-types')
    a=p.parse_args();source=Path(a.source);original=source.read_bytes();cache=Path(a.cache);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    gold=json.loads(Path('tests/fixtures/parser_set6_invoice.json').read_text(encoding='utf-8'))['documents'][0]
    assert hashlib.sha256(original).hexdigest()==gold['sha256'] and source.name==gold['filename']
    ai=env_file('.env')
    cfg=ParserSettings(vision_base_url=ai.get('PARSER_VISION_BASE_URL') or ai.get('AI_BASE_URL',''),
                       vision_api_key=ai.get('PARSER_VISION_API_KEY') or ai.get('AI_API_KEY',''),
                       vision_model=ai.get('PARSER_VISION_MODEL') or ai.get('AI_MODEL',''))
    providers=[]
    def factory(progress=None):
        ocr=CachedOcr(PaddleHttpProvider(cfg),cache/'ocr',True)
        semantic=CachedSemantic(HSBCSemanticProvider(cfg),cache/'semantic',True)
        providers.append((ocr,semantic))
        return ParsingPipeline(cfg,ocr=ocr,semantic=semantic,progress=progress)
    start=implementation_hash()
    with tempfile.TemporaryDirectory(prefix='parser-type-acceptance-') as tmp:
        private=Path(tmp);uploads=private/'uploads'
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        def dependency():
            with sessions() as db:yield db
        old=app.dependency_overrides.copy();app.dependency_overrides[get_db]=dependency
        client=TestClient(app) # No default database lifecycle.
        try:
            with sessions() as db:
                for name,role in [('type-owner',models.Role.OPERATOR),('type-other',models.Role.OPERATOR),('type-reviewer',models.Role.REVIEWER)]:
                    db.add(models.User(username=name,display_name='类别隔离验收',hashed_password='unused',role=role))
                db.commit();owner=db.query(models.User).filter_by(username='type-owner').one().id
            headers={'Authorization':'Bearer '+create_access_token('type-owner','operator')}
            other={'Authorization':'Bearer '+create_access_token('type-other','operator')}
            reviewer={'Authorization':'Bearer '+create_access_token('type-reviewer','reviewer')}
            with patch('app.config.UPLOAD_DIR',uploads),patch('app.routers.parsing.UPLOAD_DIR',uploads),patch('app.routers.files.UPLOAD_DIR',uploads),\
                 patch('app.parsing.jobs.DATA_DIR',private/'runs'),patch('app.parsing.jobs.ParsingPipeline',side_effect=factory):
                def upload(selection=None):
                    # Deliberate negative case, not a hidden rename to make type inference pass.
                    response=client.post('/api/parsing/runs',headers=headers,files={'files':('材料.pdf',original,'application/pdf')},
                                         data={} if selection is None else {'document_types':json.dumps([selection])})
                    assert response.status_code==202,(response.status_code,response.text)
                    run_id=response.json()['run_id'];url='/api/parsing/runs/'+run_id
                    for _ in range(600):
                        polled=client.get(url,headers=headers);assert polled.status_code==200,polled.text
                        run=polled.json()
                        if run['state'] in {'completed','failed','interrupted'}:break
                        time.sleep(.1)
                    else:raise RuntimeError('bounded worker observation timeout')
                    assert run['state']=='completed',run.get('error')
                    assert client.get(url,headers=other).status_code==404
                    return run_id,run['result']
                first_id,first=upload();unknown=first['documents'][0]
                assert unknown['type_code']=='UNKNOWN' and unknown['fields']==[]
                assert unknown['source_sha256']==gold['sha256'] and unknown['issues']==['UNKNOWN_DOCUMENT_TYPE']
                assert client.get('/'+unknown['pdf_file'],headers=headers).content==original
                choice=dict(type_code='PROFORMA_INVOICE',reason='原件标题PROFORMA RECHNUNG，按形式发票识别')
                second_id,second=upload(choice);doc=second['documents'][0]
                assert first_id!=second_id and doc['source_sha256']==unknown['source_sha256']
                assert doc['source_filename']=='材料.pdf' and doc['type_code']=='PROFORMA_INVOICE'
                assert client.get('/api/parsing/runs/'+first_id,headers=headers).json()['result']['documents'][0]==unknown
                expected=json.loads((cache/(source.stem+'.result.json')).read_text(encoding='utf-8'))
                assert doc['fields']==expected['fields'] and doc['issues']==expected['issues']
                selection=doc['classification'];assert selection['selected_by']==owner and selection['method']=='operator_selected'
                assert selection['reason']==choice['reason'] and selection['selected_at']
                payload=dict(borrower='隔离类别验收，主体未认定',drawdown_currency='USD',drawdown_amount='550000.00',documents=[
                    dict(doc_code=doc['doc_code'],type_code=doc['type_code'],pdf_file=doc['pdf_file'],parse_run_id=second_id,
                         fields={**{f['key']:f['value'] for f in doc['fields']},'_parsing':{'classification':{'selected_by':999}}})])
                created=client.post('/api/tasks',headers=headers,json=payload);assert created.status_code==201,created.text
                code=created.json()['task_code'];detail=client.get('/api/tasks/'+code,headers=headers).json();stored=detail['documents'][0]['fields']
                assert stored['_parsing']['classification']==selection
                for field in doc['fields']:
                    assert stored[field['key']]==field['value']
                    assert stored['_parsing']['fields'][field['key']]['machine']==field
                forged=json.loads(json.dumps(payload));forged['documents'][0]['type_code']='COMMERCIAL_CONTRACT'
                assert client.post('/api/tasks',headers=headers,json=forged).status_code==400
                complete=client.post('/api/tasks/'+code+'/complete',headers=reviewer,json={'comment':'仍有未决且只包含一份发票'})
                assert complete.status_code==409,complete.text
                assert all(o.live_attempts==s.live_attempts==0 for o,s in providers)
                report=dict(scope='actual authenticated multipart, worker, cached real parser and task persistence; not browser or new classification accuracy',
                            source_sha256=gold['sha256'],original_filename=source.name,controlled_upload_filename='材料.pdf',
                            unchanged_original_bytes=True,unknown_run_preserved=True,explicit_selection_new_receipt=True,
                            fields_and_machine_evidence_preserved=len(doc['fields']),rows_preserved=len(stored['line_items']),
                            server_actor_and_time_retained=True,client_cannot_forge_classification=True,wrong_type_rejected=True,
                            other_owner_denied=True,completion_status=complete.status_code,external_attempts=0,
                            ocr_cache=sum(o.replay for o,s in providers),model_cache=sum(s.replay for o,s in providers),
                            implementation_sha256=start,implementation_end_sha256=implementation_hash())
                assert report['implementation_sha256']==report['implementation_end_sha256']
                (out/'api-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False,indent=2))
        finally:
            client.close();app.dependency_overrides.clear();app.dependency_overrides.update(old);engine.dispose()


if __name__=='__main__':main()
