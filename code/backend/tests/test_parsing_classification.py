"""Typed routing is an operator assertion, not automatically extracted fact."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.parsing.classification import parse_selections
from app.parsing.config import ParserSettings
from app.parsing.contracts import Page
from app.parsing.pipeline import ParsingPipeline
from app.parsing import jobs
from app.schemas import DocumentIn


class DocumentTypeSelectionTests(unittest.TestCase):
    def test_explicit_order_and_duplicate_names_do_not_drive_mapping(self):
        choices=parse_selections('[{"type_code":"DRAWDOWN_INSTRUCTION","reason":"原件标题为提款申请"},{"type_code":"COMMERCIAL_CONTRACT","reason":"原件标题为销售合同"}]',2)
        self.assertEqual([c.type_code for c in choices],['DRAWDOWN_INSTRUCTION','COMMERCIAL_CONTRACT'])
        self.assertEqual(parse_selections(None,2)[0].type_code,None)

    def test_invalid_partial_extra_or_forged_selection_is_rejected(self):
        for raw in ('{}','[]','[null]','[1]','[{"type_code":"UNKNOWN","reason":"原件标题"}]',
                    '[{"type_code":"COMMERCIAL_CONTRACT","reason":" "}]',
                    '[{"type_code":null,"reason":"已选择"}]',
                    '[{"type_code":"COMMERCIAL_CONTRACT","reason":"原件标题","selected_by":999}]',
                    'not json','[{"type_code":"COMMERCIAL_CONTRACT","reason":123}]'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_selections(raw,1)

    def test_unknown_result_has_original_identity_but_no_invented_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'合同.pdf';p.write_bytes(b'synthetic original')
            with patch('app.parsing.pipeline.prepare',return_value=[Page(1,100,100,b'',[])]):
                doc=ParsingPipeline(ParserSettings(_env_file=None),ocr=object(),semantic=object()).parse_document(p,p.name)
            self.assertEqual(doc['type_code'],'UNKNOWN');self.assertEqual(doc['fields'],[])
            self.assertEqual(doc['source_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertIn('schema_version',doc)

    def test_registered_selection_reaches_pipeline_without_renaming_original(self):
        class Semantic:
            def extract(self,pages,tcode,specs,*,visual):
                assert tcode=='COMMERCIAL_CONTRACT'
                return []
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'DD notice.pdf';p.write_bytes(b'synthetic contract with misleading filename')
            classification=dict(method='operator_selected',type_code='COMMERCIAL_CONTRACT',reason='原件销售合同标题',selected_by=7,selected_at='test time')
            page=Page(1,100,100,b'',[],needs_ocr=False)
            with patch('app.parsing.pipeline.prepare',return_value=[page]):
                result=ParsingPipeline(ParserSettings(_env_file=None),ocr=object(),semantic=Semantic()).parse([
                    dict(path=str(p),filename=p.name,type_code='COMMERCIAL_CONTRACT',classification=classification)])
            doc=result['documents'][0]
            self.assertEqual(doc['source_filename'],'DD notice.pdf')
            self.assertEqual(doc['type_code'],'COMMERCIAL_CONTRACT')
            self.assertEqual(doc['classification'],classification)
            self.assertEqual(doc['source_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(doc['status'],'needs_review')

    def test_classification_persistence_comes_from_receipt_not_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'uploads'/'sample.pdf';source.parent.mkdir();source.write_bytes(b'synthetic')
            classification=dict(method='operator_selected',type_code='COMMERCIAL_CONTRACT',reason='销售合同标题',selected_by=7,selected_at='server time')
            doc=dict(doc_code='CONTRACT-01',type_code='COMMERCIAL_CONTRACT',source_filename='合同.pdf',pdf_file='uploads/sample.pdf',
                     source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),schema_version='test',classification=classification,
                     fields=[dict(key='amount',label='金额',data_type='money',value='100.01',status='accepted',required=True)])
            with patch('app.parsing.jobs.DATA_DIR',root/'runs'),patch('app.config.UPLOAD_DIR',root/'uploads'):
                receipt=jobs.save_completed(dict(documents=[doc]),7)
                submitted=DocumentIn(doc_code=doc['doc_code'],type_code=doc['type_code'],pdf_file=doc['pdf_file'],parse_run_id=receipt['parse_run_id'],
                    fields={'amount':'100.01','_parsing':{'classification':{'selected_by':999}}})
                fields,_=jobs.verified_document(submitted,7)
                self.assertEqual(fields['_parsing']['classification'],classification)
                fields['_parsing']['classification']['selected_by']=999
                reread=jobs.read_run(receipt['parse_run_id'],7)
                self.assertEqual(reread['result']['documents'][0]['classification']['selected_by'],7)
                submitted.type_code='DRAWDOWN_INSTRUCTION'
                with self.assertRaisesRegex(ValueError,'原件不匹配'):jobs.verified_document(submitted,7)


if __name__=='__main__':unittest.main()
