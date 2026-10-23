import unittest

from app.parsing.config import ParserSettings
from app.parsing.contracts import Block,Page
from app.parsing.records import normalize_records
from app.parsing.terms import clause_scopes,extract_terms,literal_row


def page(number,texts):
    return Page(number,1000,1000,b'png',[
        Block(f'p{number}b{i}',text,[.1,.1+i*.03,.8,.12+i*.03],.99,'paddle_http')
        for i,text in enumerate(texts)])


def sample():
    return [page(1,['SCHEDULE OF FACILITIES','Revolving Loan','Purpose',
                    'Working capital, including repayment only if agreed by the Lender.',
                    'Default Interest','For overdue foreign currency loans, 3% per annum plus']),
            page(2,['the applicable loan interest rate.','SCHEDULE OF FACILITIES','Import Facilities',
                    'Utilization','Clean Import Loan: not exceeding 180 days.',
                    'GENERAL TERMS AND CONDITIONS FOR FACILITIES'])]


class Model:
    def __init__(self,pages,change=None):
        self.clauses=clause_scopes(pages)[0];self.change=change;self.calls=[]

    def extract_records(self,context,spec,*,focus_page):
        self.calls.append((context,spec,focus_page))
        response=dict(records=[literal_row(c) for c in self.clauses if c.focus==focus_page],complete=True)
        return self.change(response) if self.change else response


