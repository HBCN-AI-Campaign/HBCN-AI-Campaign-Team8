from decimal import Decimal
from types import SimpleNamespace
import unittest

from app.assistant_service import search_evidence, task_context


class AssistantBusinessContextTests(unittest.TestCase):
    def test_task_context_keeps_rule_citation_source(self):
        task = SimpleNamespace(
            task_code="task-1",
            borrower="Borrower",
            drawdown_currency="USD",
            drawdown_amount=Decimal("100"),
            status="pending",
            documents=[],
            results=[SimpleNamespace(
                rule_id="RULE_1",
                rule_name="Rule",
                status="pass",
                why="Matched",
                suggestion="",
            )],
        )

        context = task_context(task)

        self.assertEqual(context["citations"][0]["source"], "规则审核结果")

    def test_rule_evidence_uses_its_specific_source(self):
        context = {
            "results": [{
                "rule_id": "BUYER_BORROWER_RULE_CONFLICT",
                "source": "requirements.xlsx / buyer row",
                "rule_name": "Source conflict",
            }],
            "documents": [],
        }

        hits = search_evidence(context, "")

        self.assertEqual(hits[0]["source"], "requirements.xlsx / buyer row")


if __name__ == "__main__":
    unittest.main()
