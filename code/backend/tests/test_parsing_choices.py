import unittest
from app.parsing.contracts import Block,Page
from app.parsing.pipeline import validate_candidate,resolve
from app.parsing.registry import FIELDS


CHOICE=next(s for s in FIELDS['DRAWDOWN_INSTRUCTION'] if s['key']=='disbursement_method')


def c(raw,value,state='selected',method='vision',evidence=None):
    p=Page(1,1000,1000,b'', [Block('p1b0',evidence or raw,[.1,.2,.8,.3],.99,'paddle_http')])
    return validate_candidate(dict(key=CHOICE['key'],value=value,raw_value=raw,block_ids=['p1b0'],visual_state=state),CHOICE,[p],method)


class ChoiceTests(unittest.TestCase):
    def test_mark_not_in_ocr_is_verified_from_pixels_not_invented_label(self):
        result=c('☑ 银行受托支付','银行受托支付',evidence='银行受托支付')
        self.assertEqual(result['issues'],[])
        self.assertEqual(resolve(CHOICE,[result])['value'],'银行受托支付')

    def test_unknown_label_cannot_be_grounded_by_mark(self):
        result=c('☑ 银行受托支付','银行受托支付',evidence='借款人自主支付')
        self.assertIn('RAW_VALUE_NOT_GROUNDED',result['issues'])

    def test_text_symbols_cannot_confirm_selection(self):
        result=c('☑ 银行受托支付','银行受托支付',method='ocr_semantic')
        self.assertIn('VISUAL_REVIEW_REQUIRED',result['issues'])

    def test_clear_is_not_selected(self):
        self.assertIsNone(resolve(CHOICE,[c('银行受托支付','银行受托支付',state='clear')])['value'])

    def test_effectively_deleted_choice_does_not_conflict_with_selected_choice(self):
        deleted=c('银行受托支付','银行受托支付',state='deleted')
        selected=c('借款人自主支付','借款人自主支付')
        result=resolve(CHOICE,[deleted,selected])
        self.assertEqual(result['value'],'借款人自主支付')
        self.assertEqual(len(result['candidates']),2)

    def test_two_selected_choices_remain_conflict(self):
        self.assertEqual(resolve(CHOICE,[c('银行受托支付','银行受托支付'),c('借款人自主支付','借款人自主支付')])['status'],'conflict')

    def test_english_label_maps_to_business_choice(self):
        self.assertEqual(resolve(CHOICE,[c('[X] Bank entrusted payment','Bank entrusted payment')])['value'],'银行受托支付')

    def test_cross_is_not_automatically_selected(self):
        self.assertIsNone(resolve(CHOICE,[c('[X] Bank entrusted payment','Bank entrusted payment',state='ambiguous')])['value'])

    def test_unregistered_source_label_stays_invalid_without_crashing(self):
        result=c('Other method','Other method')
        self.assertIn('INVALID_FIELD_TYPE',result['issues'])
        self.assertIsNone(resolve(CHOICE,[result])['value'])


if __name__=='__main__':unittest.main()
