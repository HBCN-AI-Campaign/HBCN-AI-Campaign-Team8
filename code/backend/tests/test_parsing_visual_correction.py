import hashlib
from io import BytesIO
import json
import unittest
from unittest.mock import Mock

from PIL import Image
from app.parsing.config import ParserSettings
from app.parsing.contracts import Block,Page,ParseError
from app.parsing.pipeline import ParsingPipeline,validate_candidate,resolve
from app.parsing.providers import HSBCSemanticProvider
from app.parsing.registry import A,QUNIT,spec
from app.parsing.visual_correction import correction_crop,validate_transcription


class VisualCorrectionTests(unittest.TestCase):
    def setup_case(self):
        buf=BytesIO();Image.new('RGB',(1000,1000),'white').save(buf,format='PNG')
        p=Page(1,1000,1000,buf.getvalue(),[Block('p1b0','440,593.4b',[.1,.1,.3,.14],.99,'paddle_http')])
        c=validate_candidate(dict(key='amount',value='440593.46',raw_value='440,593.4b',block_ids=['p1b0'],visual_state='clear'),A,[p],'vision')
        return p,c

    def test_agreement_preserves_wrong_ocr_and_hashed_pixels(self):
        p,c=self.setup_case();crop,source=correction_crop(c,A,[p],16000000)
        result=validate_transcription(c,A,{'raw_text':'440,593.46','visual_state':'clear'},source)
        self.assertEqual(result['issues'],[])
        self.assertEqual(result['normalized_value'],'440593.46')
        self.assertEqual(result['evidence'][0]['text'],'440,593.4b')
        self.assertEqual(result['pixel_evidence']['image_sha256'],hashlib.sha256(crop.image).hexdigest())
        self.assertTrue(result['pixel_evidence']['same_model'])
        self.assertEqual(c['raw_value'],'440,593.4b')

    def test_disagreement_is_retained_as_conflict(self):
        p,c=self.setup_case();_,source=correction_crop(c,A,[p],16000000)
        result=validate_transcription(c,A,{'raw_text':'440,593.48','visual_state':'clear'},source)
        self.assertIn('VISUAL_READS_DISAGREE',result['issues'])
        self.assertEqual(resolve(A,[c,result])['status'],'conflict')

    def test_unclear_deleted_and_invalid_do_not_pass(self):
        p,c=self.setup_case();_,source=correction_crop(c,A,[p],16000000)
        for raw,state in [('440,593.46','deleted'),('','ambiguous'),('440,593.4b','clear')]:
            with self.subTest(state=state,raw=raw):
                self.assertTrue(validate_transcription(c,A,{'raw_text':raw,'visual_state':state},source)['issues'])

    def test_missing_multiple_anchors_and_prior_visual_deletion_are_not_corrected(self):
        p,c=self.setup_case()
        for state in ['deleted','ambiguous','not_checked']:
            c['visual_state']=state
            self.assertIsNone(correction_crop(c,A,[p],16000000))
        c['visual_state']='clear';c['block_ids']=[]
        self.assertIsNone(correction_crop(c,A,[p],16000000))
        p.blocks.append(Block('second','125.00',[.4,.1,.5,.2],1,'paddle_http'));c['block_ids']=['p1b0','second']
        self.assertIsNone(correction_crop(c,A,[p],16000000))

    def test_bound_and_optional_provider_failure_leave_original(self):
        p,c=self.setup_case();semantic=Mock();semantic.transcribe_region.side_effect=ParseError('SEMANTIC_REQUEST_FAILED')
        pipeline=ParsingPipeline(ParserSettings(visual_correction_fields=0),ocr=Mock(),semantic=semantic)
        self.assertEqual(pipeline._correct_from_pixels([p],[A],{'amount':[c]}),[])
        semantic.transcribe_region.assert_not_called()
        pipeline.cfg.visual_correction_fields=1
        attempts=pipeline._correct_from_pixels([p],[A],{'amount':[c]})
        self.assertEqual(attempts[0]['status'],'failed')
        self.assertNotIn('superseded',c)

    def test_provider_does_not_send_expected_value_or_ocr_text(self):
        p,c=self.setup_case();crop,_=correction_crop(c,A,[p],16000000)
        response=Mock();response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"raw_text":"440,593.46","visual_state":"clear"}'}}]}
        client=Mock();client.post.return_value=response
        provider=HSBCSemanticProvider(ParserSettings(vision_base_url='https://example.invalid/v1',vision_api_key='test',vision_model='test-model'),client)
        self.assertEqual(provider.transcribe_region(crop,A)['raw_text'],'440,593.46')
        payload=client.post.call_args.kwargs['json']
        instructions=json.dumps(payload['messages'],ensure_ascii=False)
        self.assertNotIn('440,593.4b',instructions)
        self.assertNotIn('440593.46',instructions)
        self.assertNotIn('block_ids',instructions)
        self.assertEqual(len(payload['messages'][1]['content']),2)

    def test_unit_still_has_no_nt_alias(self):
        with self.assertRaises(ValueError):
            from app.parsing.normalization import normalize_source
            normalize_source('NT',QUNIT)

    def test_glued_typed_field_requires_blind_pixels_not_a_label_exception(self):
        p,_ = self.setup_case()
        p.blocks[0].text = 'Rechnungsnummer: PI-2023-8843Währung: USD'
        invoice = spec('invoice_no', '发票号')
        original = validate_candidate(dict(value='PI-2023-8843',raw_value='Rechnungsnummer: PI-2023-8843',
            block_ids=['p1b0'],visual_state='clear'),invoice,[p],'vision')
        self.assertEqual(original['issues'],['IDENTIFIER_SOURCE_INCOMPLETE'])
        self.assertEqual(original['identifier_boundary']['following_value'],'USD')
        self.assertIsNone(resolve(invoice,[original])['value'])
        semantic=Mock();semantic.transcribe_region.return_value={'raw_text':'PI-2023-8843','visual_state':'clear'}
        pipeline=ParsingPipeline(ParserSettings(visual_correction_fields=1),ocr=Mock(),semantic=semantic)
        candidates={'invoice_no':[original]}
        attempts=pipeline._correct_from_pixels([p],[invoice],candidates)
        self.assertEqual(attempts[0]['status'],'accepted')
        active=[c for c in candidates['invoice_no'] if not c.get('superseded')]
        self.assertEqual(resolve(invoice,active)['value'],'PI-2023-8843')
        self.assertEqual(active[0]['evidence'][0]['text'],p.blocks[0].text)
        self.assertEqual(active[0]['verification'],'blind_region_pixels')
        semantic.transcribe_region.assert_called_once()

    def test_actual_partial_identifiers_and_unknown_labels_are_ineligible(self):
        p,_=self.setup_case();invoice=spec('invoice_no','发票号')
        for text in ('PI-2023-8843-CONTRACT','PI-2023-8843Unknown: USD','PI-2023-8843Currency: unknown'):
            p.blocks[0].text=text
            original=validate_candidate(dict(value='PI-2023-8843',raw_value='PI-2023-8843',
                block_ids=['p1b0'],visual_state='clear',identifier_boundary={'kind':'possible_following_field_merge'}),invoice,[p],'vision')
            self.assertIn('IDENTIFIER_SOURCE_INCOMPLETE',original['issues'])
            self.assertNotIn('identifier_boundary',original)
            self.assertIsNone(correction_crop(original,invoice,[p],16000000))
            rejected=validate_transcription(original,invoice,{'raw_text':'PI-2023-8843','visual_state':'clear'},dict(page=1,bbox=[0,0,.5,.5]))
            self.assertIn('IDENTIFIER_CORRECTION_NOT_ELIGIBLE',rejected['issues'])

    def test_pixel_identifier_comparison_cannot_drop_account_zeros(self):
        p,_=self.setup_case();p.blocks[0].text='00123Currency: USD'
        account=spec('payee_account','收款账号','account')
        original=validate_candidate(dict(value='00123',raw_value='00123',block_ids=['p1b0'],visual_state='clear'),account,[p],'vision')
        _,source=correction_crop(original,account,[p],16000000)
        corrected=validate_transcription(original,account,{'raw_text':'123','visual_state':'clear'},source)
        self.assertIn('VISUAL_READS_DISAGREE',corrected['issues'])
        self.assertEqual(resolve(account,[original,corrected])['status'],'conflict')

    def test_pixel_merge_ambiguous_and_failed_reads_do_not_clear_the_guard(self):
        p,_=self.setup_case();p.blocks[0].text='PI-123Currency: USD'
        invoice=spec('invoice_no','发票号')
        original=validate_candidate(dict(value='PI-123',raw_value='PI-123',block_ids=['p1b0'],visual_state='clear'),invoice,[p],'vision')
        _,source=correction_crop(original,invoice,[p],16000000)
        bad=validate_transcription(original,invoice,{'raw_text':'PI-123','visual_state':'ambiguous'},source)
        self.assertIn('REGION_NOT_CLEAR',bad['issues'])
        semantic=Mock();semantic.transcribe_region.side_effect=ParseError('SEMANTIC_REQUEST_FAILED')
        pipeline=ParsingPipeline(ParserSettings(visual_correction_fields=1),ocr=Mock(),semantic=semantic)
        candidates={'invoice_no':[original]}
        self.assertEqual(pipeline._correct_from_pixels([p],[invoice],candidates)[0]['status'],'failed')
        self.assertNotIn('superseded',original)
        self.assertIsNone(resolve(invoice,candidates['invoice_no'])['value'])


if __name__=='__main__':unittest.main()
