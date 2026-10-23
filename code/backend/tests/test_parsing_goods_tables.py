"""Native table geometry routes extraction; it never supplies accepted cell values."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.parsing.contracts import Block, Page
from app.parsing.config import ParserSettings
from app.parsing.goods_tables import native_goods_scope, scope_pages
from app.parsing.invoice_items import extract_invoice_items
from app.parsing.normalization import normalize_source
from app.parsing.pipeline import ParsingPipeline
from app.parsing.registry import CN
from tests.test_parsing_invoice_items import fixture, Provider


def native_fixture():
    header=['No.','Description of Goods','HS Code','Quantity (pcs)','Unit Price (USD)','Total Amount (USD)']
    table=SimpleNamespace(bbox=(10,20,95,90),rows=[SimpleNamespace(cells=[(10,20,20,30),(20,20,40,30)])],
                          extract=lambda:[header,['1','Item','Code','2','3','6']])
    word=lambda text,x,y:dict(text=text,x0=x,x1=x+5,top=y,bottom=y+3)
    native=SimpleNamespace(width=100,height=100,find_tables=lambda:[table],
                           extract_words=lambda:[word('1',12,40),word('2',12,80)])
    blocks=[Block('p1b0','1',[.12,.4,.17,.43],.99,'paddle_http'),
            Block('p1b1','2',[.12,.8,.17,.83],.99,'paddle_http'),
            Block('p1b2','outside',[.01,.01,.1,.03],.99,'paddle_http')]
    pages=[Page(1,100,100,b'',blocks)]
    class Pdf:
        pages=[native]
        def __enter__(self):return self
        def __exit__(self,*_):pass
    return Pdf,pages,native


class GoodsScopeTests(unittest.TestCase):
    def test_native_words_recover_row_omitted_by_table_cells(self):
        pdf,pages,_=native_fixture()
        with patch('pdfplumber.open',return_value=pdf()):scope=native_goods_scope(Path('synthetic.pdf'),pages)
        self.assertEqual(scope['status'],'detected')
        self.assertEqual([r['line_no'] for r in scope['rows']],['1','2'])
        self.assertFalse(scope['issues'])
        selected=scope_pages(pages,scope)
        self.assertEqual([b.id for b in selected[0].blocks],['p1b0','p1b1'])
        self.assertEqual(len(pages[0].blocks),3)  # scalar context remains untouched

    def test_prose_and_unknown_headers_do_not_trigger_numbered_adapter(self):
        pdf,pages,native=native_fixture();native.find_tables=lambda:[]
        with patch('pdfplumber.open',return_value=pdf()):scope=native_goods_scope(Path('synthetic.pdf'),pages)
        self.assertEqual(scope['status'],'not_detected')
        self.assertFalse(scope['rows'])

    def test_duplicate_or_gapped_native_numbers_do_not_prove_completeness(self):
        for value in ('1','3'):
            pdf,pages,native=native_fixture()
            words=native.extract_words();words[-1]['text']=value;native.extract_words=lambda:words
            with patch('pdfplumber.open',return_value=pdf()):scope=native_goods_scope(Path('synthetic.pdf'),pages)
            self.assertIn('NATIVE_TABLE_ROW_SEQUENCE_UNPROVEN',scope['issues'])

    def test_no_native_text_and_reader_failure_are_explicit_fallbacks(self):
        pdf,pages,native=native_fixture();native.extract_words=lambda:[]
        with patch('pdfplumber.open',return_value=pdf()):scope=native_goods_scope(Path('synthetic.pdf'),pages)
        self.assertEqual(scope['status'],'not_detected')
        with patch('pdfplumber.open',side_effect=ValueError('bad pdf')):
            scope=native_goods_scope(Path('synthetic.pdf'),pages)
        self.assertEqual(scope['status'],'unavailable')
        self.assertIn('NATIVE_TABLE_SCOPE_UNAVAILABLE',scope['issues'])


class GoodsCoverageTests(unittest.TestCase):
    def test_missing_terminal_row_fails_even_when_model_says_complete(self):
        row,pages=fixture()
        expected=[dict(line_no='1',page=1,bbox=pages[0].blocks[0].bbox),dict(line_no='2',page=2,bbox=[.05,.2,.13,.22])]
        field,_=extract_invoice_items(pages,Provider({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
            ParserSettings(_env_file=None),lambda **_:None,expected_rows=expected)
        self.assertIsNone(field['value']);self.assertIn('TABLE_ROW_COVERAGE_INCOMPLETE',field['issues'])

    def test_native_anchor_location_must_match_registered_block(self):
        row,pages=fixture()
        expected=[dict(line_no='1',page=1,bbox=[.05,.7,.13,.72])]
        field,_=extract_invoice_items(pages,Provider({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
            ParserSettings(_env_file=None),lambda **_:None,expected_rows=expected)
        self.assertIsNone(field['value']);self.assertIn('TABLE_ROW_ANCHOR_MISMATCH',field['issues'])

    def test_matching_native_coverage_uses_existing_cell_evidence(self):
        row,pages=fixture()
        expected=[dict(line_no='1',page=1,bbox=deepcopy(pages[0].blocks[0].bbox))]
        field,_=extract_invoice_items(pages,Provider({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
            ParserSettings(_env_file=None),lambda **_:None,expected_rows=expected)
        self.assertEqual(field['status'],'accepted')
        self.assertEqual(field['value'][0]['amount'],'29400.00')
        self.assertEqual(field['row_results'][0]['cells']['amount']['sources'][0]['method'],'paddle_http')

    def test_contract_pipeline_splits_only_after_positive_scope(self):
        row,pages=fixture()
        for p in pages:p.needs_ocr=False
        scope=dict(status='detected',method='test_geometry',regions=[dict(page=1,bbox=[0,0,1,1]),dict(page=2,bbox=[0,0,1,1])],description_sources=[],
                   rows=[dict(line_no='1',page=1,bbox=pages[0].blocks[0].bbox)],issues=[])
        class Semantic(Provider):
            def extract(self,context,tcode,specs,*,visual):
                assert tcode=='COMMERCIAL_CONTRACT'
                assert 'line_items' not in [s['key'] for s in specs]
                return [dict(key='amount',value='29400.00',raw_value='29,400.00',block_ids=['p1b5'],visual_state='clear')]
        semantic=Semantic({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)})
        with patch('app.parsing.pipeline.prepare',return_value=pages),patch('app.parsing.goods_tables.native_goods_scope',return_value=scope),patch.object(Path,'read_bytes',return_value=b'synthetic'):
            doc=ParsingPipeline(ParserSettings(_env_file=None),ocr=object(),semantic=semantic).parse_document(Path('合同.pdf'),'合同.pdf',type_code='COMMERCIAL_CONTRACT')
        by_key={f['key']:f for f in doc['fields']}
        self.assertEqual(by_key['amount']['value'],'29400.00')
        self.assertEqual(by_key['line_items']['status'],'accepted')
        self.assertEqual(doc['goods_table_scope'],scope)
        self.assertEqual(by_key['line_items']['table_scope'],scope)

    def test_unclaimed_continuation_and_partial_block_quotes_block_collection(self):
        for partial in (False,True):
            row,pages=fixture()
            source=dict(block_id='p2b0',page=2,bbox=[.05,.05,.3,.07],text='(Stil: W-DR-02)')
            if partial:
                # The cited block contains more text than the returned quote.
                source=dict(block_id=pages[0].blocks[1].id,page=1,bbox=pages[0].blocks[1].bbox,
                            text=pages[0].blocks[1].text+' omitted suffix')
            field,_=extract_invoice_items(pages,Provider({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
                ParserSettings(_env_file=None),lambda **_:None,expected_description_sources=[source])
            self.assertIsNone(field['value']);self.assertIn('TABLE_DESCRIPTION_COVERAGE_INCOMPLETE',field['issues'])
            self.assertEqual(field['uncovered_description_sources'],[source])

    def test_leading_description_is_supplied_as_a_visual_question_not_a_gold_value(self):
        row,pages=fixture()
        gap=dict(block_id='p2b0',page=2,bbox=[.1,.1,.3,.12],text='actual continuation')
        expected=[dict(line_no='1',page=1,bbox=pages[0].blocks[0].bbox),dict(line_no='2',page=2,bbox=[.05,.3,.1,.32])]
        class Inspect(Provider):
            def extract_records(self,pages,spec,*,focus_page):
                if focus_page==1:
                    assert spec['possible_continuation_sources']==[gap]
                    assert '不确定则complete=false' in spec['note']
                else:assert 'possible_continuation_sources' not in spec
                return super().extract_records(pages,spec,focus_page=focus_page)
        field,_=extract_invoice_items(pages,Inspect({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
            ParserSettings(_env_file=None),lambda **_:None,expected_rows=expected,expected_description_sources=[gap])
        self.assertIsNone(field['value'])  # a hint never auto-attaches the words

    def test_explicit_source_labels_keep_identifier_suffix_and_account_digits(self):
        self.assertEqual(normalize_source('Contract No.: PI-2023-8843-CONTRACT',CN),'PI-2023-8843-CONTRACT')
        spec=dict(key='payee_account',label='收款账号',data_type='account')
        self.assertEqual(normalize_source('Account No: 001234567890',spec),'001234567890')
        with self.assertRaises(ValueError):normalize_source('Other No: 001234567890',spec)


if __name__=='__main__':unittest.main()
