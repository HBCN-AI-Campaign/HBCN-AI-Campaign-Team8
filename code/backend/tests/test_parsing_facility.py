"""Synthetic association fixtures: no gold labels, OCR or model calls."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from app.parsing.facility import analyze_facility, attach_facility_context, verified_dtos
from app.rule_engine import run_all
from app.rule_engine.base import DocBundle, Status
from app.rule_engine.rules import R_DrawdownAmountWithinFacility,R_DrawdownCurrencyInFacilityScope,R_DrawdownTranche


def field(key,value,data_type='text',**extra):
    return dict(key=key,label=key,value=value,status='accepted',required=False,data_type=data_type,**extra)


def row(value,page=7):
    return dict(value=value,status='accepted',issues=[],cells={k:dict(value=v,raw_value=str(v),issues=[],
        sources=[dict(block_id=f'p{page}-{k}',page=page,bbox=[.1,.2,.4,.3],text=str(v),method='synthetic',score=1)])
        for k,v in value.items()})


def documents():
    return [dict(doc_code='FOL-01',type_code='FACILITY_LETTER',source_sha256='a'*64,issues=[],fields=[
        field('borrowers',[{'name':'Alpha Ltd.','short_name':'ALPHA','name_local':'甲公司'}],
            row_results=[row({'name':'Alpha Ltd.','short_name':'ALPHA','name_local':'甲公司'},5)],data_type='rows'),
        field('borrower_allocations',[{'borrower_name':'ALPHA','facility_name':'Revolving Loan','amount':'1000.01','currency':'USD'}],
            row_results=[row({'borrower_name':'ALPHA','facility_name':'Revolving Loan','amount':'1000.01','currency':'USD'},8)],data_type='rows'),
        field('facility_limits',[{'facility_name':'Revolving Loan','amount':'6000.00','currency':'USD'}],
            row_results=[row({'facility_name':'Revolving Loan','amount':'6000.00','currency':'USD'})],data_type='rows'),
        field('allowed_currencies',['USD','CNY'],data_type='list'),
    ]),dict(doc_code='DD-01',type_code='DRAWDOWN_INSTRUCTION',source_sha256='b'*64,issues=[],fields=[
        field('borrower','甲公司'),field('facility','Revolving Loan'),field('currency','USD',data_type='currency_code'),field('amount','1000.00',data_type='money'),
    ])]


def at(docs,code,key):
    return next(f for d in docs if d['doc_code']==code for f in d['fields'] if f['key']==key)


def as_verified(docs):
    result=[]
    for d in docs:
        fields={f['key']:deepcopy(f['value']) for f in d['fields']}
        fields['_parsing']=dict(source_sha256=d['source_sha256'],document_errors=d['issues'],fields={
            f['key']:dict(machine=deepcopy(f),final_value=deepcopy(f['value']),status=f['status']) for f in d['fields']})
        result.append(SimpleNamespace(doc_code=d['doc_code'],type_code=d['type_code'],fields=fields,field_sources={},pdf_file='uploads/synthetic.pdf'))
    return result


def selection(context,**extra):
    return dict(borrower_id=context['borrowers'][0]['id'],allocation_id=context['allocations'][0]['id'],reason='对照两份原件，确认中英文授信名称对应关系',**extra)


class FacilityTests(unittest.TestCase):
    def test_registered_local_name_and_same_currency_limit(self):
        context=analyze_facility(documents())
        self.assertEqual(context['status'],'ready')
        self.assertEqual(context['nominal_limit']['amount'],'1000.01')
        self.assertEqual(context['comparison'],'within_nominal_limit')
        self.assertIsNone(context['available_balance'])
        self.assertEqual(context['association_method'],'exact_registered_name')

    def test_cross_currency_never_compares_numbers(self):
        docs=documents();at(docs,'DD-01','currency')['value']='CNY'
        at(docs,'DD-01','amount')['value']='5000'
        context=analyze_facility(docs)
        self.assertIsNone(context['comparison'])
        self.assertIn('CROSS_CURRENCY_COMPARISON',[i['code'] for i in context['issues']])

    def test_translated_facility_relation_is_separate_from_extracted_facts(self):
        docs=documents();at(docs,'DD-01','facility')['value']='人民币循环贷款授信'
        original=deepcopy(docs);context=analyze_facility(docs)
        self.assertEqual(context['status'],'needs_review')
        linked=analyze_facility(docs,selection(context))
        self.assertEqual(linked['status'],'ready')
        self.assertEqual(linked['association_method'],'human_confirmed')
        self.assertEqual(docs,original)

    def test_selection_does_not_fill_missing_drawdown_borrower(self):
        docs=documents();at(docs,'DD-01','borrower').update(value=None,status='missing')
        linked=analyze_facility(docs,selection(analyze_facility(docs)))
        self.assertEqual(linked['status'],'needs_review')
        self.assertIsNone(linked['request']['borrower']['value'])
        self.assertIn('DRAWDOWN_BORROWER_UNRESOLVED',[i['code'] for i in linked['issues']])

    def test_different_borrower_cannot_be_overridden_by_relation_reason(self):
        docs=documents();at(docs,'DD-01','borrower')['value']='Other Legal Company'
        linked=analyze_facility(docs,selection(analyze_facility(docs)))
        self.assertIn('BORROWER_MISMATCH',[i['code'] for i in linked['issues']])

    def test_alias_typos_are_not_fuzzy_matched(self):
        docs=documents();at(docs,'FOL-01','borrower_allocations')['row_results'][0]['value']['borrower_name']='ALPHAA'
        context=analyze_facility(docs)
        self.assertEqual(context['allocations'][0]['borrower_ids'],[])
        with self.assertRaisesRegex(ValueError,'不唯一对应'):analyze_facility(docs,selection(context))

    def test_unknown_changed_source_and_cross_borrower_ids_are_rejected(self):
        docs=documents();chosen=selection(analyze_facility(docs))
        docs[0]['source_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'已失效'):analyze_facility(docs,chosen)
        chosen['borrower_id']='d'*64
        with self.assertRaises(ValueError):analyze_facility(documents(),chosen)

    def test_reason_required_and_extra_selection_values_rejected(self):
        docs=documents();chosen=selection(analyze_facility(docs));chosen['reason']=' '
        with self.assertRaisesRegex(ValueError,'核实依据'):analyze_facility(docs,chosen)
        chosen['reason']='对照原件';chosen['amount']='9999999'
        with self.assertRaises(ValueError):analyze_facility(docs,chosen)

    def test_unclear_row_cannot_be_selected(self):
        docs=documents();at(docs,'FOL-01','borrower_allocations')['row_results'][0]['status']='conflict'
        with self.assertRaisesRegex(ValueError,'未决或冲突'):analyze_facility(docs,selection(analyze_facility(docs)))

    def test_conflicting_group_limits_and_incomplete_table_block_ready(self):
        docs=documents();group=at(docs,'FOL-01','facility_limits')['row_results']
        group.append(row({'facility_name':'Revolving Loan','amount':'4000.00','currency':'USD'},8))
        at(docs,'FOL-01','borrower_allocations')['status']='needs_review'
        context=analyze_facility(docs)
        self.assertEqual(context['status'],'needs_review')
        codes={i['code'] for i in context['issues']}
        self.assertTrue({'FACILITY_LIMIT_CONFLICT','ALLOCATION_REGISTER_INCOMPLETE'}<=codes)

    def test_group_currency_and_allocation_bound_checked(self):
        docs=documents();group=at(docs,'FOL-01','facility_limits')['row_results'][0]['value']
        group['amount']='999'
        self.assertIn('ALLOCATION_EXCEEDS_GROUP',[i['code'] for i in analyze_facility(docs)['issues']])
        group['currency']='CNY'
        self.assertIn('GROUP_ALLOCATION_CURRENCY_MISMATCH',[i['code'] for i in analyze_facility(docs)['issues']])

    def test_permitted_currency_needs_separate_clause_evidence(self):
        docs=documents();at(docs,'FOL-01','allowed_currencies').update(value=None,status='conflict')
        self.assertIn('PERMITTED_CURRENCY_UNVERIFIED',[i['code'] for i in analyze_facility(docs)['issues']])

    def test_task_metadata_cannot_supply_borrower_or_override_drawdown(self):
        context=analyze_facility(documents(),task_request=dict(borrower='其他主体',drawdown_currency='CNY',drawdown_amount='999'))
        self.assertTrue({'TASK_BORROWER_MISMATCH','TASK_CURRENCY_MISMATCH','TASK_AMOUNT_MISMATCH'}<=set(i['code'] for i in context['issues']))

    def test_multiple_documents_are_not_silently_reduced_to_first(self):
        docs=documents();docs.append(deepcopy(docs[1]))
        self.assertIn('MULTIPLE_DRAWDOWNS',[i['code'] for i in analyze_facility(docs)['issues']])
        docs=documents();docs.append(deepcopy(docs[0]))
        self.assertIn('MULTIPLE_FACILITY_LETTERS',[i['code'] for i in analyze_facility(docs)['issues']])

    def test_verified_manual_rows_do_not_inherit_wrong_cell_coordinates(self):
        docs=as_verified(documents());audit=docs[0].fields['_parsing']['fields']['borrower_allocations']
        audit['status']='confirmed';audit['final_value'][0]['amount']='900.00'
        docs[0].fields['borrower_allocations']=deepcopy(audit['final_value'])
        row_result=analyze_facility(verified_dtos(docs))['allocations'][0]
        self.assertEqual(row_result['cells'],{})
        self.assertEqual(row_result['status'],'confirmed')

    def test_stored_association_actor_and_runner_revalidation(self):
        docs=as_verified(documents());context=analyze_facility(verified_dtos(docs))
        attach_facility_context(docs,selection(context),7)
        stored=docs[0].fields['_parsing']['facility_context']
        self.assertEqual(stored['confirmed_by'],7);self.assertTrue(stored['confirmed_at'])
        self.assertEqual(stored['status'],'ready')
        results=run_all(docs)
        amount=next(r for r in results if r.rule_id=='DRAWDOWN_VS_FACILITY_LETTER__AMOUNT')
        self.assertEqual(amount.status,Status.WARN)
        self.assertIn('非可用余额',str(amount.detail))
        self.assertEqual(amount.detail[1][3]['page'],8)
        self.assertNotIn('_facility_context',docs[0].fields)
        docs[1].fields['amount']='9999'
        self.assertEqual(run_all(docs)[0].rule_id,'PARSING_READY')

    def test_unresolved_context_stops_rules_and_invalidates_old_selection(self):
        docs=as_verified(documents());docs[1].fields['_parsing']['fields']['facility']['status']='missing'
        self.assertEqual(run_all(docs)[0].rule_id,'FACILITY_APPLICABILITY')
        docs=as_verified(documents());attach_facility_context(docs,selection(analyze_facility(verified_dtos(docs))),7)
        docs[0].fields['_parsing']['source_sha256']='f'*64
        self.assertEqual(run_all(docs)[0].rule_id,'FACILITY_APPLICABILITY')

    def test_amount_rule_never_turns_unknown_into_zero_or_subtracts_different_currencies(self):
        rule=R_DrawdownAmountWithinFacility()
        for dd,fol in [({'amount':None},{'facility_amount':'1','facility_currency':'USD'}),
                       ({'amount':'10','currency':'CNY'},{'facility_amount':'100','facility_currency':'USD'}),
                       ({'amount':'10','currency':'USD'},{'facility_amount':'100'})]:
            self.assertEqual(rule.evaluate(DocBundle({'DRAWDOWN_INSTRUCTION':[dd],'FACILITY_LETTER':[fol]})).status,Status.WARN)
        bundle=DocBundle({'DRAWDOWN_INSTRUCTION':[{'amount':'9007199254740993.02','currency':'USD'}],
            'FACILITY_LETTER':[{'facility_amount':'9007199254740993.01','facility_currency':'USD'}]})
        self.assertEqual(rule.evaluate(bundle).status,Status.FAIL)

    def test_empty_facility_and_conditional_currency_do_not_pass(self):
        bundle=DocBundle({'DRAWDOWN_INSTRUCTION':[{'tranche':'Any name','currency':'CNY'}],
            'FACILITY_LETTER':[{'facility':None,'utilization_currency':'any currency agreed by lender'}]})
        self.assertEqual(R_DrawdownTranche().evaluate(bundle).status,Status.WARN)
        self.assertEqual(R_DrawdownCurrencyInFacilityScope().evaluate(bundle).status,Status.WARN)


if __name__=='__main__':unittest.main()
