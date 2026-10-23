"""Focused deterministic checks for business-rule boundaries."""
import unittest

from app.business_review.service import _finding
from app.rule_engine.base import DocBundle, Status
from app.rule_engine.rules import R_SupportingAmountChain, R_SupportingBuyer, R_SupportingContractNo


class SupportingRuleTests(unittest.TestCase):
    def test_customs_protocol_can_match_invoice_number_but_wrong_waybill_contract_fails(self):
        documents = DocBundle(by_type={
            "COMMERCIAL_CONTRACT": [{"contract_no": "CT-1"}],
            "PROFORMA_INVOICE": [{"contract_no": "CT-1", "invoice_no": "IV-1"}],
            "CUSTOMS_DECLARATION": [{"contract_no": "IV-1"}],
        })
        self.assertEqual(R_SupportingContractNo().evaluate(documents).status, Status.PASS)

        documents.by_type["WAYBILL"] = [{"contract_no": "CT-OTHER"}]
        self.assertEqual(R_SupportingContractNo().evaluate(documents).status, Status.FAIL)

    def test_invoice_above_contract_is_a_hard_failure(self):
        documents = DocBundle(by_type={
            "COMMERCIAL_CONTRACT": [{"amount": 100}],
            "PROFORMA_INVOICE": [{"amount": 101}],
        })
        self.assertEqual(R_SupportingAmountChain().evaluate(documents).status, Status.FAIL)

    def test_buyer_borrower_source_conflict_is_routed_to_human_review(self):
        documents = DocBundle(by_type={
            "FACILITY_LETTER": [{"borrower": "Borrower Ltd"}],
            "COMMERCIAL_CONTRACT": [{"buyer": "Buyer Ltd"}],
            "PROFORMA_INVOICE": [{"buyer": "Buyer Ltd"}],
        }, meta_by_type={
            "FACILITY_LETTER": [{"doc_id": 11, "field_sources": {"borrower": {"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]}}}],
            "COMMERCIAL_CONTRACT": [{"doc_id": 12, "field_sources": {"buyer": {"page": 2, "bbox": [0.2, 0.2, 0.3, 0.3]}}}],
            "PROFORMA_INVOICE": [{"doc_id": 13, "field_sources": {"buyer": {"page": 3, "bbox": [0.3, 0.3, 0.4, 0.4]}}}],
        })
        finding = _finding(R_SupportingBuyer().evaluate(documents))
        self.assertEqual(finding["status"], "needs_review")
        self.assertTrue(finding["requires_resolution"])
        self.assertEqual(finding["business_conflict"], "BUYER_BORROWER_RULE_CONFLICT")
        self.assertEqual(finding["evidence"][0][3]["doc_id"], 11)


if __name__ == "__main__":
    unittest.main()
