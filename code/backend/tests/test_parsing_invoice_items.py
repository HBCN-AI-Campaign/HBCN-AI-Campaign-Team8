"""Invoice truncation isolation, cross-page row evidence and ambiguity boundaries."""
from copy import deepcopy
from unittest.mock import patch
import unittest

from app.parsing.config import ParserSettings
from app.parsing.contracts import Block, Page, ParseError
from app.parsing.invoice_items import extract_invoice_items
from app.parsing.normalization import normalize, normalize_source
from app.parsing.pipeline import ParsingPipeline
from app.parsing.registry import D


def fixture(number=1):
    values=dict(line_no=str(number),description='Kleid (Stil: W-DR-02)',quantity='1200',
                unit='PCS',unit_price='24.50',amount='29400.00',currency='USD')
    raw={**values,'unit':'Stk','amount':'29,400.00'}
    blocks=[Block('p1b'+str(i),v,[.05+i*.1,.2,.13+i*.1,.22],.99,'paddle_http')
            for i,v in enumerate(raw.values())]
    row={**values,'cell_sources':{k:dict(raw_value=v,block_ids=[blocks[i].id]) for i,(k,v) in enumerate(raw.items())}}
    pages=[Page(1,1000,1000,b'',blocks),Page(2,1000,1000,b'',[])]
    return row,pages


class Provider:
    def __init__(self, responses): self.responses=responses;self.calls=[]
    def extract_records(self,pages,spec,*,focus_page):
        self.calls.append((focus_page,[p.number for p in pages]))
        response=self.responses[focus_page]
        if isinstance(response,Exception):raise response
        return response


class InvoiceItemsTests(unittest.TestCase):
    def run_rows(self,row,pages,**kwargs):
        return extract_invoice_items(pages,Provider({1:dict(records=[row],complete=True),2:dict(records=[],complete=True)}),
                                     ParserSettings(_env_file=None),lambda **_:None,**kwargs)[0]

    def test_split_description_keeps_both_pages_and_printed_amount(self):
        row,pages=fixture()
        pages[0].blocks[1].text='Kleid'
        pages[1].blocks=[Block('p2b0','(Stil: W-DR-02)',[.05,.05,.3,.07],.99,'paddle_http')]
        row['cell_sources']['description']['block_ids'].append('p2b0')
        field=self.run_rows(row,pages)
        self.assertEqual(field['status'],'accepted')
        self.assertEqual(field['value'][0]['amount'],'29400.00')
        self.assertEqual({s['page'] for s in field['row_results'][0]['cells']['description']['sources']},{1,2})

    def test_wrong_row_alignment_and_missing_number_are_never_usable(self):
        row,pages=fixture();pages[0].blocks[2].bbox=[.2,.6,.3,.62]
        field=self.run_rows(row,pages)
        self.assertIsNone(field['value']);self.assertIn('INVOICE_ROW_ALIGNMENT_UNPROVEN',field['issues'])
        row,pages=fixture(2);field=self.run_rows(row,pages)
        self.assertIsNone(field['value']);self.assertIn('INVOICE_ROW_SEQUENCE_INCOMPLETE',field['issues'])

    def test_numeric_substrings_are_not_cell_evidence(self):
        for index,printed in ((0,'14'),(2,'11200'),(5,'129,400.00'),(5,'29,400.001')):
            with self.subTest(index=index):
                row,pages=fixture();pages[0].blocks[index].text=printed
                field=self.run_rows(row,pages)
                self.assertIsNone(field['value']);self.assertIn('CELL_QUOTE_NOT_GROUNDED',field['issues'])

    def test_numeric_quote_can_end_at_prose_punctuation(self):
        row,pages=fixture();pages[0].blocks[5].text='29,400.00, payable by T/T.'
        self.assertEqual(self.run_rows(row,pages)['status'],'accepted')

    def test_failure_incomplete_page_and_document_gap_block_collection(self):
        row,pages=fixture()
        for response in (ParseError('SEMANTIC_OUTPUT_TRUNCATED'),dict(records=[],complete=False)):
            provider=Provider({1:dict(records=[row],complete=True),2:response})
            field,attempts=extract_invoice_items(pages,provider,ParserSettings(_env_file=None),lambda **_:None)
            self.assertIsNone(field['value']);self.assertEqual(len(field['row_results']),1)
            self.assertEqual(provider.calls,[(1,[1,2]),(2,[1,2])])
        self.assertIn('DOCUMENT_INCOMPLETE',self.run_rows(row,pages,document_errors=['OCR_FAILED'])['issues'])

    def test_pipeline_keeps_table_failure_out_of_scalar_request(self):
        row,pages=fixture()
        for page in pages:page.needs_ocr=False
        class ScalarProvider(Provider):
            def extract(self,context,tcode,specs,*,visual):
                self.asserted_specs=[s['key'] for s in specs]
                assert 'line_items' not in self.asserted_specs
                return [dict(key='amount',value='29400.00',raw_value='29,400.00',block_ids=['p1b5'],visual_state='clear')]
        provider=ScalarProvider({1:ParseError('SEMANTIC_OUTPUT_TRUNCATED'),2:dict(records=[],complete=True)})
        from pathlib import Path
        with patch('app.parsing.pipeline.prepare',return_value=pages),patch.object(Path,'read_bytes',return_value=b'synthetic'):
            result=ParsingPipeline(ParserSettings(_env_file=None),ocr=object(),semantic=provider).parse_document(Path('invoice.pdf'),'invoice.pdf')
        fields={f['key']:f for f in result['fields']}
        self.assertEqual(fields['amount']['value'],'29400.00')
        self.assertIsNone(fields['line_items']['value'])
        self.assertFalse(result['issues']);self.assertEqual(result['status'],'needs_review')


class NamedDateTests(unittest.TestCase):
    def test_explicit_german_and_english_months_are_locale_independent(self):
        examples={'24. Oktober 2023':'2023-10-24','24.Oktober 2023':'2023-10-24','29. Februar 2024':'2024-02-29',
                  '3. März 2026':'2026-03-03','3 Maerz 2026':'2026-03-03',
                  'October 24, 2023':'2023-10-24','Oct.24,2023':'2023-10-24',
                  '24 Oct 2023':'2023-10-24','2023年10月24日':'2023-10-24'}
        for value,expected in examples.items():
            with self.subTest(value=value):self.assertEqual(normalize(value,'date'),expected)
        self.assertEqual(normalize_source('Datum: 24. Oktober 2023',D),'2023-10-24')
        self.assertEqual(normalize('Stk','unit'),'PCS')
        self.assertEqual(normalize_source('Rechnungsnummer: PI-2023-8843',dict(key='invoice_no',label='发票号',data_type='text')),'PI-2023-8843')
        self.assertEqual(normalize_source('Verkäufer: PHY',dict(key='seller',label='卖方',data_type='text')),'PHY')
        self.assertEqual(normalize_source('Währung: USD',dict(key='currency',label='币种',data_type='currency_code')),'USD')

    def test_legacy_rows_do_not_acquire_numbered_invoice_requirement(self):
        from app.parsing.records import ROW_MODELS
        self.assertNotIn('line_items',ROW_MODELS)

    def test_omitted_components_numeric_ambiguity_and_prose_are_rejected(self):
        for value in ('Oktober 2023','24. Oktober','24. Oktober 23','29. Februar 2023',
                      '10/11/2026','31 April 2026','24 Oktober 2023 bis 25 Oktober 2023',
                      'approximately 24 Oktober 2023','24 Wrong 2023'):
            with self.subTest(value=value),self.assertRaises(ValueError):normalize(value,'date')


if __name__=='__main__':unittest.main()
