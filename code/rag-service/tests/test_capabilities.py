import unittest
from unittest.mock import patch

from app.config import settings
from app.main import capabilities


class CapabilitiesTests(unittest.TestCase):
    def test_local_engine_advertises_backend_upload_constraints(self):
        original_limit = settings.MAX_UPLOAD_BYTES
        original_timeout = settings.UPLOAD_TIMEOUT_SECONDS
        settings.MAX_UPLOAD_BYTES = 1024 * 1024
        settings.UPLOAD_TIMEOUT_SECONDS = 420
        try:
            with patch("app.main.engine_kind", return_value="local"):
                result = capabilities()
        finally:
            settings.MAX_UPLOAD_BYTES = original_limit
            settings.UPLOAD_TIMEOUT_SECONDS = original_timeout

        self.assertEqual(result.max_upload_bytes, 1024 * 1024)
        self.assertEqual(result.upload_timeout_seconds, 420)
        self.assertIn(".pdf", result.supported_file_extensions)
        self.assertIn(".txt", result.supported_file_extensions)
        self.assertEqual(result.supported_file_extensions, sorted(result.supported_file_extensions))

    def test_unconfigured_engine_still_advertises_file_contract(self):
        with patch("app.main.engine_kind", return_value="none"):
            result = capabilities()

        self.assertFalse(result.document_ingestion)
        self.assertGreater(result.max_upload_bytes, 0)
        self.assertGreater(result.upload_timeout_seconds, 0)
        self.assertIn(".pdf", result.supported_file_extensions)


if __name__ == "__main__":
    unittest.main()
