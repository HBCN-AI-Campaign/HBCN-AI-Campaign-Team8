import sys
import types
import unittest
from unittest.mock import Mock, patch

from ocr_service import config
from ocr_service.ocr_engine import OcrEngine


class OcrEngineConfigTests(unittest.TestCase):
    def test_configured_cpu_threads_are_passed_to_paddle(self):
        paddleocr = types.ModuleType("paddleocr")
        paddleocr.PaddleOCR = Mock(return_value=object())
        with patch.dict(sys.modules, {"paddleocr": paddleocr}), patch.object(
            config, "OCR_CPU_THREADS", 3
        ), patch.object(config, "OCR_TEXT_RECOGNITION_BATCH_SIZE", 8):
            OcrEngine()._ensure()

        paddleocr.PaddleOCR.assert_called_once()
        self.assertEqual(paddleocr.PaddleOCR.call_args.kwargs["cpu_threads"], 3)
        self.assertEqual(
            paddleocr.PaddleOCR.call_args.kwargs["text_recognition_batch_size"], 8
        )


if __name__ == "__main__":
    unittest.main()
