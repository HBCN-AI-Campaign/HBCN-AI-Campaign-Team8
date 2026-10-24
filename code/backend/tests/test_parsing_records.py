import unittest
from app.parsing.config import ParserSettings
from app.parsing.contracts import Block,Page,ParseError
from app.parsing.records import normalize_records,validate_record,merge_records
from app.parsing.structured import extract_structures,section_pages


def page(number,texts):
    return Page(number,1000,1000,b'png',[Block(f'p{number}b{i}',t,[.1,.1+i*.03,.8,.12+i*.03],.99,'paddle_http') for i,t in enumerate(texts)])


def row(name='Alpha Ltd',amount='1000000',ids=None):
    ids=ids or {'facility_name':'p1b0','amount':'p1b1','currency':'p1b1'}
    return dict(facility_name=name,amount=amount,currency='USD',cell_sources={
        'facility_name':dict(raw_value=name,block_ids=[ids['facility_name']]),
        'amount':dict(raw_value='USD1,000,000',block_ids=[ids['amount']]),
        'currency':dict(raw_value='USD',block_ids=[ids['currency']])})


class RecordTests(unittest.TestCase):
    def test_typed_money_and_unrecognized_nested_fields(self):
        self.assertEqual(normalize_records([row(amount='9007199254740993.01')],'facility_limits')[0]['amount'],'9007199254740993.01')
        for value in [dict(row(),amount=True),dict(row(),amount='1e6'),dict(row(),allocations=[{'amount':'999'}])]:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_records([value],'facility_limits')

    def test_per_cell_quotes_and_source_coordinates(self):
        p=page(1,['Alpha Ltd','USD1,000,000'])
        r=validate_record(row(),'facility_limits',[p])
        self.assertEqual(r['status'],'accepted')
        self.assertEqual(r['cells']['amount']['sources'][0]['bbox'],p.blocks[1].bbox)
        wrong=row(amount='2000000')
        self.assertIn('CELL_VALUE_SOURCE_MISMATCH',validate_record(wrong,'facility_limits',[p])['issues'])

    def test_unknown_cell_ids_or_missing_quote_do_not_pass(self):
        p=page(1,['Alpha Ltd','USD1,000,000']);r=row()
        r['cell_sources']['amount']['block_ids']=['p2b0']
        self.assertIn('CELL_EVIDENCE_MISSING',validate_record(r,'facility_limits',[p])['issues'])
        r=row();r['cell_sources']['amount']['raw_value']=''
        self.assertIn('CELL_QUOTE_NOT_GROUNDED',validate_record(r,'facility_limits',[p])['issues'])
        r['cell_sources']['amount']['raw_value']=123
        self.assertIn('CELL_QUOTE_NOT_GROUNDED',validate_record(r,'facility_limits',[p])['issues'])

    def test_split_name_crosses_pages_without_conflating_chinese_and_short_name(self):
        a=page(1,['ABCD AUTOMOTIVE']);b=page(2,['PROCESSING CENTER CO., LTD','ABCD（苏州）汽车配件制造有限公司','Suzhou ABCD'])
        r={'name':'ABCD AUTOMOTIVE PROCESSING CENTER CO., LTD','short_name':'Suzhou ABCD',
           'name_local':'ABCD（苏州）汽车配件制造有限公司','cell_sources':{
               'name':{'raw_value':'ABCD AUTOMOTIVE PROCESSING CENTER CO., LTD','block_ids':['p1b0','p2b0']},
               'short_name':{'raw_value':'Suzhou ABCD','block_ids':['p2b2']},
               'name_local':{'raw_value':'ABCD（苏州）汽车配件制造有限公司','block_ids':['p2b1']}}}
        self.assertEqual(validate_record(r,'borrowers',[a,b])['status'],'accepted')

    def test_currency_from_other_cell_cannot_change_the_amounts_currency(self):
        p=page(1,['Alpha Ltd','USD1,000,000','CNY']);r=row();r['currency']='CNY'
        self.assertIn('CELL_VALUE_SOURCE_MISMATCH',validate_record(r,'facility_limits',[p])['issues'])
        r['cell_sources']['currency']={'raw_value':'CNY','block_ids':['p1b2']}
        self.assertIn('AMOUNT_CURRENCY_MISMATCH',validate_record(r,'facility_limits',[p])['issues'])

    def test_printed_label_wrappers_normalize_without_losing_original_quotes(self):
        p=page(1,['(3) Facility for Bank Acceptance:','USD1,000,000'])
        r=row('(3) Facility for Bank Acceptance')
        r['cell_sources']['facility_name']['raw_value']='(3) Facility for Bank Acceptance:'
        result=validate_record(r,'facility_limits',[p])
        self.assertEqual(result['status'],'accepted')
        self.assertEqual(result['value']['facility_name'],'Facility for Bank Acceptance')
        self.assertEqual(result['cells']['facility_name']['raw_value'],'(3) Facility for Bank Acceptance:')
        borrower=normalize_records([{'name':'Alpha (China) Ltd','short_name':'(Alpha China)',
            'name_local':'（甲（中国）有限公司）'}],'borrowers')[0]
        self.assertEqual(borrower,{'name':'Alpha (China) Ltd','short_name':'Alpha China','name_local':'甲(中国)有限公司'})

    def test_invalid_amount_keeps_partial_cells_for_business_review_without_typed_value(self):
        p=page(1,['Facility A','POS-QD','USD]0,000,000']);p.blocks[2].bbox=p.blocks[1].bbox
        r=row('Facility A',amount=']0,000,000',ids={'facility_name':'p1b0','amount':'p1b2','currency':'p1b2'})
        r['borrower_name']='POS-QD';r['cell_sources']['borrower_name']={'raw_value':'POS-QD','block_ids':['p1b1']}
        r['cell_sources']['amount']['raw_value']='USD]0,000,000'
        result=validate_record(r,'borrower_allocations',[p])
        self.assertIsNone(result['value']);self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['cells']['borrower_name']['value'],'POS-QD')
        self.assertEqual(result['cells']['amount']['sources'][0]['page'],1)
        self.assertIn('INVALID_ROW_SCHEMA',result['issues'])

    def test_borrower_and_amount_cannot_be_taken_from_different_rows(self):
        p=page(1,['Facility X','Borrower A','USD1,000,000'])
        r=row('Facility X',ids={'facility_name':'p1b0','amount':'p1b2','currency':'p1b2'})
        r['borrower_name']='Borrower A';r['cell_sources']['borrower_name']={'raw_value':'Borrower A','block_ids':['p1b1']}
        self.assertIn('ALLOCATION_ROW_ALIGNMENT_UNPROVEN',validate_record(r,'borrower_allocations',[p])['issues'])
        p.blocks[2].bbox=[.8,.13,.95,.15]
        self.assertEqual(validate_record(r,'borrower_allocations',[p])['status'],'accepted')

    def test_distinct_chunks_append_and_exact_repeats_deduplicate(self):
        a=validate_record(row(),'facility_limits',[page(1,['Alpha Ltd','USD1,000,000'])])
        b=validate_record(row('Beta Ltd'),'facility_limits',[page(1,['Beta Ltd','USD1,000,000'])])
        merged=merge_records('facility_limits',[a,b,a])
        self.assertEqual(len(merged),2)
        self.assertTrue(all(r['status']=='accepted' for r in merged))
        self.assertEqual(len(merged[0]['repeated_evidence']),1)

    def test_same_facility_with_different_limits_is_not_last_writer_wins(self):
        a=validate_record(row(),'facility_limits',[page(1,['Alpha Ltd','USD1,000,000'])])
        other=row(amount='2000000');other['cell_sources']['amount']['raw_value']='USD2,000,000'
        b=validate_record(other,'facility_limits',[page(1,['Alpha Ltd','USD2,000,000'])])
        merged=merge_records('facility_limits',[a,b])
        self.assertEqual([r['status'] for r in merged],['conflict','conflict'])
        self.assertEqual([r['value']['amount'] for r in merged],['1000000','2000000'])

    def test_valid_repeat_can_revalidate_same_values_but_retains_bad_source(self):
        p=page(1,['Alpha Ltd','USD1,000,000']);bad=row();bad['cell_sources']['amount']['block_ids']=['unknown']
        merged=merge_records('facility_limits',[validate_record(bad,'facility_limits',[p]),validate_record(row(),'facility_limits',[p])])
        self.assertEqual(merged[0]['status'],'accepted')
        self.assertEqual(merged[0]['repeated_evidence'][0]['status'],'needs_review')

    def test_repeat_cannot_erase_a_conflict_and_blank_names_are_invalid(self):
        p=page(1,['Alpha Ltd','USD1,000,000']);a=validate_record(row(),'facility_limits',[p])
        other=row(amount='2000000');other['cell_sources']['amount']['raw_value']='USD2,000,000'
        b=validate_record(other,'facility_limits',[page(1,['Alpha Ltd','USD2,000,000'])])
        merged=merge_records('facility_limits',[a,b,a])
        self.assertEqual([r['status'] for r in merged],['conflict','conflict'])
        with self.assertRaises(ValueError):normalize_records([dict(row(),facility_name='  ')],'facility_limits')

    def test_section_scope_does_not_admit_lender_or_security_names(self):
        pages=[page(1,['Borrower:','Alpha Ltd']),page(2,['Beta Ltd','Lender:','Bank Ltd','Facility/Amount:']),
               page(3,['Security:','Guarantor Ltd'])]
        self.assertEqual(section_pages(pages,'borrowers'),([1,2],None))
        calls=[]
        class Model:
            def extract_records(self,context,spec,*,focus_page):
                calls.append((spec['key'],[b.text for p in context for b in p.blocks]))
                return {'records':[],'complete':True}
        extract_structures(pages,Model(),ParserSettings(),lambda **kw:None)
        borrowers=[words for key,words in calls if key=='borrowers']
        self.assertTrue(borrowers)
        self.assertFalse(any('Bank Ltd' in words or 'Guarantor Ltd' in words for words in borrowers))

    def test_missing_boundary_or_budget_is_explicit_and_does_not_call_model(self):
        class Model:
            def extract_records(self,*args,**kwargs):raise AssertionError('must not call')
        fields,attempts=extract_structures([page(1,['Borrower:','Alpha'])],Model(),ParserSettings(),lambda **kw:None)
        self.assertIn('STRUCTURE_SECTION_END_NOT_FOUND',fields[0]['issues'])
        pages=[page(1,['Borrower:','Alpha','Lender:','Facility/Amount:','Security:'])]
        fields,attempts=extract_structures(pages,Model(),ParserSettings(max_structure_calls=0),lambda **kw:None)
        self.assertIn('STRUCTURE_CALL_BUDGET_EXCEEDED',fields[0]['issues'])
        self.assertEqual(attempts,[])


if __name__=='__main__':unittest.main()
