"""Identifiers retain leading zeros through evidence and candidate reconciliation."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.parsing.config import ParserSettings
from app.parsing.contracts import Block
from app.parsing.pipeline import ParsingPipeline, resolve, validate_candidate
from app.parsing.registry import A, spec
from tests.test_parsing import candidate, page


class IdentifierTests(unittest.TestCase):
    def test_account_source_cannot_lose_a_leading_zero(self):
        account = spec('payee_account', '收款账号', 'account')
        result = validate_candidate(candidate('123', '00123'), account, [page(text='00123')], 'vision')
        self.assertIn('VALUE_SOURCE_MISMATCH', result['issues'])
        self.assertIsNone(resolve(account, [result])['value'])

    def test_different_grounded_accounts_remain_conflicting(self):
        account = spec('payee_account', '收款账号', 'account')
        candidates = [validate_candidate(candidate(v, v), account, [page(text=v)], 'vision')
                      for v in ('00123', '123')]
        result = resolve(account, candidates)
        self.assertEqual(result['status'], 'conflict')
        self.assertIsNone(result['value'])

    def test_numeric_document_identifiers_are_text(self):
        identifier = spec('contract_no', '合同号')
        candidates = [validate_candidate(candidate(v, v), identifier, [page(text=v)], 'vision')
                      for v in ('00123', '123')]
        self.assertEqual(resolve(identifier, candidates)['status'], 'conflict')

    def test_document_pipeline_does_not_supersede_another_account(self):
        account = spec('payee_account', '收款账号', 'account')
        original = page(text='00123 123')
        original.needs_ocr = False
        provider = Mock()
        provider.extract.side_effect = [[dict(candidate('00123', '00123'), key='payee_account')],
                                        [dict(candidate('123', '123'), key='payee_account')]]
        pipeline = ParsingPipeline(ParserSettings(regional_retry_pages=0, visual_correction_fields=0),
                                   ocr=Mock(), semantic=provider)
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'payment.pdf'
            path.write_bytes(b'isolated identifier test')
            with patch('app.parsing.pipeline.prepare', return_value=[original]), \
                 patch.dict('app.parsing.pipeline.FIELDS', {'PAYMENT_INSTRUCTION': [account]}):
                result = pipeline.parse_document(path, path.name)
        field = result['fields'][0]
        self.assertEqual(field['status'], 'conflict')
        self.assertIsNone(field['value'])
        self.assertFalse(any(c.get('superseded') for c in field['candidates']))

    def test_registered_account_formatting_and_numeric_amounts_still_match(self):
        account = spec('payee_account', '收款账号', 'account')
        result = validate_candidate(candidate('00123', '001-23'), account, [page(text='001-23')], 'vision')
        self.assertEqual(resolve(account, [result])['value'], '00123')
        amounts = [validate_candidate(candidate(v, v), A, [page(text=v)], 'vision')
                   for v in ('00123', '123.00')]
        self.assertEqual(resolve(A, amounts)['status'], 'accepted')

    def test_both_value_and_quote_cannot_truncate_an_account(self):
        account = spec('payee_account', '收款账号', 'account')
        for text, raw in [('00123', '123'), ('00123', '0012'), ('00123-456', '00123'),
                          ('001 23', '001'), ('123.00', '123')]:
            with self.subTest(text=text, raw=raw):
                c = validate_candidate(candidate(raw, raw), account, [page(text=text)], 'vision')
                self.assertIn('IDENTIFIER_SOURCE_INCOMPLETE', c['issues'])
                self.assertIsNone(resolve(account, [c])['value'])

    def test_registered_document_ids_require_the_whole_connected_token(self):
        for key in ('contract_no', 'invoice_no', 'order_no', 'bill_of_lading_no', 'proforma_invoice_no'):
            identifier = spec(key, '编号')
            for text, raw in [('PI-2023-8843-CONTRACT', 'PI-2023-8843'),
                              ('PI-2023-8843 / A', 'PI-2023-8843'),
                              ('PRE_PI-2023-8843', 'PI-2023-8843'),
                              ('PI.123', 'PI'), ('AB123CD', '123')]:
                with self.subTest(key=key, text=text, raw=raw):
                    c = validate_candidate(candidate(raw, raw), identifier, [page(text=text)], 'vision')
                    self.assertIn('IDENTIFIER_SOURCE_INCOMPLETE', c['issues'])

    def test_identifier_cannot_be_composed_from_different_blocks_or_pages(self):
        account = spec('payee_account', '收款账号', 'account')
        p1 = page(text='001')
        p1.blocks.append(Block('p1b1', '23', [.6, .4, .7, .45], .99, 'paddle_http'))
        p2 = page(2, text='23')
        for pages, ids in [([p1], ['p1b0', 'p1b1']), ([p1, p2], ['p1b0', 'p2b0'])]:
            with self.subTest(ids=ids):
                c = validate_candidate(candidate('00123', '00123', ids=ids), account, pages, 'vision')
                self.assertIn('IDENTIFIER_SOURCE_INCOMPLETE', c['issues'])

    def test_complete_identifiers_allow_actual_whitespace_labels_and_punctuation(self):
        contract = spec('contract_no', '合同号')
        for text, raw, value in [
            ('Contract No.: PI-123 Date: 2026-10-23', 'Contract No.: PI-123', 'PI-123'),
            ('PI-123. Date: 2026-10-23', 'PI-123', 'PI-123'),
            ('(PI-123)', 'PI-123', 'PI-123'),
            ('ＰＩ－１２３', 'PI-123', 'PI-123'),
            ('PI - 123', 'PI-123', 'PI-123'),
        ]:
            with self.subTest(text=text):
                c = validate_candidate(candidate(value, raw), contract, [page(text=text)], 'vision')
                self.assertEqual(c['issues'], [])
                self.assertEqual(resolve(contract, [c])['value'], value)
        account = spec('payee_account', '收款账号', 'account')
        c = validate_candidate(candidate('00123', 'Account No.: 001 23'), account,
                               [page(text='Account No.: 001 23. Bank: ABC')], 'vision')
        self.assertEqual(c['issues'], [])
        self.assertEqual(resolve(account, [c])['value'], '00123')

    def test_identifier_label_may_be_a_separate_block(self):
        contract = spec('contract_no', '合同号')
        p = page(text='Contract No.:')
        p.blocks.append(Block('p1b1', 'PI-123', [.6, .2, .7, .25], .99, 'paddle_http'))
        c = validate_candidate(candidate('PI-123', 'Contract No.: PI-123', ids=['p1b0', 'p1b1']),
                               contract, [p], 'vision')
        self.assertEqual(c['issues'], [])

    def test_complete_occurrence_cannot_be_hidden_by_another_partial_occurrence(self):
        contract = spec('contract_no', '合同号')
        c = validate_candidate(candidate('PI-123', 'PI-123'), contract,
                               [page(text='PI-123-OLD; effective contract: PI-123.')], 'vision')
        self.assertEqual(c['issues'], [])

    def test_incomplete_identifier_does_not_discard_different_grounded_full_id(self):
        contract = spec('contract_no', '合同号')
        p = page(text='PI-123-CONTRACT')
        incomplete = validate_candidate(candidate('PI-123', 'PI-123'), contract, [p], 'ocr_semantic')
        complete = validate_candidate(candidate('PI-123-CONTRACT', 'PI-123-CONTRACT'), contract, [p], 'vision')
        self.assertIn('IDENTIFIER_SOURCE_INCOMPLETE', incomplete['issues'])
        self.assertEqual(complete['issues'], [])
        # A new grounding guard is not permission to silently arbitrate channels.
        self.assertEqual(resolve(contract, [incomplete, complete])['status'], 'conflict')


if __name__ == '__main__':
    unittest.main()
