from copy import deepcopy
import unittest

from app.parsing.term_facts import derive_term_facts,applicable_terms,date_span_observation,REVOLVER,IMPORT,ACCEPTANCE
from app.parsing.facility import analyze_facility,verified_dtos
from app.rule_engine.base import DocBundle,Status
from app.rule_engine.rules import R_DrawdownCurrencyInFacilityScope,R_DrawdownLoanTenor
from tests.test_parsing_facility import documents,at,as_verified
from scripts.score_parser_term_facts import score


def clause(name,heading,text,page=28):
    value=dict(facility_name=name,clause_heading=heading,clause_text=text)
    return dict(value=value,status='accepted',issues=[],cells={k:dict(value=v,raw_value=v,issues=[],
        sources=[dict(block_id=f'p{page}-{k}',page=page,bbox=[.1,.2,.8,.8],text=v,method='synthetic',score=.99)])
        for k,v in value.items()})


def revolving(**values):
    return REVOLVER.format(**dict(dict(ccy1='RMB',ccy2='USD',limit_ccy='USD',notice=3,
        period1=1,period2=3,period3=6,maximum=12),**values))


def importing(**values):
    return IMPORT.format(**dict(dict(ccy1='RMB',ccy2='USD',limit_ccy='USD',cil_days=180,reimbursement_days=180),**values))


