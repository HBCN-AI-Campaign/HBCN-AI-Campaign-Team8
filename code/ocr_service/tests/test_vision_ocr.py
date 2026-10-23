import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ocr_service import config
from ocr_service.parser import parse_file, parse_image_detailed
from ocr_service.vision_ocr import recognize_page


class VisionOcrTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch.multiple(
            config,
            OCR_VISION_ENABLED=True,
            OCR_VISION_BASE_URL="https://vision.example/v1",
            OCR_VISION_API_KEY="test-secret",
            OCR_VISION_MODEL="vision-test",
            OCR_VISION_TIMEOUT_SECONDS=3.0,
            OCR_VISION_MAX_IMAGE_BYTES=100,
            OCR_VISION_TRIGGER_MIN_LINES=2,
            OCR_VISION_TRIGGER_MIN_SCORE=0.55,
        )
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()

    def test_disabled_or_insecure_endpoint_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "page.png"
            image.write_bytes(b"png-data")
            with patch.object(config, "OCR_VISION_ENABLED", False), patch("ocr_service.vision_ocr.httpx.post") as post:
                self.assertIsNone(recognize_page(image))
                post.assert_not_called()
            with patch.object(config, "OCR_VISION_BASE_URL", "http://outside.example/v1"), patch("ocr_service.vision_ocr.httpx.post") as post:
                self.assertIsNone(recognize_page(image))
                post.assert_not_called()

    def test_sends_page_as_data_url_and_accepts_only_complete_text(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "借款人：示例"}}]}
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "page.png"
            image.write_bytes(b"png-data")
            with patch("ocr_service.vision_ocr.httpx.post", return_value=response) as post:
                self.assertEqual(recognize_page(image), "借款人：示例")
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://vision.example/v1/chat/completions")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
            data_url = kwargs["json"]["messages"][0]["content"][0]["image_url"]["url"]
            self.assertEqual(data_url, f"data:image/png;base64,{base64.b64encode(b'png-data').decode('ascii')}")

            response.json.return_value["choices"][0]["finish_reason"] = "length"
            with patch("ocr_service.vision_ocr.httpx.post", return_value=response):
                self.assertIsNone(recognize_page(image))

    def test_vision_candidate_has_no_fabricated_score_or_bbox(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "page.png"
            image.write_bytes(b"png-data")
            local = [{"text": "x", "score": 0.2, "box": [1, 2, 3, 4], "poly": []}]
            with patch("ocr_service.parser.is_configured", return_value=True), \
                    patch("ocr_service.parser.recognize_page", return_value="金额：100\n币种：USD"), \
                    patch("ocr_service.ocr_engine.recognize_image_detailed", return_value=local):
                parsed = parse_image_detailed(image)

        self.assertEqual(parsed["method"], "vision_ocr")
        self.assertEqual([item["score"] for item in parsed["blocks"]], [0.0, 0.0])
        self.assertTrue(all(item["box"] is None for item in parsed["blocks"]))
        self.assertTrue(all(item["method"] == "vision_ocr" for item in parsed["blocks"]))

    def test_simple_pdf_entry_preserves_vision_method(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.pdf"
            path.write_bytes(b"test")
            with patch("ocr_service.parser._parse_pdf_with_method", return_value=("candidate text", True, "vision_ocr")):
                parsed = parse_file(path)

        self.assertEqual(parsed["text"], "candidate text")
        self.assertEqual(parsed["method"], "vision_ocr")

    def test_parse_error_exposes_type_without_logging_exception_content(self):
        with patch("ocr_service.parser.parse_pdf_detailed", side_effect=RuntimeError("private document detail")):
            with self.assertLogs("ocr_service.parser", level="ERROR") as captured:
                parsed = parse_file(Path("document.pdf"), detailed=True)

        self.assertEqual(parsed["error_type"], "RuntimeError")
        self.assertIn("RuntimeError", captured.output[0])
        self.assertNotIn("private document detail", captured.output[0])


if __name__ == "__main__":
    unittest.main()
