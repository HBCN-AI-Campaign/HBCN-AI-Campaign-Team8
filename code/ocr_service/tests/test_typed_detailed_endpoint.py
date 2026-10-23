import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TypedDetailedEndpointTests(unittest.TestCase):
    def test_optional_type_code_returns_fields_from_same_parse(self):
        parsed = {
            "text": "金额：100",
            "blocks": [{"text": "金额：100", "score": 0.9, "box": [1, 2, 3, 4], "page": 1}],
            "via_ocr": True,
            "method": "paddleocr",
            "label": "PDF",
            "error": None,
        }
        fields = [{"key": "amount", "value": "100", "found": True}]
        with patch("main.parse_file", return_value=parsed) as parse_file, patch(
            "main.extract_fields", return_value={"fields": fields}
        ) as extract_fields:
            response = TestClient(app).post(
                "/file/detailed",
                data={"type_code": "PAYMENT_INSTRUCTION"},
                files={"file": ("payment.pdf", b"pdf-content", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"], fields)
        parse_file.assert_called_once()
        extract_fields.assert_called_once_with("PAYMENT_INSTRUCTION", "金额：100")

    def test_unknown_optional_type_code_is_rejected(self):
        with patch("main.parse_file") as parse_file:
            response = TestClient(app).post(
                "/file/detailed",
                data={"type_code": "UNKNOWN"},
                files={"file": ("payment.pdf", b"pdf-content", "application/pdf")},
            )

        self.assertEqual(response.status_code, 400)
        parse_file.assert_not_called()

    def test_parse_failure_exposes_type_without_exception_details(self):
        parsed = {
            "error": "RuntimeError: private document detail",
            "error_type": "RuntimeError",
        }
        client = TestClient(app)
        with patch("main.parse_file", return_value=parsed):
            detailed = client.post(
                "/file/detailed",
                files={"file": ("payment.pdf", b"pdf-content", "application/pdf")},
            )
            extract = client.post(
                "/extract",
                data={"type_code": "PAYMENT_INSTRUCTION"},
                files={"file": ("payment.pdf", b"pdf-content", "application/pdf")},
            )

        for response in (detailed, extract):
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["error_type"], "RuntimeError")
            self.assertEqual(response.json()["error"], "文档解析失败")
            self.assertNotIn("private document detail", response.text)


if __name__ == "__main__":
    unittest.main()
