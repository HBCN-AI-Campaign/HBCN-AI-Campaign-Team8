import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.parsing.config import ParserSettings
from app.parsing.contracts import Block, Page, ParseError
from app.parsing.normalization import normalize
from app.parsing.pipeline import ParsingPipeline, field_quality, page_quality, resolve, validate_candidate
from app.parsing.providers import HSBCSemanticProvider, PaddleHttpProvider, safe_endpoint
from app.parsing.registry import A, FIELDS, guess_type, spec
from app.rule_engine import run_all


def page(number=1,text="123,456.78"):
    return Page(number,1000,1000,b"png",[Block(f"p{number}b0",text,[.1,.2,.5,.25],.99,"paddle_http")])


def candidate(value="123456.78",raw="123,456.78",state="clear",ids=None):
    return dict(key="amount",value=value,raw_value=raw,visual_state=state,block_ids=ids or ["p1b0"])


class NormalizationTests(unittest.TestCase):
    def test_exact_decimal(self):
        self.assertEqual(normalize("9,007,199,254,740,993.01","money"),"9007199254740993.01")
    def test_amount_not_unit_price_or_multiple_numbers(self):
        for value in ["3.14 CNY/MT","123 456","1.234,56","1e7",True,"nan"]:
            with self.subTest(value=value),self.assertRaises(ValueError): normalize(value,"money")
    def test_chinese_date_and_account(self):
        self.assertEqual(normalize("2026 年 10 月 12 日","date"),"2026-10-12")
        self.assertEqual(normalize("012-345678-901","account"),"012345678901")
    def test_ambiguous_and_invalid_date(self):
        for value in ["10/11/2026","2026-02-30"]:
            with self.assertRaises(ValueError): normalize(value,"date")
    def test_currency_semantics(self):
        self.assertEqual(normalize("人民币","currency_code"),"CNY")
        with self.assertRaises(ValueError): normalize("$","currency_code")

    def test_unambiguous_punctuation_and_bilingual_currency(self):
        self.assertEqual(normalize('(CNY)','currency_code'),'CNY')
        self.assertEqual(normalize('CNY 人民币','currency_code'),'CNY')
        self.assertEqual(normalize('OCT. 29,2025','date'),'2025-10-29')
        with self.assertRaises(ValueError):normalize('USD 人民币','currency_code')

    def test_quantity_unit_is_not_silently_discarded(self):
        with self.assertRaises(ValueError):normalize('89860千克','decimal')


