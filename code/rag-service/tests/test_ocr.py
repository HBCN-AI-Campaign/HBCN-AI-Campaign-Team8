"""OCR provider selection and response handling."""
import unittest
from unittest.mock import Mock, patch

from app.ocr import OCRClient


class OCRClientTests(unittest.TestCase):
    def make_client(self):
        client = OCRClient()
        client.base_url = "http://ocr.test"
        client.timeout = 2
        client.vision_base_url = "https://bailian.test/v1"
        client.vision_api_key = "test-key"
        client.vision_model = "vision-model"
        client.service_api_key = "ocr-service-key"
        return client

    @patch("app.ocr.httpx.post")
    def test_remote_ocr_api_uses_optional_bearer_and_contract(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "recognized", "via_ocr": True}
        post.return_value = response

        result = self.make_client().extract("scan.png", b"image")

        self.assertEqual(result, {"text": "recognized", "via_ocr": True, "error": None})
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer ocr-service-key"})
        self.assertTrue(post.call_args.args[0].endswith("/ocr/file"))

    @patch("app.ocr.httpx.post")
    def test_image_falls_back_to_multimodal_when_remote_is_unavailable(self, post):
        remote = Mock(status_code=503)
        vision = Mock(status_code=200)
        vision.json.return_value = {"choices": [{"message": {"content": "vision text"}}]}
        post.side_effect = [remote, vision]

        result = self.make_client().extract("scan.png", b"image")

        self.assertEqual(result, {"text": "vision text", "via_ocr": True, "error": None})
        self.assertEqual(post.call_count, 2)
        self.assertTrue(post.call_args.args[0].endswith("/chat/completions"))

    @patch("app.ocr.httpx.post")
    def test_invalid_remote_response_uses_multimodal_fallback(self, post):
        remote = Mock(status_code=200)
        remote.json.return_value = {"unexpected": "shape"}
        vision = Mock(status_code=200)
        vision.json.return_value = {
            "choices": [{"message": {"content": [{"type": "text", "text": "vision text"}]}}]
        }
        post.side_effect = [remote, vision]

        result = self.make_client().extract("scan.jpg", b"image")

        self.assertEqual(result["text"], "vision text")
        self.assertIsNone(result["error"])

    @patch("app.ocr.httpx.post")
    def test_documents_do_not_get_sent_to_image_only_vision_fallback(self, post):
        post.return_value = Mock(status_code=503)

        result = self.make_client().extract("scan.pdf", b"pdf")

        self.assertIsNotNone(result["error"])
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
