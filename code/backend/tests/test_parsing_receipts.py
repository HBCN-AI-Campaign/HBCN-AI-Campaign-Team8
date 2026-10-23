"""Server receipt, source binding and review gate regressions; no live credentials."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.parsing import jobs
from app.schemas import DocumentIn
from app.rule_engine import run_all


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.patches=[patch('app.parsing.jobs.DATA_DIR',self.root/'runs'),patch('app.config.UPLOAD_DIR',self.root/'uploads')]
        for p in self.patches:p.start()
        source=self.root/'uploads'/'sample.pdf';source.parent.mkdir();source.write_bytes(b'synthetic original')
        self.original=dict(doc_code='PI-01',type_code='PAYMENT_INSTRUCTION',pdf_file='uploads/sample.pdf',
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),schema_version='loan-fields/1.0',issues=[],
            fields=[dict(key='amount',label='金额',value='123.45',data_type='money',required=True,status='accepted',
                         source={'page':1,'bbox':[.1,.2,.3,.4]})])
        self.result=jobs.save_completed({'documents':[self.original]},7)
        self.doc=DocumentIn(doc_code='PI-01',type_code='PAYMENT_INSTRUCTION',pdf_file='uploads/sample.pdf',
            parse_run_id=self.result['parse_run_id'],fields={'amount':'123.45'},field_sources={'amount':{'page':999}})

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_owner_only(self):
        with self.assertRaises(FileNotFoundError):jobs.read_run(self.doc.parse_run_id,8)

    def test_source_cannot_be_forged_by_client(self):
        fields,sources=jobs.verified_document(self.doc,7)
        self.assertEqual(sources['amount']['page'],1)
        self.assertEqual(fields['_parsing']['fields']['amount']['final_value'],'123.45')

    def test_changed_original_requires_reparse(self):
        (self.root/'uploads'/'sample.pdf').write_bytes(b'changed original')
        with self.assertRaisesRegex(ValueError,'重新解析'):jobs.verified_document(self.doc,7)

    def test_correction_requires_reason_and_keeps_machine_value(self):
        self.doc.fields['amount']='543.21'
        with self.assertRaises(ValueError):jobs.verified_document(self.doc,7)
        self.doc.field_confirmations={'amount':'原件第1页人工核对金额，纠正识别错误'}
        fields,_=jobs.verified_document(self.doc,7)
        audit=fields['_parsing']['fields']['amount']
        self.assertEqual((audit['machine']['value'],audit['final_value'],audit['confirmed_by']),('123.45','543.21',7))

    def test_new_receipt_for_changed_bytes_does_not_inherit_old_confirmation(self):
        self.doc.field_confirmations={'amount':'隔离测试：旧原件金额核实记录'}
        old_fields,_=jobs.verified_document(self.doc,7)
        source=self.root/'uploads'/'sample.pdf'
        source.write_bytes(b'changed synthetic original with ambiguous amount')
        with self.assertRaisesRegex(ValueError,'重新解析'):jobs.verified_document(self.doc,7)
        new=deepcopy(self.original)
        new['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        new['fields'][0].update(value=None,status='needs_review')
        receipt=jobs.save_completed({'documents':[new]},7)
        replacement=DocumentIn(doc_code=new['doc_code'],type_code=new['type_code'],pdf_file=new['pdf_file'],
            parse_run_id=receipt['parse_run_id'],fields={'amount':None})
        fields,_=jobs.verified_document(replacement,7)
        audit=fields['_parsing']['fields']['amount']
        self.assertEqual(audit['status'],'needs_review')
        self.assertIsNone(audit['confirmation_reason']);self.assertIsNone(audit['confirmed_by'])
        self.assertIsNone(audit['confirmed_at']);self.assertIsNone(fields['amount'])
        self.assertNotEqual(fields['_parsing']['source_sha256'],old_fields['_parsing']['source_sha256'])
        self.assertEqual(old_fields['_parsing']['fields']['amount']['status'],'confirmed')
        self.assertEqual(run_all([SimpleNamespace(doc_code='PI',fields=fields)])[0].rule_id,'PARSING_READY')

    def test_invalid_correction_is_rejected(self):
        self.doc.fields['amount']='1e99';self.doc.field_confirmations={'amount':'核对原件'}
        with self.assertRaises(ValueError):jobs.verified_document(self.doc,7)

    def test_unregistered_manual_choice_is_rejected(self):
        self.original['fields'][0].update(data_type='text',choices=['银行受托支付','借款人自主支付'])
        self.result=jobs.save_completed({'documents':[self.original]},7)
        self.doc.parse_run_id=self.result['parse_run_id']
        self.doc.fields['amount']='自定义选项';self.doc.field_confirmations={'amount':'核对原件'}
        with self.assertRaisesRegex(ValueError,'格式不正确'):jobs.verified_document(self.doc,7)

    def test_typed_rows_require_reason_and_preserve_machine_cell_evidence(self):
        machine=dict(key='borrower_allocations',label='借款人授信分配',value=None,data_type='rows',required=False,
            status='needs_review',row_results=[{'value':None,'issues':['INVALID_ROW_SCHEMA'],'cells':{}}])
        self.original['fields']=[machine]
        self.result=jobs.save_completed({'documents':[self.original]},7);self.doc.parse_run_id=self.result['parse_run_id']
        self.doc.fields={'borrower_allocations':[{'facility_name':'Facility A','borrower_name':'Alpha',
            'amount':'9007199254740993.01','currency':'USD'}]}
        with self.assertRaisesRegex(ValueError,'核实说明'):jobs.verified_document(self.doc,7)
        self.doc.field_confirmations={'borrower_allocations':'原件补正后核对额度，测试说明'}
        fields,_=jobs.verified_document(self.doc,7)
        self.assertEqual(fields['borrower_allocations'][0]['amount'],'9007199254740993.01')
        self.assertEqual(fields['_parsing']['fields']['borrower_allocations']['machine']['row_results'],machine['row_results'])
        self.doc.fields['borrower_allocations'][0]['nested_unknown']={'amount':'1'}
        with self.assertRaisesRegex(ValueError,'格式不正确'):jobs.verified_document(self.doc,7)

    def test_unresolved_optional_conflict_blocks_rules(self):
        self.original['fields'][0].update(required=False,status='conflict',value=None)
        self.result=jobs.save_completed({'documents':[self.original]},7)
        self.doc.parse_run_id=self.result['parse_run_id'];self.doc.fields={'amount':None}
        fields,_=jobs.verified_document(self.doc,7)
        self.assertEqual(fields['_parsing']['unresolved_fields'],['amount'])
        self.assertEqual(run_all([SimpleNamespace(doc_code='PI',fields=fields)])[0].rule_id,'PARSING_READY')

    def test_edit_after_confirmation_cannot_reuse_old_quality(self):
        fields,_=jobs.verified_document(self.doc,7);fields['amount']='999'
        self.assertEqual(run_all([SimpleNamespace(doc_code='PI',fields=fields)])[0].rule_id,'PARSING_READY')

    def test_restarted_job_is_interrupted_not_running_forever(self):
        run=jobs.read_run(self.doc.parse_run_id,7);run.update(state='running',process='previous-process')
        jobs._write(run)
        self.assertEqual(jobs.read_run(self.doc.parse_run_id,7)['state'],'interrupted')


if __name__=='__main__':unittest.main()
