"""Replay one actual multi-page invoice or contract through the isolated role API.

This verifies persistence and review gates, not a complete lending transaction.
"""
import argparse
import copy
from decimal import Decimal
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
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--result',required=True)
    p.add_argument('--type-code',choices=['PROFORMA_INVOICE','COMMERCIAL_CONTRACT'],default='PROFORMA_INVOICE')
    args=p.parse_args();result_path=Path(args.result);doc=json.loads(result_path.read_text(encoding='utf-8'))
    original=Path(args.source)
    assert hashlib.sha256(original.read_bytes()).hexdigest()==doc['source_sha256']
    assert original.name==doc['source_filename'] and doc['type_code']==args.type_code
    fields={f['key']:f for f in doc['fields']}
    assert fields['line_items']['status']=='accepted' and len(fields['line_items']['value'])>1
    with tempfile.TemporaryDirectory(prefix='invoice-parser-api-') as tmp:
        private=Path(tmp);uploads=private/'uploads';batch=uuid.uuid4().hex;folder=uploads/batch;folder.mkdir(parents=True)
        shutil.copyfile(original,folder/'invoice.pdf')
        doc=copy.deepcopy(doc);doc.update(doc_code=args.type_code+'-01',pdf_file=f'uploads/{batch}/invoice.pdf')
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        def dependency():
            with sessions() as db:yield db
        old=app.dependency_overrides.copy();app.dependency_overrides[get_db]=dependency
        client=TestClient(app) # Deliberately no deployment-engine lifespan.
        try:
            with sessions() as db:
                for username,role in [('invoice-operator',models.Role.OPERATOR),('invoice-other',models.Role.OPERATOR),('invoice-reviewer',models.Role.REVIEWER)]:
                    db.add(models.User(username=username,display_name='隔离发票验收',hashed_password='unused',role=role))
                db.commit();owner=db.query(models.User).filter_by(username='invoice-operator').one().id
            (folder/'.owner.json').write_text(json.dumps(dict(owner_id=owner)),encoding='utf-8')
            headers={'Authorization':'Bearer '+create_access_token('invoice-operator','operator')}
            reviewer={'Authorization':'Bearer '+create_access_token('invoice-reviewer','reviewer')}
            other={'Authorization':'Bearer '+create_access_token('invoice-other','operator')}
            with patch('app.config.UPLOAD_DIR',uploads),patch('app.routers.files.UPLOAD_DIR',uploads),patch('app.parsing.jobs.DATA_DIR',private/'runs'):
                receipt=save_completed({'documents':[doc]},owner)
                label='合同' if args.type_code=='COMMERCIAL_CONTRACT' else '发票'
                payload=dict(borrower='隔离'+label+'测试（未认定实际借款人）',drawdown_currency=fields['currency']['value'],
                             drawdown_amount=fields['amount']['value'],documents=[dict(doc_code=doc['doc_code'],type_code=doc['type_code'],
                             pdf_file=doc['pdf_file'],parse_run_id=receipt['parse_run_id'],fields={f['key']:f['value'] for f in doc['fields']})])
                response=client.post('/api/tasks',headers=headers,json=payload)
                assert response.status_code==201,(response.status_code,response.text)
                task_code=response.json()['task_code'];detail=client.get('/api/tasks/'+task_code,headers=headers)
                assert detail.status_code==200,detail.text
                actual=detail.json()['documents'][0]
                for field in doc['fields']:
                    assert actual['fields'][field['key']]==field['value'],field['key']
                    assert actual['fields']['_parsing']['fields'][field['key']]['machine']==field
                rows=actual['fields']['line_items']
                total=format(sum(Decimal(r['amount']) for r in rows),'f')
                quantity=format(sum(Decimal(r['quantity']) for r in rows),'f')
                assert actual['fields']['amount']==fields['amount']['value']
                url='/'+doc['pdf_file']
                assert client.get(url).status_code==401
                assert client.get(url,headers=other).status_code==404
                assert client.get(url,headers=headers).content==original.read_bytes()
                assert client.get(url,headers=reviewer).status_code==200
                assert actual['fields']['_parsing']['unresolved_fields']
                assert detail.json()['result_counts']['warn']>=1
                complete=client.post('/api/tasks/'+task_code+'/complete',headers=reviewer,json={'comment':'单一单据仍有待核实且缺整套材料'})
                assert complete.status_code==409,complete.text
                report=dict(scope='actual frozen invoice/contract response into isolated role API; no browser or complete transaction acceptance',type_code=args.type_code,
                            result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),source_sha256=doc['source_sha256'],
                            exact_final_fields_and_full_machine_evidence=len(doc['fields']),rows_preserved=len(rows),
                            printed_amount=actual['fields']['amount'],printed_quantity=actual['fields']['quantity'],
                            row_amount_sum=total,row_quantity_sum=quantity,totals_reconciled_by_parser=False,
                            authenticated_original_verified=True,other_operator_denied=True,pending_preserved=True,
                            completion_status=complete.status_code,business_total_consistency_rule_executed=False,
                            temporary_database_and_receipts=True)
                name='contract-api-acceptance.json' if args.type_code=='COMMERCIAL_CONTRACT' else 'invoice-api-acceptance.json'
                (result_path.parent/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False,indent=2))
        finally:
            client.close();app.dependency_overrides.clear();app.dependency_overrides.update(old);engine.dispose()


if __name__=='__main__':main()