class EvidenceTests(unittest.TestCase):
    def test_field_quality_reports_stage_signals_without_candidate_values(self):
        diagnostic=field_quality({
            'key':'amount','data_type':'money','status':'needs_review','required':True,
            'value':None,'source':None,'issues':['NO_VALUE'],
            'candidates':[{'method':'ocr_semantic','raw_value':'sensitive amount text',
                'value':'987654321.00','issues':['RAW_VALUE_NOT_GROUNDED','LOW_OCR_SCORE']}],
        },[{'keys':['amount'],'status':'failed','code':'OCR_REQUEST_FAILED','bbox':[.1,.2,.3,.4]}])
        self.assertEqual(diagnostic['key'],'amount')
        self.assertEqual(diagnostic['candidate_method_counts'],{'ocr_semantic':1})
        self.assertEqual(diagnostic['candidate_issue_counts'],{'LOW_OCR_SCORE':1,'RAW_VALUE_NOT_GROUNDED':1})
        self.assertEqual(diagnostic['regional_attempt_count'],1)
        self.assertEqual(diagnostic['regional_attempt_status_counts'],{'failed':1})
        self.assertEqual(diagnostic['regional_attempt_failure_counts'],{'OCR_REQUEST_FAILED':1})
        self.assertFalse(diagnostic['value_present'])
        self.assertFalse(diagnostic['source_box_valid'])
        serialized=json.dumps(diagnostic,ensure_ascii=False)
        self.assertNotIn('sensitive amount text',serialized)
        self.assertNotIn('987654321.00',serialized)
        self.assertNotIn('bbox',serialized)

    def test_page_quality_diagnostics_omit_business_text(self):
        p=Page(2,1000,500,b"png",[Block("p2b0","account-number-123",[.1,.2,.3,.4],.82,"paddle_http")])
        report=page_quality(p)
        self.assertEqual(report["ocr_status"],"completed")
        self.assertEqual(report["score_bins"],{'lt_085':1,'085_to_095':0,'ge_095':0})
        self.assertEqual((report["block_count"],report["recognized_character_count"],report["valid_box_count"]),(1,18,1))
        self.assertNotIn("text",report)
        self.assertNotIn("account-number-123",json.dumps(report))

    def test_value_source_and_normalized_box(self):
        c=validate_candidate(candidate(),A,[page()],"vision")
        self.assertEqual(c["issues"],[])
        self.assertEqual(c["source"],dict(page=1,bbox=[.1,.2,.5,.25]))
        self.assertEqual(resolve(A,[c])["value"],"123456.78")
    def test_invalid_native_text_box_cannot_be_a_field_location(self):
        p=page();p.blocks[0].bbox=[.9,.2,1.1,.25]
        c=validate_candidate(candidate(),A,[p],"vision")
        self.assertIn("INVALID_EVIDENCE_COORDINATES",c["issues"])
        self.assertIsNone(c["source"])
        self.assertIsNone(resolve(A,[c])["value"])
    def test_scalar_evidence_across_pages_is_not_collapsed_to_first_page_box(self):
        first=page(1,"123,456")
        second=page(2,".78")
        second.blocks[0].id="p2b0"
        c=validate_candidate(candidate(ids=["p1b0","p2b0"]),A,[first,second],"vision")
        self.assertIn("EVIDENCE_SPANS_MULTIPLE_PAGES",c["issues"])
        self.assertIsNone(c["source"])
        self.assertIsNone(resolve(A,[c])["value"])
    def test_model_cannot_override_amount(self):
        c=validate_candidate(candidate("999999"),A,[page()],"vision")
        self.assertIn("VALUE_SOURCE_MISMATCH",c["issues"])
        self.assertIsNone(resolve(A,[c])["value"])
    def test_hallucinated_or_cross_page_id_rejected(self):
        c=validate_candidate(candidate(ids=["p2b0"]),A,[page()],"vision")
        self.assertIn("EVIDENCE_MISSING_OR_UNKNOWN",c["issues"])
    def test_no_zero_for_missing(self):
        self.assertIsNone(resolve(A,[])["value"])
        self.assertEqual(resolve(A,[])["status"],"missing")
    def test_selection_symbols_do_not_mean_true_or_false(self):
        selection=spec("disbursement_method","放款方式",visual=True)
        for state in ["unselected","deleted","ambiguous","not_checked"]:
            c=validate_candidate(candidate("银行受托支付","银行受托支付",state),selection,[page(text="银行受托支付")],"vision")
            self.assertIsNone(resolve(selection,[c])["value"])
    def test_text_only_cannot_confirm_checkbox(self):
        s=spec("purpose","用途",visual=True)
        c=validate_candidate(candidate("采购","采购"),s,[page(text="采购")],"ocr_semantic")
        self.assertIn("VISUAL_REVIEW_REQUIRED",c["issues"])
    def test_conflicting_values_not_last_writer_wins(self):
        c1=validate_candidate(candidate(),A,[page()],"vision")
        c2=validate_candidate(candidate("987.65","987.65",ids=["p2b0"]),A,[page(2,"987.65")],"vision")
        result=resolve(A,[c1,c2])
        self.assertEqual(result["status"],"conflict")
        self.assertIsNone(result["value"])
    def test_low_ocr_score_requires_review(self):
        p=page();p.blocks[0].score=.5
        self.assertIn("LOW_OCR_SCORE",validate_candidate(candidate(),A,[p],"vision")["issues"])
    def test_unknown_filename_is_not_facility_letter(self): self.assertIsNone(guess_type("random.pdf"))

    def test_table_cell_cannot_hide_hallucination_in_valid_row_evidence(self):
        table=spec('line_items','货物明细','rows',visual=True)
        row={'description':'钢卷','amount':'999.00','block_ids':['p1b0']}
        c=validate_candidate(candidate([row],'钢卷'),table,[page(text='钢卷 123.45')],'vision')
        self.assertIn('ROW_CELL_NOT_GROUNDED',c['issues'])
        self.assertIsNone(resolve(table,[c])['value'])

    def test_every_list_member_needs_evidence(self):
        c=validate_candidate(candidate(['USD','CNY'],'USD'),spec('allowed_currencies','币种','list'),[page(text='USD')],'vision')
        self.assertIn('LIST_ITEM_NOT_GROUNDED',c['issues'])

    def test_invalid_visual_state_does_not_crash(self):
        c=validate_candidate(candidate(state={}),A,[page()],'vision')
        self.assertIn('VISUAL_AMBIGUOUS',c['issues'])

    def test_explicit_label_does_not_make_correct_amount_unusable(self):
        c=validate_candidate(candidate('12000000.00','金额：12,000,000.00'),A,[page(text='金额：12,000,000.00')],'vision')
        self.assertEqual(c['issues'],[])

    def test_prose_date_is_exact_and_two_dates_remain_ambiguous(self):
        s=spec('facility_letter_date','授信函日期','date')
        c=validate_candidate(candidate('2026-10-12','于2026年10月12日订立的银行授信函'),s,[page(text='于2026年10月12日订立的银行授信函')],'vision')
        self.assertEqual(c['issues'],[])
        c=validate_candidate(candidate('2026-10-12','2026年10月12日或2026年10月13日'),s,[page(text='2026年10月12日或2026年10月13日')],'vision')
        self.assertIn('VALUE_SOURCE_MISMATCH',c['issues'])