class TermFactsTests(unittest.TestCase):
    def derive(self,rows,status='accepted',errors=None):return derive_term_facts(rows,status,errors)

    def test_complete_revolver_types_capture_values_instead_of_hardcoding_set8(self):
        rows=[clause('Loan A','Utilization',revolving(ccy1='EUR',ccy2='GBP',period1=2,period2=4,period3=8,maximum=14))]
        original=deepcopy(rows);d=self.derive(rows);facts=d['facilities'][0]['facts']
        self.assertEqual(facts['permitted_currencies']['value']['currencies'],['EUR','GBP'])
        tenor=facts['loan_tenor']['value']
        self.assertEqual([p['count'] for p in tenor['standard_periods']],[2,4,8])
        self.assertEqual(tenor['absolute_maximum'],dict(count=14,unit='months'))
        self.assertTrue(tenor['other_period_requires_lender_agreement'])
        self.assertTrue(tenor['maximum_includes_extensions_and_rollovers'])
        self.assertEqual(rows,original)

    def test_appended_exception_or_deleted_condition_cannot_be_ignored(self):
        texts=[revolving()+' However USD utilization is prohibited.',
               revolving().replace('or such other period as agreed by the Lender.','.'),
               revolving().replace('(including any extension or rollover)','')]
        for text in texts:
            with self.subTest(text=text):
                facts=self.derive([clause('A','Utilization',text)])['facilities'][0]['facts']
                self.assertIsNone(facts['permitted_currencies']['value'])
                self.assertIsNone(facts['loan_tenor']['value'])

    def test_inconsistent_or_unbounded_periods_are_not_usable(self):
        for changes in [dict(period3=18),dict(period1=3),dict(maximum=9999)]:
            f=self.derive([clause('A','Utilization',revolving(**changes))])['facilities'][0]['facts']
            self.assertEqual(f['loan_tenor']['issues'],['TERMS_TYPED_VALUE_INVALID'])

    def test_import_children_have_explicit_product_scope_and_distinct_day_caps(self):
        d=self.derive([clause('Import Facilities','Utilization',importing(cil_days=90,reimbursement_days=170),30)])
        parent=applicable_terms(d,'Import Facilities')
        self.assertIsNone(parent['facts']['loan_tenor']['value'])
        self.assertEqual(parent['facts']['loan_tenor']['issues'],['TERMS_SUBFACILITY_REQUIRED'])
        for name,days in [('Facility for Clean Import Loan',90),('Facility for Reimbursement Finance',170)]:
            child=applicable_terms(d,name)
            self.assertEqual(child['scope_method'],'explicit_named_subfacility')
            self.assertEqual(child['facts']['loan_tenor']['value']['absolute_maximum'],dict(count=days,unit='days'))
            self.assertEqual(child['facts']['permitted_currencies']['value']['currencies'],['CNY','USD'])
        self.assertEqual(applicable_terms(d,'Clean Import')['issues'],['TERMS_FACILITY_NOT_UNIQUE'])

    def test_acceptance_draft_tenors_are_not_revolving_loan_tenors(self):
        text=ACCEPTANCE.format(paper_months=4,electronic_months=7)
        f=self.derive([clause('Draft acceptance','Utilization',text)])['facilities'][0]['facts']
        self.assertEqual(f['permitted_currencies']['value']['currencies'],['CNY'])
        tenor=f['loan_tenor']['value']
        self.assertEqual(tenor['maximum_scope'],'each_draft')
        self.assertEqual(tenor['standard_periods'],[])
        self.assertEqual(tenor['instrument_maxima']['electronic']['count'],7)
        self.assertIsNone(tenor['absolute_maximum'])

    def test_draft_discount_cannot_inherit_acceptance_or_import_tenor(self):
        d=self.derive([clause('Discount','Purpose','Detailed terms are in a separate Master Agreement.'),
            clause('Acceptance','Utilization',ACCEPTANCE.format(paper_months=6,electronic_months=6))])
        f=applicable_terms(d,'Discount')['facts']
        self.assertIsNone(f['loan_tenor']['value']);self.assertIsNone(f['permitted_currencies']['value'])

    def test_unverified_visual_row_incomplete_register_and_duplicate_heading_stay_unresolved(self):
        r=clause('A','Utilization',revolving());r['status']='needs_review'
        f=self.derive([r])['facilities'][0]['facts']
        self.assertIsNone(f['permitted_currencies']['value'])
        r['status']='accepted';entry=self.derive([r],status='needs_review')['facilities'][0]
        self.assertEqual(entry['status'],'needs_review')
        self.assertEqual(entry['facts']['permitted_currencies']['status'],'accepted')
        d=self.derive([r,deepcopy(r)])
        self.assertIn('TERMS_DUPLICATE_CLAUSE_HEADING',d['facilities'][0]['issues'])
        self.assertIsNone(d['facilities'][0]['facts']['loan_tenor']['value'])

    def test_changed_manual_value_cannot_reuse_old_machine_quote_or_location(self):
        r=clause('A','Utilization',revolving());r['status']='confirmed'
        r['value']['clause_text']=revolving(maximum=24)
        facts=self.derive([r])['facilities'][0]['facts']
        self.assertIsNone(facts['loan_tenor']['value'])
        self.assertEqual(facts['loan_tenor']['evidence'],{})
        r['cells']=None
        self.assertIsNone(self.derive([r])['facilities'][0]['facts']['loan_tenor']['value'])

    def test_default_interest_is_preserved_separately_and_never_fills_ordinary_rate(self):
        f=self.derive([clause('A','Default Interest','150% of applicable interest and 3% per annum plus applicable rate.')])['facilities'][0]['facts']
        self.assertNotIn('interest',f)
        self.assertIn('150%',f['default_interest']['value']['clause_text'])
        self.assertNotIn('interest_rate',f)

    def test_date_difference_is_not_a_month_or_an_interest_period(self):
        observed=date_span_observation('2026-10-12','2026-11-11')
        self.assertEqual(observed['elapsed_days'],30)
        self.assertEqual(observed['status'],'needs_review')
        self.assertNotIn('months',observed)
        self.assertEqual(date_span_observation('2024-02-28','2024-03-01')['elapsed_days'],2)
        self.assertIsNone(date_span_observation(None,'2026-11-11')['elapsed_days'])
        self.assertEqual(date_span_observation('2026-11-11','2026-10-12')['issue'],'TENOR_DATE_ORDER_INVALID')

    def test_selected_scope_recomputed_without_using_global_currency_or_cached_projection(self):
        docs=documents();r=clause('Revolving Loan','Utilization',revolving(ccy1='USD',ccy2='EUR'))
        docs[0]['fields'].append(dict(key='facility_terms',label='terms',status='accepted',required=False,
            value=[r['value']],data_type='rows',row_results=[r],term_facts={'forged':'cached projection'}))
        c=analyze_facility(docs)
        self.assertEqual(c['term_application']['facts']['permitted_currencies']['value']['currencies'],['USD','EUR'])
        self.assertEqual(c['status'],'ready')
        at(docs,'DD-01','currency')['value']='CNY'
        c=analyze_facility(docs)
        self.assertIn('PERMITTED_CURRENCY_UNVERIFIED',[i['code'] for i in c['issues']])
        at(docs,'FOL-01','facility_terms')['status']='needs_review'
        c=analyze_facility(docs)
        self.assertEqual(c['status'],'needs_review')
        self.assertIn('FACILITY_TERMS_UNVERIFIED',[i['code'] for i in c['issues']])

    def test_rule_uses_selected_scope_and_location_never_global_fallback(self):
        application=applicable_terms(self.derive([clause('A','Utilization',revolving(ccy1='USD',ccy2='EUR'))]),'A')
        context=dict(status='ready',term_application=application)
        bundle=DocBundle({'DRAWDOWN_INSTRUCTION':[dict(currency='USD',tranche='A')],
            'FACILITY_LETTER':[dict(allowed_currencies=['CNY'],_facility_context=context)]},
            meta_by_type={'FACILITY_LETTER':[dict(doc_code='FOL-01',pdf_file='uploads/synthetic.pdf')]})
        rule=R_DrawdownCurrencyInFacilityScope()
        result=rule.evaluate(bundle);self.assertEqual(result.status,Status.PASS)
        self.assertEqual(result.detail[2][3]['page'],28)
        bundle.by_type['DRAWDOWN_INSTRUCTION'][0]['currency']='CNY'
        self.assertEqual(rule.evaluate(bundle).status,Status.FAIL)
        application['status']='needs_review'
        self.assertEqual(rule.evaluate(bundle).status,Status.WARN)
        bundle.by_type['FACILITY_LETTER'][0].pop('_facility_context')
        bundle.by_type['FACILITY_LETTER'][0]['facility_terms']=[]
        self.assertEqual(rule.evaluate(bundle).status,Status.WARN)

    def test_changed_after_persistence_invalidates_term_evidence(self):
        docs=documents();r=clause('Revolving Loan','Utilization',revolving())
        docs[0]['fields'].append(dict(key='facility_terms',label='terms',status='accepted',required=False,
            value=[r['value']],data_type='rows',row_results=[r]))
        verified=as_verified(docs)
        verified[0].fields['facility_terms'][0]['clause_text']=revolving(maximum=24)
        self.assertEqual(analyze_facility(verified_dtos(verified))['term_application']['status'],'needs_review')

    def test_tenor_rule_preserves_conditions_and_cannot_pass_based_on_interest_period(self):
        application=applicable_terms(self.derive([clause('A','Utilization',revolving())]),'A')
        # A 30-day observation and a one-month interest period do not establish
        # the contractual month convention or lender approval for this loan.
        dd=dict(drawdown_date='2026-10-12',maturity_date='2026-11-11',interest_period='1 month')
        bundle=DocBundle({'DRAWDOWN_INSTRUCTION':[dd], 'FACILITY_LETTER':[dict(
            _facility_context=dict(status='ready',term_application=application))]})
        rule=R_DrawdownLoanTenor();result=rule.evaluate(bundle)
        self.assertEqual(result.status,Status.WARN)
        self.assertIn('1个月 / 3个月 / 6个月',result.detail[1][1])
        self.assertIn('其他期限须贷款人同意',result.detail[1][1])
        self.assertIn('包括延期和展期的绝对上限：12个月',result.detail[1][1])
        self.assertEqual(result.detail[1][3]['page'],28)
        self.assertIn('30天；不是已核实贷款期限',result.detail[-1][1])
        dd['maturity_date']='2027-11-11'
        self.assertEqual(rule.evaluate(bundle).status,Status.WARN)
        application['status']='needs_review'
        result=rule.evaluate(bundle)
        self.assertEqual(result.status,Status.WARN)
        self.assertNotIn('12个月',str(result.detail))

    def test_tenor_rule_never_borrows_other_product_caps(self):
        application=applicable_terms(self.derive([clause('Import','Utilization',importing(cil_days=90,reimbursement_days=170))]),'Import')
        bundle=DocBundle({'DRAWDOWN_INSTRUCTION':[dict(interest_period='90 days')], 'FACILITY_LETTER':[dict(
            _facility_context=dict(status='ready',term_application=application))]})
        result=R_DrawdownLoanTenor().evaluate(bundle)
        self.assertEqual(result.status,Status.WARN)
        self.assertEqual(result.detail,[])
        bundle.by_type['FACILITY_LETTER'][0]={}
        self.assertEqual(R_DrawdownLoanTenor().evaluate(bundle).status,Status.SKIP)

    def test_gold_scorer_rebuilds_and_detects_changed_numbers_and_missing_evidence(self):
        r=clause('A','Utilization',revolving())
        gold=dict(sha256='synthetic',scope_must_remain_unresolved=True,facilities=[dict(
            name='A',currencies=['CNY','USD'],limit_currency='USD',pages=[28],tenor=dict(
                standard_months=[1,3,6],maximum=dict(count=12,unit='months'),
                other_requires_agreement=True,includes_extensions=True))])
        result=dict(source_sha256='synthetic',fields=[dict(key='facility_terms',status='needs_review',
            row_results=[r],term_facts={'forged':'all accepted'})])
        self.assertTrue(score(gold,result)['passed'])
        result['fields'][0]['row_results']=[clause('A','Utilization',revolving(maximum=24))]
        self.assertFalse(score(gold,result)['passed'])
        result['fields'][0]['row_results'][0]['cells']={}
        self.assertFalse(score(gold,result)['passed'])
        result['source_sha256']='different-source'
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH_MISMATCH'):score(gold,result)


if __name__=='__main__':unittest.main()
