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


if __name__ == "__main__":
    unittest.main()
