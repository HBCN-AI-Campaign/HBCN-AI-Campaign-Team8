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
from app.parsing.pipeline import ParsingPipeline, resolve, validate_candidate
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
    def test_value_source_and_normalized_box(self):
        c=validate_candidate(candidate(),A,[page()],"vision")
        self.assertEqual(c["issues"],[])
        self.assertEqual(c["source"],dict(page=1,bbox=[.1,.2,.5,.25]))
        self.assertEqual(resolve(A,[c])["value"],"123456.78")
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
