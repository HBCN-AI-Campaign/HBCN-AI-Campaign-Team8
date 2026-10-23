"""Replay actual extraction into an isolated main API and verify persistence gates.

This is API acceptance, not browser acceptance or a fresh inference benchmark.
The original PDFs are copied only into a temporary local directory.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import models
from app.database import Base,get_db
from app.main import app
from app.parsing.jobs import save_completed
from app.security import create_access_token


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',required=True)
    p.add_argument('--results',default='parser_data/evaluation/set8');a=p.parse_args()
    root=Path(a.results);run=json.loads((root/'run.json').read_text(encoding='utf-8'))
    assert not run.get('implementation_changed_during_run'),'Parser changed during inference; rerun baseline'
    docs=copy.deepcopy(run['documents']);assert len(docs)==7
    with tempfile.TemporaryDirectory(prefix='parser-api-acceptance-') as tmp:
        private=Path(tmp);uploads=private/'uploads';uploads.mkdir();seq=Counter()
        batch=uuid.uuid4().hex;folder=uploads/batch;folder.mkdir()
        for index,doc in enumerate(docs,1):
            seq[doc['type_code']]+=1
            doc['doc_code']=f"{doc['type_code']}-{seq[doc['type_code']]:02d}"
            dest=folder/f'{index}.pdf'
            shutil.copyfile(Path(a.source_root)/doc['source_filename'],dest)
            doc['pdf_file']=f'uploads/{batch}/{index}.pdf'
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        def dependency():
            with sessions() as db:yield db
        old=app.dependency_overrides.copy();app.dependency_overrides[get_db]=dependency
        try:
            with sessions() as db:
                db.add_all([models.User(username='parser-operator',display_name='隔离验收经办人',hashed_password='unused',role=models.Role.OPERATOR),
                            models.User(username='parser-reviewer',display_name='隔离验收审核员',hashed_password='unused',role=models.Role.REVIEWER)])
                db.commit();owner=db.query(models.User).filter_by(username='parser-operator').one().id
            (folder/'.owner.json').write_text(json.dumps({'owner_id':owner}),encoding='utf-8')
            # No application lifespan: it is wired to the normal deployment engine.
            # Only this script's in-memory Base metadata has been initialized.
            client=TestClient(app)
            with patch('app.config.UPLOAD_DIR',uploads),patch('app.routers.files.UPLOAD_DIR',uploads),patch('app.parsing.jobs.DATA_DIR',private/'runs'):
                receipt=save_completed({'documents':docs},owner)
                headers={'Authorization':'Bearer '+create_access_token('parser-operator','operator')}
                review_headers={'Authorization':'Bearer '+create_access_token('parser-reviewer','reviewer')}
                payload=dict(borrower='隔离验收任务（主体尚待核实）',drawdown_currency='CNY',drawdown_amount='12000000.00',
                    documents=[dict(doc_code=d['doc_code'],type_code=d['type_code'],pdf_file=d['pdf_file'],
                                    parse_run_id=receipt['parse_run_id'],fields={f['key']:f['value'] for f in d['fields']}) for d in docs])
                response=client.post('/api/tasks',headers=headers,json=payload)
                assert response.status_code==201,(response.status_code,response.text)
                code=response.json()['task_code']
                detail=client.get('/api/tasks/'+code,headers=headers)
                assert detail.status_code==200,detail.text
                assert response.json()['drawdown_amount']=='12000000.00'
                assert detail.json()['drawdown_amount']=='12000000.00'
                stored=detail.json()['documents'];assert len(stored)==7
                persisted={d['doc_code']:d for d in stored}
                checked_fields=0
                for original in docs:
                    actual=persisted[original['doc_code']]
                    assert actual['pdf_file']==original['pdf_file']
                    assert actual['fields']['_parsing']['source_sha256']==original['source_sha256']
                    for field in original['fields']:
                        assert actual['fields'][field['key']]==field['value'],(original['doc_code'],field['key'])
                        assert actual['fields']['_parsing']['fields'][field['key']]['machine']==field
                        checked_fields+=1
                drawdown=next(d for d in stored if d['type_code']=='DRAWDOWN_INSTRUCTION')
                assert drawdown['fields']['amount']=='12000000.00'
                assert drawdown['fields']['_parsing']['fields']['amount']['machine']['status']=='accepted'
                assert any(d['fields']['_parsing']['unresolved_required'] for d in stored)
                assert detail.json()['result_counts']['warn']>=1
                for doc in docs:
                    url='/'+doc['pdf_file']
                    assert client.get(url).status_code==401
                    assert client.get(url,headers=headers).content==(folder/Path(url).name).read_bytes()
                    assert client.get(url,headers=review_headers).status_code==200
                complete=client.post('/api/tasks/'+code+'/complete',headers=review_headers,json={'comment':'仍有识别待核实项'})
                assert complete.status_code==409,complete.text
                evidence=dict(scope='真实响应重放至隔离主站API；非浏览器验收',documents_persisted=7,
                    parser_result_sha256=hashlib.sha256((root/'run.json').read_bytes()).hexdigest(),
                    parser_implementation_sha256=run.get('implementation_sha256'),
                    all_field_values_and_machine_evidence_exactly_preserved=checked_fields,
                    task_amount_contract='decimal-string/1',
                    create_and_detail_amount_exact='12000000.00',
                    source_hashes_validated=True,exact_amount_persisted=True,machine_evidence_retained=True,
                    unresolved_fields_preserved=True,rule_warning_preserved=True,completion_blocked=True,
                    authenticated_original_preview_verified=True,
                    task_identity='临时测试任务，未认定实际借款人；数据库和凭据随测试销毁')
                from parser_supplement_acceptance import accept_supplement
                supplement=accept_supplement(client,sessions,uploads,docs,owner,headers,review_headers)
                (root/'supplement-api-acceptance.json').write_text(json.dumps(supplement,ensure_ascii=False,indent=2),encoding='utf-8')
                evidence['supplement_acceptance']=supplement
                (root/'api-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(evidence,ensure_ascii=False,indent=2))
        finally:
            if 'client' in locals():client.close()
            app.dependency_overrides.clear();app.dependency_overrides.update(old);engine.dispose()


if __name__=='__main__':main()