class ProviderTests(unittest.TestCase):
    def test_missing_ocr_endpoint_fails_closed(self):
        with self.assertRaisesRegex(ParseError, "OCR_NOT_CONFIGURED"):
            PaddleHttpProvider(ParserSettings(ocr_base_url="")).analyze(page())

    def test_existing_server_multipart_contract(self):
        def handle(request):
            self.assertEqual(request.url.path,"/analyze")
            self.assertIn(b'name="id"',request.content)
            self.assertIn(b'name="file"',request.content)
            return httpx.Response(200,json={"blocks":[dict(text="123",score=.98,box=[100,200,500,250])]})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            provider=PaddleHttpProvider(ParserSettings(ocr_base_url="http://127.0.0.1:7888"),client)
            self.assertEqual(provider.analyze(page())[0].bbox,[.1,.2,.5,.25])
    def test_empty_ocr_result_is_explicit_no_text(self):
        response=httpx.Response(200,json={"blocks":[dict(text="  ",score=.99,box=[100,200,500,250])]})
        with httpx.Client(transport=httpx.MockTransport(lambda r:response)) as client:
            provider=PaddleHttpProvider(ParserSettings(ocr_base_url="http://127.0.0.1"),client)
            with self.assertRaisesRegex(ParseError,"OCR_NO_TEXT"):
                provider.analyze(page())
    def test_second_page_ocr_box_maps_to_page_scoped_field_evidence(self):
        p=Page(2,1000,500,b"png")
        response=httpx.Response(200,json={"blocks":[dict(text="123,456.78",score=.99,box=[250,100,750,150])]})
        with httpx.Client(transport=httpx.MockTransport(lambda r:response)) as client:
            provider=PaddleHttpProvider(ParserSettings(ocr_base_url="http://127.0.0.1"),client)
            block=provider.analyze(p)[0]
        self.assertEqual(block.id,"p2b0")
        self.assertEqual(block.bbox,[.25,.2,.75,.3])
        candidate=validate_candidate(dict(key="amount",value="123456.78",raw_value="123,456.78",
            visual_state="clear",block_ids=[block.id]),A,[Page(2,p.width,p.height,p.image,[block])],"vision")
        self.assertEqual(candidate["issues"],[])
        self.assertEqual(candidate["source"],dict(page=2,bbox=[.25,.2,.75,.3]))
    def test_invalid_coordinate_and_nan(self):
        for box in [[0,0,1001,50],[20,30,10,40],[float('nan'),0,10,20]]:
            response=json.dumps(dict(blocks=[dict(text="123",score=.9,box=box)]))
            with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=response))) as client:
                with self.assertRaises(ParseError): PaddleHttpProvider(ParserSettings(ocr_base_url="http://127.0.0.1"),client).analyze(page())
    def test_http200_error_and_timeout(self):
        for payload in [{"error":"secret provider details"},{"text":"no blocks"}]:
            with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
                with self.assertRaisesRegex(ParseError,"OCR_INVALID_RESPONSE"):
                    PaddleHttpProvider(ParserSettings(ocr_base_url="http://127.0.0.1"),client).analyze(page())
    def test_public_http_refused(self):
        with self.assertRaises(ParseError): safe_endpoint("http://101.201.232.81/ocr")
        self.assertEqual(safe_endpoint("https://example.com/v1/"),"https://example.com/v1")
    def test_truncated_semantic_json_rejected(self):
        cfg=ParserSettings(vision_base_url="https://model.example/v1",vision_api_key="test",vision_model="test")
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"choices":[{"finish_reason":"length","message":{"content":"{\"fields\":[]}"}}]}))) as client:
            with self.assertRaisesRegex(ParseError,"TRUNCATED"):
                HSBCSemanticProvider(cfg,client).extract([page()],"PAYMENT_INSTRUCTION",[A],visual=True)