class TermsTests(unittest.TestCase):
    def extract(self,pages=None,change=None,**settings):
        pages=pages or sample();model=Model(pages,change)
        field,attempts=extract_terms(pages,model,ParserSettings(**settings),lambda **kw:None)
        return field,attempts,model

    def test_cross_page_default_interest_stays_with_original_facility(self):
        field,attempts,model=self.extract()
        self.assertEqual(field['status'],'accepted')
        rows=field['value'];self.assertEqual(len(rows),3)
        self.assertIn('only if agreed by the Lender',rows[0]['clause_text'])
        self.assertEqual(rows[1]['facility_name'],'Revolving Loan')
        self.assertEqual(rows[1]['clause_text'],'For overdue foreign currency loans, 3% per annum plus the applicable loan interest rate.')
        self.assertEqual([s['page'] for s in field['row_results'][1]['cells']['clause_text']['sources']],[1,2])
        self.assertEqual(rows[2]['facility_name'],'Import Facilities')
        self.assertNotIn('180 days',rows[1]['clause_text'])
        self.assertFalse(any(b.text=='GENERAL TERMS AND CONDITIONS FOR FACILITIES' for p in model.calls[1][0] for b in p.blocks))

    def test_grounded_substring_that_omits_lender_condition_does_not_pass(self):
        def change(response):
            for row in response['records']:
                if row['clause_heading']=='Purpose':
                    row['clause_text']='Working capital'
                    row['cell_sources']['clause_text']['raw_value']='Working capital'
            return response
        field,_,_=self.extract(change=change)
        self.assertIsNone(field['value'])
        self.assertIn('TERMS_CLAUSE_NOT_COMPLETE',field['issues'])
        self.assertEqual(field['row_results'][0]['status'],'needs_review')

    def test_same_page_other_facility_title_is_not_valid_provenance(self):
        def change(response):
            for row in response['records']:
                if row['facility_name']=='Import Facilities':
                    row['cell_sources']['facility_name']['block_ids']=['p2b1']
            return response
        field,_,_=self.extract(change=change)
        self.assertIn('TERMS_SCOPE_MISMATCH',field['issues'])
        self.assertIsNone(field['value'])

    def test_correct_words_in_wrong_order_or_missing_continuation_are_rejected(self):
        def change(response):
            for row in response['records']:
                if row['clause_heading']=='Default Interest':
                    row['cell_sources']['clause_text']['block_ids'].reverse()
            return response
        field,_,_=self.extract(change=change)
        self.assertIn('TERMS_CLAUSE_NOT_COMPLETE',field['issues'])

    def test_model_incomplete_cannot_confer_accepted_rows(self):
        field,_,_=self.extract(change=lambda r:dict(r,complete=False))
        self.assertIsNone(field['value'])
        self.assertTrue(all(r['status']=='needs_review' for r in field['row_results']))

    def test_missing_clause_retains_only_unverified_ocr_candidate(self):
        field,_,_=self.extract(change=lambda r:dict(r,records=r['records'][1:]))
        self.assertEqual(len(field['row_results']),3)
        missing=[r for r in field['row_results'] if 'TERMS_CLAUSE_MISSING' in r['issues']]
        self.assertEqual(len(missing),2)
        self.assertTrue(all(r['value'] is None for r in missing))
        self.assertEqual(missing[0]['cells']['clause_heading']['value'],'Purpose')

    def test_missing_end_unknown_title_and_zero_budget_are_explicit(self):
        field,attempts,_=self.extract(max_terms_calls=0)
        self.assertEqual(attempts,[]);self.assertIsNone(field['value'])
        self.assertIn('TERMS_CALL_BUDGET_EXCEEDED',field['issues'])
        for texts,code in [(['SCHEDULE OF FACILITIES','Loan','Purpose','Use'], 'TERMS_SCHEDULE_END_NOT_FOUND'),
            (['SCHEDULE OF FACILITIES','Purpose','Use','GENERAL TERMS AND CONDITIONS FOR FACILITIES'],'TERMS_FACILITY_TITLE_NOT_FOUND')]:
            field,_,_=self.extract([page(1,texts)])
            self.assertIn(code,field['issues']);self.assertIsNone(field['value'])

    def test_footer_numbers_excluded_but_unclassified_margin_remains_a_gap(self):
        pages=sample();p=pages[0]
        p.blocks.extend([Block('footer','26',[.49,.87,.52,.89],.99,'paddle_http'),
                         Block('internal','INTERNAL',[.1,.97,.2,.99],.99,'paddle_http'),
                         Block('annotation','?', [.4,.92,.5,.94],.8,'paddle_http')])
        field,_,_=self.extract(pages)
        self.assertIsNone(field['value'])
        self.assertIn('TERMS_MARGIN_REVIEW_REQUIRED',field['issues'])
        self.assertEqual([m['block_id'] for m in field['margin_blocks']],['annotation'])
        self.assertNotIn('INTERNAL',field['row_results'][1]['value']['clause_text'])

    def test_scope_page_budget_prevents_incomplete_image_verification(self):
        field,_,model=self.extract(max_vision_pages_per_call=1)
        self.assertIn('TERMS_CONTEXT_PAGE_LIMIT',field['issues'])
        self.assertEqual([focus for _,_,focus in model.calls],[2])

    def test_malformed_response_does_not_escape_or_accept_deterministic_copy(self):
        for bad in [dict(records='wrong',complete=True),dict(records=[],complete='true'),
                    dict(records=[{}]*201,complete=True)]:
            field,_,_=self.extract(change=lambda r:bad)
            self.assertIsNone(field['value'])
            self.assertTrue(all(r['value'] is None for r in field['row_results']))

    def test_manual_term_schema_preserves_literal_rates_and_rejects_extra_columns(self):
        row=literal_row(clause_scopes(sample())[0][1])
        self.assertIn('3% per annum plus',normalize_records([row],'facility_terms')[0]['clause_text'])
        with self.assertRaises(ValueError):normalize_records([dict(row,interest_rate='3')],'facility_terms')

    def test_format_repair_is_one_bounded_retry_and_does_not_coerce_bad_rows(self):
        pages=sample();base=Model(pages)
        class WrongShape:
            def extract_records(self,context,spec,*,focus_page):
                response=base.extract_records(context,spec,focus_page=focus_page)
                if focus_page==1 and 'format_repair' not in spec:
                    response['records'][0]['facility_name']={'raw_value':'Revolving Loan'}
                return response
        field,attempts=extract_terms(pages,WrongShape(),ParserSettings(),lambda **kw:None)
        self.assertEqual(field['status'],'accepted')
        self.assertEqual([a['status'] for a in attempts],['invalid_format','completed','completed'])
        field,attempts=extract_terms(pages,WrongShape(),ParserSettings(max_terms_calls=1),lambda **kw:None)
        self.assertIsNone(field['value'])
        self.assertEqual(len(attempts),1)
        self.assertIn('TERMS_CALL_BUDGET_EXCEEDED',field['issues'])


if __name__=='__main__':unittest.main()
