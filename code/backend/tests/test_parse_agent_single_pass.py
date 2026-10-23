import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app import parse_agent


class ParseAgentSinglePassTests(unittest.TestCase):
    def test_payment_fields_reuse_detailed_ocr_response(self):
        requests = []
        payload = {
            "text": "金额：100",
            "blocks": [{"text": "金额：100", "score": 0.92, "box": [1, 2, 3, 4], "page": 1}],
            "fields": [
                {"key": "amount", "label": "金额", "value": "100", "found": True, "confidence": 0.9}
            ],
        }

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=payload)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "app" / "uploads"
            pdf_path = upload_dir / "set_8" / "payment.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"pdf-content")
            transport = httpx.MockTransport(respond)
            with httpx.Client(transport=transport) as client, patch(
                "app.parse_agent.httpx.post", side_effect=client.post
            ) as post, patch("app.parse_agent.UPLOAD_DIR", upload_dir), patch(
                "app.parse_agent.settings.OCR_BASE_URL", "http://ocr-service"
            ), patch("app.parse_agent.settings.OCR_REQUEST_TIMEOUT_SECONDS", 1200.0):
                result = parse_agent.parse_files(
                    [{"filename": "payment.pdf", "pdf_url": "uploads/set_8/payment.pdf"}]
                )

        self.assertEqual(len(requests), 1)
        self.assertEqual(post.call_args.kwargs["timeout"], 1200.0)
        self.assertIn(b"PAYMENT_INSTRUCTION", requests[0].read())
        fields = {field["key"]: field for field in result["documents"][0]["fields"]}
        self.assertEqual(fields["amount"]["value"], "100")
        self.assertEqual(fields["amount"]["source"]["page"], 1)

    def test_fields_without_matching_text_blocks_do_not_get_high_confidence(self):
        value, confidence, source = parse_agent._find_with_source("借款人：Borrower Ltd", ["借款人"], [])
        self.assertEqual(value, "Borrower Ltd")
        self.assertEqual(confidence, 0.0)
        self.assertIsNone(source["page"])
        self.assertIsNone(source["bbox"])

        field = parse_agent._from_ocr_field({
            "key": "amount", "label": "金额", "value": "100", "found": True, "confidence": 0.99,
        }, [])
        self.assertEqual(field["confidence"], 0.0)
        self.assertIsNone(field["source"])

    def test_ocr_error_logs_exclude_response_body_and_local_path(self):
        with tempfile.TemporaryDirectory(prefix="private-ocr-log-") as directory:
            pdf_path = Path(directory) / "sensitive-document.pdf"
            pdf_path.write_bytes(b"test pdf")
            response_body = f"private OCR response with customer data at {pdf_path}"
            transport = httpx.MockTransport(lambda request: httpx.Response(500, text=response_body))
            with httpx.Client(transport=transport) as client, patch(
                "app.parse_agent.httpx.post", side_effect=client.post
            ), self.assertLogs("app.parse_agent", level="INFO") as captured:
                self.assertEqual(parse_agent._ocr_detailed(str(pdf_path)), ("", [], []))
                self.assertEqual(parse_agent._ocr_extract(str(pdf_path), "PAYMENT_INSTRUCTION"), [])

            non_200_logs = "\n".join(captured.output)
            self.assertIn("status=500", non_200_logs)
            self.assertNotIn(response_body, non_200_logs)
            self.assertNotIn(str(pdf_path), non_200_logs)

            with patch("app.parse_agent.httpx.post", side_effect=RuntimeError(f"private failure {pdf_path}")), self.assertLogs(
                "app.parse_agent", level="WARNING"
            ) as captured:
                self.assertEqual(parse_agent._ocr_detailed(str(pdf_path)), ("", [], []))
                self.assertEqual(parse_agent._ocr_extract(str(pdf_path), "PAYMENT_INSTRUCTION"), [])

            exception_logs = "\n".join(captured.output)
            self.assertIn("error_type=RuntimeError", exception_logs)
            self.assertNotIn("private failure", exception_logs)
            self.assertNotIn(str(pdf_path), exception_logs)


if __name__ == "__main__":
    unittest.main()
