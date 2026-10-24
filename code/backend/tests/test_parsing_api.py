import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import User, Role,ReviewTask,Document
from app.parsing import jobs
from app.routers.parsing import router
from app.routers.files import router as originals_router
from app.security import create_access_token
try:
    from app.business_review.storage import BusinessReviewAudit
    HAS_BUSINESS_REVIEW = True
except ModuleNotFoundError:
    HAS_BUSINESS_REVIEW = False


class ParsingAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch('app.parsing.jobs.DATA_DIR',self.root/'runs'),patch('app.routers.parsing.UPLOAD_DIR',self.root/'uploads'),patch('app.routers.files.UPLOAD_DIR',self.root/'uploads')]
        for p in self.patches:p.start()
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine);self.sessions=sessionmaker(bind=self.engine)
        with self.sessions() as db:
            for name,role in [('owner',Role.OPERATOR),('other',Role.OPERATOR),('review',Role.REVIEWER)]:
                db.add(User(username=name,display_name=name,hashed_password='unused',role=role))
            db.commit();self.owner_id=db.query(User).filter_by(username='owner').one().id
        app=FastAPI();app.include_router(router);app.include_router(originals_router)
        def dependency():
            with self.sessions() as db:yield db
        app.dependency_overrides[get_db]=dependency
        self.client=TestClient(app)
        self.headers={n:{'Authorization':'Bearer '+create_access_token(n,r)} for n,r in [('owner','operator'),('other','operator'),('review','reviewer')]}

    def tearDown(self):
        self.client.close();self.engine.dispose()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_jwt_and_operator_role_required(self):
        self.assertEqual(self.client.get('/api/parsing/runs/'+'a'*32).status_code,401)
        self.assertEqual(self.client.post('/api/parsing/runs',headers=self.headers['review'],files={'files':('payment.pdf',b'test','application/pdf')}).status_code,403)

    def test_receipt_owner_only_and_no_internal_owner_metadata(self):
        result=jobs.save_completed({'documents':[]},self.owner_id);url='/api/parsing/runs/'+result['parse_run_id']
        r=self.client.get(url,headers=self.headers['owner']);self.assertEqual(r.status_code,200)
        self.assertNotIn('owner_id',r.json());self.assertNotIn('process',r.json())
        self.assertEqual(self.client.get(url,headers=self.headers['other']).status_code,404)

    def test_upload_returns_202_and_preserves_bytes_with_generated_path(self):
        with patch('app.parsing.jobs.submit',return_value='a'*32) as submit:
            r=self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('../../支付指令.pdf',b'original bytes','application/pdf')})
        self.assertEqual(r.status_code,202,r.text)
        saved,owner=submit.call_args.args
        path=Path(saved[0]['path']).resolve()
        self.assertTrue(path.is_relative_to((self.root/'uploads').resolve()))
        self.assertEqual(path.read_bytes(),b'original bytes');self.assertEqual(owner,self.owner_id)

    def test_queue_full_is_429_not_success(self):
        with patch('app.parsing.jobs.submit',return_value=None):
            r=self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('payment.pdf',b'test','application/pdf')})
        self.assertEqual(r.status_code,429)
        self.assertEqual(list((self.root/'uploads').iterdir()),[])

    def test_type_selections_bind_by_upload_order_and_server_records_actor(self):
        choices=[dict(type_code='DRAWDOWN_INSTRUCTION',reason='提款申请标题'),dict(type_code='COMMERCIAL_CONTRACT',reason='销售合同标题')]
        with patch('app.parsing.jobs.submit',return_value='a'*32) as submit:
            response=self.client.post('/api/parsing/runs',headers=self.headers['owner'],
                files=[('files',('same.pdf',b'first original')),('files',('same.pdf',b'second original'))],
                data={'document_types':json.dumps(choices)})
        self.assertEqual(response.status_code,202,response.text)
        saved,_=submit.call_args.args
        self.assertEqual([Path(d['path']).read_bytes() for d in saved],[b'first original',b'second original'])
        self.assertEqual([d['filename'] for d in saved],['same.pdf','same.pdf'])
        self.assertEqual([d['type_code'] for d in saved],[c['type_code'] for c in choices])
        for item in saved:
            self.assertEqual(item['classification']['selected_by'],self.owner_id)
            self.assertEqual(item['classification']['method'],'operator_selected')
            self.assertTrue(item['classification']['selected_at'])

    def test_invalid_type_metadata_fails_before_persisting_any_files(self):
        for raw in ('[]','[{"type_code":"COMMERCIAL_CONTRACT","reason":""}]',
                    '[{"type_code":"COMMERCIAL_CONTRACT","reason":"标题","selected_by":999}]'):
            with self.subTest(raw=raw):
                response=self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('合同.pdf',b'bytes')},data={'document_types':raw})
                self.assertEqual(response.status_code,400,response.text)
                self.assertFalse((self.root/'uploads').exists())

    def test_original_preview_requires_owner_or_submitted_reviewer(self):
        with patch('app.parsing.jobs.submit',return_value='a'*32) as submit:
            self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('payment.pdf',b'original bytes','application/pdf')})
        saved,_=submit.call_args.args;relative=saved[0]['pdf_url'];url='/'+relative
        self.assertEqual(self.client.get(url).status_code,401)
        response=self.client.get(url,headers=self.headers['owner'])
        self.assertEqual(response.content,b'original bytes');self.assertEqual(response.headers['cache-control'],'private, no-store')
        for role in ['other','review']:self.assertEqual(self.client.get(url,headers=self.headers[role]).status_code,404)
        with self.sessions() as db:
            task=ReviewTask(task_code='TEST-1',borrower='test',drawdown_currency='CNY',drawdown_amount=1,submitted_by=self.owner_id)
            task.documents.append(Document(doc_code='PI',type_code='PAYMENT_INSTRUCTION',fields={},pdf_file=relative))
            db.add(task);db.commit()
        self.assertEqual(self.client.get(url,headers=self.headers['review']).status_code,200)
        self.assertEqual(self.client.get(url.rsplit('/',1)[0]+'/.owner.json',headers=self.headers['owner']).status_code,404)

    def test_bad_upload_does_not_leave_partial_originals(self):
        response=self.client.post('/api/parsing/runs',headers=self.headers['owner'],files=[('files',('payment.pdf',b'good')),('files',('bad.exe',b'bad'))])
        self.assertEqual(response.status_code,400)
        self.assertEqual(list((self.root/'uploads').iterdir()),[])

    @unittest.skipUnless(HAS_BUSINESS_REVIEW, 'requires the separately integrated business-review audit module')
    def test_reviewer_can_trace_replaced_original_only_through_owner_bound_snapshot(self):
        with patch('app.parsing.jobs.submit',return_value='a'*32) as submit:
            self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('old.pdf',b'old PDF bytes')})
        saved,_=submit.call_args.args;relative=saved[0]['pdf_url'];url='/'+relative
        self.assertEqual(self.client.get(url,headers=self.headers['review']).status_code,404)
        with self.sessions() as db:
            task=ReviewTask(task_code='HISTORY',borrower='test',drawdown_currency='CNY',drawdown_amount=1,submitted_by=self.owner_id)
            db.add(task);db.flush()
            data={'previous_snapshot':{'documents':[{'doc_code':'PI',
                'file_sha256':hashlib.sha256(b'old PDF bytes').hexdigest(),
                'sources':{'amount':{'file':relative,'page':1}}}]}}
            audit=BusinessReviewAudit(task_id=task.id,user_id=self.owner_id,kind='supplement',reason='隔离测试旧版原件追溯',data=data)
            db.add(audit);db.commit();audit_id=audit.id;task_id=task.id
        response=self.client.get(url,headers=self.headers['review'])
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,b'old PDF bytes')
        self.assertEqual(response.headers['cache-control'],'private, no-store')
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.headers['other']).status_code,404)
        with self.sessions() as db:
            row=db.get(BusinessReviewAudit,audit_id)
            row.data={'note':relative,'previous_snapshot':{'documents':[]}};db.commit()
        self.assertEqual(self.client.get(url,headers=self.headers['review']).status_code,404)
        with self.sessions() as db:
            row=db.get(BusinessReviewAudit,audit_id);row.data=data
            task=db.get(ReviewTask,task_id);task.submitted_by=db.query(User).filter_by(username='other').one().id
            db.commit()
        self.assertEqual(self.client.get(url,headers=self.headers['review']).status_code,404)
        with self.sessions() as db:
            db.get(ReviewTask,task_id).submitted_by=self.owner_id;db.commit()
        Path(saved[0]['path']).write_bytes(b'changed bytes at the old path')
        self.assertEqual(self.client.get(url,headers=self.headers['review']).status_code,404)

    def test_client_cannot_grant_reviewer_access_to_another_uploaders_file(self):
        with patch('app.parsing.jobs.submit',return_value='a'*32) as submit:
            self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':('private.pdf',b'private PDF bytes')})
        saved,_=submit.call_args.args;relative=saved[0]['pdf_url']
        with self.sessions() as db:
            other_id=db.query(User).filter_by(username='other').one().id
            task=ReviewTask(task_code='WRONG-OWNER',borrower='test',drawdown_currency='CNY',drawdown_amount=1,submitted_by=other_id)
            task.documents.append(Document(doc_code='PI',type_code='PAYMENT_INSTRUCTION',fields={},pdf_file=relative))
            db.add(task);db.commit()
        self.assertEqual(self.client.get('/'+relative,headers=self.headers['review']).status_code,404)

    def test_unknown_or_empty_format_is_rejected(self):
        for name,content in [('payment.exe',b'test'),('payment.pdf',b'')]:
            self.assertEqual(self.client.post('/api/parsing/runs',headers=self.headers['owner'],files={'files':(name,content)}).status_code,400)

    def _facility_request(self):
        from tests.test_parsing_facility import documents
        docs=documents()
        upload=self.root/'uploads';upload.mkdir(exist_ok=True)
        for index,doc in enumerate(docs):
            source=upload/f'facility-{index}.pdf';source.write_bytes(b'synthetic facility original '+str(index).encode())
            doc.update(pdf_file='uploads/'+source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),schema_version='loan-fields/1.2')
        result=jobs.save_completed({'documents':docs},self.owner_id)
        return dict(documents=[dict(doc_code=d['doc_code'],type_code=d['type_code'],pdf_file=d['pdf_file'],
            parse_run_id=result['parse_run_id'],fields={f['key']:f['value'] for f in d['fields']}) for d in docs])

    def test_facility_context_uses_receipts_and_operator_owner_authorization(self):
        payload=self._facility_request();url='/api/parsing/facility-context'
        with patch('app.config.UPLOAD_DIR',self.root/'uploads'):
            self.assertEqual(self.client.post(url,json=payload).status_code,401)
            self.assertEqual(self.client.post(url,json=payload,headers=self.headers['review']).status_code,403)
            self.assertEqual(self.client.post(url,json=payload,headers=self.headers['other']).status_code,404)
            response=self.client.post(url,json=payload,headers=self.headers['owner'])
            self.assertEqual(response.status_code,200,response.text)
            context=response.json();self.assertEqual(context['status'],'ready')
            self.assertEqual(context['nominal_limit']['amount'],'1000.01')
            self.assertIsNone(context['available_balance'])
            # A client-supplied field cannot silently replace a receipted value.
            payload['documents'][1]['fields']['borrower']='其他主体'
            self.assertEqual(self.client.post(url,json=payload,headers=self.headers['owner']).status_code,400)

    def test_facility_selection_persists_actor_evidence_and_rechecks_at_task_creation(self):
        from app.routers.tasks import router as tasks_router
        self.client.app.include_router(tasks_router)
        payload=self._facility_request()
        with patch('app.config.UPLOAD_DIR',self.root/'uploads'):
            context=self.client.post('/api/parsing/facility-context',json=payload,headers=self.headers['owner']).json()
            chosen=dict(borrower_id=context['borrowers'][0]['id'],allocation_id=context['allocations'][0]['id'],reason='对照原件核实授信对应关系')
            task=dict(**payload,facility_selection=chosen,borrower='甲公司',drawdown_currency='USD',drawdown_amount=1000)
            response=self.client.post('/api/tasks',json=task,headers=self.headers['owner'])
            self.assertEqual(response.status_code,201,response.text)
            with self.sessions() as db:
                document=db.query(Document).filter_by(doc_code='FOL-01').one()
                saved=document.fields['_parsing']['facility_context']
                self.assertEqual(saved['selection'],chosen)
                self.assertEqual(saved['confirmed_by'],self.owner_id)
                self.assertEqual(saved['status'],'ready')
                self.assertIsNone(saved['available_balance'])
            task['facility_selection']={**chosen,'borrower_id':'e'*64}
            self.assertEqual(self.client.post('/api/tasks',json=task,headers=self.headers['owner']).status_code,400)
            with self.sessions() as db:self.assertEqual(db.query(ReviewTask).count(),1)

    def test_facility_context_cannot_reuse_selection_for_changed_original(self):
        payload=self._facility_request()
        with patch('app.config.UPLOAD_DIR',self.root/'uploads'):
            context=self.client.post('/api/parsing/facility-context',json=payload,headers=self.headers['owner']).json()
            payload['facility_selection']=dict(borrower_id=context['borrowers'][0]['id'],allocation_id=context['allocations'][0]['id'],reason='对照原件')
            (self.root/'uploads'/'facility-0.pdf').write_bytes(b'replaced original')
            response=self.client.post('/api/parsing/facility-context',json=payload,headers=self.headers['owner'])
            self.assertEqual(response.status_code,400)
            self.assertIn('重新解析',response.json()['detail'])


if __name__=='__main__':unittest.main()