class PipelineTests(unittest.TestCase):
    def test_unknown_model_field_key_is_reported_without_logging_content(self):
        class OCR:
            def analyze(self,p): return p.blocks
        class Model:
            def extract(self,pages,tcode,specs,*,visual):
                return [dict(key="unregistered-model-output",value="secret text",raw_value="secret text",
                    block_ids=["p1b0"],visual_state="clear")]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"payment.pdf";path.write_bytes(b"test")
            with patch("app.parsing.pipeline.prepare",return_value=[page()]):
                doc=ParsingPipeline(ParserSettings(),ocr=OCR(),semantic=Model()).parse_document(
                    path,"payment.pdf",type_code="PAYMENT_INSTRUCTION")
        self.assertEqual(doc["status"],"needs_review")
        self.assertIn("SEMANTIC_UNKNOWN_FIELD_KEY",[issue["code"] for issue in doc["issues"]])
        amount=next(item for item in doc["field_diagnostics"] if item["key"]=="amount")
        self.assertEqual(amount["data_type"],"money")
        self.assertEqual(amount["candidate_count"],0)
        self.assertEqual(amount["regional_attempt_count"],0)
        self.assertFalse(amount["value_present"])
        self.assertNotIn("secret text",json.dumps(doc,ensure_ascii=False))

    def test_malformed_model_field_is_reported(self):
        class OCR:
            def analyze(self,p): return p.blocks
        class Model:
            def extract(self,pages,tcode,specs,*,visual): return [None]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"payment.pdf";path.write_bytes(b"test")
            with patch("app.parsing.pipeline.prepare",return_value=[page()]):
                doc=ParsingPipeline(ParserSettings(),ocr=OCR(),semantic=Model()).parse_document(
                    path,"payment.pdf",type_code="PAYMENT_INSTRUCTION")
        self.assertIn("SEMANTIC_INVALID_FIELD",[issue["code"] for issue in doc["issues"]])

    def test_ocr_outage_keeps_candidate_unresolved_and_marks_document_incomplete(self):
        class OCR:
            def analyze(self,p): raise ParseError("OCR_REQUEST_FAILED")
        class Model:
            def extract(self,pages,tcode,specs,*,visual):
                return [candidate()] if not visual else [candidate()]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"payment.pdf";path.write_bytes(b"test")
            with patch("app.parsing.pipeline.prepare",return_value=[page()]):
                doc=ParsingPipeline(ParserSettings(),ocr=OCR(),semantic=Model()).parse_document(path,"payment.pdf")
        amount=next(f for f in doc["fields"] if f["key"]=="amount")
        self.assertEqual(doc["status"],"needs_review")
        self.assertEqual(doc["issues"],[{"page":1,"code":"OCR_REQUEST_FAILED"}])
        self.assertIsNone(amount["value"])
        self.assertIn("DOCUMENT_INCOMPLETE",amount["issues"])

    def test_text_candidate_without_pixel_check_never_auto_accepted(self):
        class OCR:
            def analyze(self,p): return p.blocks
        class Model:
            def extract(self,pages,tcode,specs,*,visual):
                if visual: raise ParseError("VISION_DOWN")
                return [candidate()]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"payment.pdf";path.write_bytes(b"test")
            with patch("app.parsing.pipeline.prepare",return_value=[page()]):
                doc=ParsingPipeline(ParserSettings(),ocr=OCR(),semantic=Model()).parse_document(path,"payment.pdf")
            amount=next(f for f in doc["fields"] if f["key"]=="amount")
            self.assertIsNone(amount["value"])
            self.assertEqual(doc["status"],"needs_review")
    def test_missing_fields_block_rules_instead_of_becoming_zero(self):
        d=SimpleNamespace(doc_code="DD1",fields={"amount":None,"_parsing":{"unresolved_required":["amount"]}},type_code="DRAWDOWN_INSTRUCTION")
        result=run_all([d])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].rule_id,"PARSING_READY")
        self.assertEqual(result[0].status.value,"warn")


if __name__=="__main__": unittest.main()
