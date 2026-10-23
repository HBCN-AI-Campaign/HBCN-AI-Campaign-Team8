from io import BytesIO
import unittest
from unittest.mock import Mock
from PIL import Image
from app.parsing.config import ParserSettings
from app.parsing.contracts import Block,Page,ParseError
from app.parsing.pipeline import ParsingPipeline,validate_candidate,resolve
from app.parsing.regional import crop_page,remap_blocks
from app.parsing.registry import QUNIT,FIELDS


def page():
    buf=BytesIO();Image.new('RGB',(1000,1000),'white').save(buf,format='PNG')
    return Page(1,1000,1000,buf.getvalue(),[Block('p1b0','NT',[.1,.1,.2,.2],.99,'paddle_http')])


class RegionalTests(unittest.TestCase):
    def setup_pipeline(self,new_value='MT',cite='p1r1b0'):
        p=page()
        old=validate_candidate(dict(key='quantity_unit',value='MT',raw_value='NT',block_ids=['p1b0'],visual_state='clear'),QUNIT,[p],'vision')
        ocr=Mock();ocr.analyze.return_value=[Block('p1b0',new_value,[.1,.1,.9,.9],.99,'paddle_http')]
        semantic=Mock();semantic.extract.return_value=[dict(key='quantity_unit',value=new_value,raw_value=new_value,block_ids=[cite],visual_state='clear')]
        pipeline=ParsingPipeline(ParserSettings(),ocr=ocr,semantic=semantic)
        return pipeline,p,{'quantity_unit':[old]}

    def test_regional_coordinates_return_to_original_page(self):
        p=page();crop,box=crop_page(p,[.1,.1,.2,.2],16000000)
        self.assertEqual((crop.width,crop.height),(280,280))
        block=remap_blocks([Block('local','MT',[.5,.5,.75,.75],1,'ocr')],p,box,1)[0]
        self.assertEqual(block.bbox[:2],[.15,.15])
        self.assertTrue(all(.08<=v<=.22 for v in block.bbox))

    def test_valid_retry_keeps_old_evidence_and_replaces_only_same_hypothesis(self):
        pipeline,p,candidates=self.setup_pipeline()
        attempts=pipeline._retry_regions([p],'WAYBILL',[QUNIT],candidates)
        self.assertEqual(attempts[0]['status'],'completed')
        self.assertEqual(p.blocks[0].text,'NT')
        self.assertTrue(candidates['quantity_unit'][0]['superseded'])
        self.assertEqual(resolve(QUNIT,[c for c in candidates['quantity_unit'] if not c.get('superseded')])['value'],'MT')

    def test_different_hypothesis_remains_conflict(self):
        pipeline,p,candidates=self.setup_pipeline(new_value='kg')
        pipeline._retry_regions([p],'WAYBILL',[QUNIT],candidates)
        self.assertEqual(resolve(QUNIT,candidates['quantity_unit'])['status'],'conflict')

    def test_retry_cannot_claim_verification_without_using_new_ocr(self):
        pipeline,p,candidates=self.setup_pipeline(cite='p1b0')
        pipeline._retry_regions([p],'WAYBILL',[QUNIT],candidates)
        self.assertIn('REGIONAL_EVIDENCE_NOT_USED',candidates['quantity_unit'][-1]['issues'])
        self.assertIsNone(resolve(QUNIT,candidates['quantity_unit'])['value'])

    def test_optional_retry_failure_is_reported_without_losing_old_evidence(self):
        pipeline,p,candidates=self.setup_pipeline();pipeline.ocr.analyze.side_effect=ParseError('OCR_REQUEST_FAILED')
        attempts=pipeline._retry_regions([p],'WAYBILL',[QUNIT],candidates)
        self.assertEqual(attempts[0]['code'],'OCR_REQUEST_FAILED')
        self.assertEqual(len(candidates['quantity_unit']),1)

    def test_budget_zero_makes_no_extra_provider_calls(self):
        pipeline,p,candidates=self.setup_pipeline();pipeline.cfg.regional_retry_pages=0
        self.assertEqual(pipeline._retry_regions([p],'WAYBILL',[QUNIT],candidates),[])
        pipeline.ocr.analyze.assert_not_called()

    def choice_pipeline(self, state='selected', replacement='3个月', cite='p1r1b0', score=.99):
        spec=next(s for s in FIELDS['DRAWDOWN_INSTRUCTION'] if s['key']=='interest_period')
        p=page()
        p.blocks=[Block('p1b0','☑ 3个月',[.2,.4,.35,.45],.81,'paddle_http'),
                  Block('p1b1','□ 1个月',[.2,.3,.35,.35],.99,'paddle_http'),
                  Block('p1b2','□ 6个月',[.2,.5,.35,.55],.99,'paddle_http')]
        old=validate_candidate(dict(key=spec['key'],value='3个月',raw_value='☑ 3个月',
            block_ids=['p1b0'],visual_state=state),spec,[p],'vision')
        ocr=Mock();ocr.analyze.return_value=[Block('local',replacement,[.2,.4,.35,.45],score,'paddle_http')]
        semantic=Mock();semantic.extract.return_value=[dict(key=spec['key'],value=replacement,
            raw_value=replacement,block_ids=[cite],visual_state='selected')]
        return ParsingPipeline(ParserSettings(),ocr=ocr,semantic=semantic),p,spec,{spec['key']:[old]}

    def test_low_score_selected_choice_retries_entire_page_with_same_budget(self):
        pipeline,p,spec,candidates=self.choice_pipeline()
        attempts=pipeline._retry_regions([p],'DRAWDOWN_INSTRUCTION',[spec],candidates)
        self.assertEqual(len(attempts),1)
        self.assertEqual(attempts[0]['bbox'],[0,0,1,1])
        self.assertEqual(attempts[0]['context'],'full_page_choices')
        self.assertEqual(pipeline.ocr.analyze.call_args.args[0].width,2000)
        self.assertEqual(pipeline.semantic.extract.call_args.args[0][0].image,p.image)
        self.assertTrue(candidates[spec['key']][0]['superseded'])
        self.assertEqual(resolve(spec,[c for c in candidates[spec['key']] if not c.get('superseded')])['value'],'3个月')

    def test_choice_retry_does_not_resolve_ambiguous_mark_or_skip_new_evidence(self):
        for state in ('ambiguous','deleted','unselected','clear'):
            with self.subTest(state=state):
                pipeline,p,spec,candidates=self.choice_pipeline(state=state)
                self.assertEqual(pipeline._retry_regions([p],'DRAWDOWN_INSTRUCTION',[spec],candidates),[])
                pipeline.ocr.analyze.assert_not_called()
        pipeline,p,spec,candidates=self.choice_pipeline(cite='p1b0')
        pipeline._retry_regions([p],'DRAWDOWN_INSTRUCTION',[spec],candidates)
        self.assertIn('REGIONAL_EVIDENCE_NOT_USED',candidates[spec['key']][-1]['issues'])
        self.assertIsNone(resolve(spec,candidates[spec['key']])['value'])

    def test_choice_retry_keeps_disagreement_and_low_confidence_unresolved(self):
        for replacement,score,expected in [('6个月',.99,'conflict'),('3个月',.82,'needs_review')]:
            with self.subTest(replacement=replacement,score=score):
                pipeline,p,spec,candidates=self.choice_pipeline(replacement=replacement,score=score)
                pipeline._retry_regions([p],'DRAWDOWN_INSTRUCTION',[spec],candidates)
                self.assertEqual(resolve(spec,candidates[spec['key']])['status'],expected)
        pipeline,p,spec,candidates=self.choice_pipeline()
        pipeline.cfg.regional_retry_pages=0
        self.assertEqual(pipeline._retry_regions([p],'DRAWDOWN_INSTRUCTION',[spec],candidates),[])
        pipeline.ocr.analyze.assert_not_called()


if __name__=='__main__':unittest.main()
