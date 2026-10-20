import asyncio
import io
import time
import unittest
from unittest.mock import patch

from app.main import index_document
from starlette.datastructures import UploadFile


class SlowEngine:
    def upload(self, **kwargs):
        time.sleep(0.3)
        return ["synthetic-document-id"]


class DocumentUploadTests(unittest.TestCase):
    def test_synchronous_ingestion_does_not_block_the_asgi_event_loop(self):
        async def run_upload():
            file = UploadFile(filename="synthetic.txt", file=io.BytesIO(b"synthetic test"))
            with patch("app.main.get_engine", return_value=SlowEngine()):
                task = asyncio.create_task(index_document(scope="business_rules", file=file))
                await asyncio.sleep(0.03)
                self.assertFalse(task.done())
                return await task

        response = asyncio.run(run_upload())
        self.assertEqual(response.status, "processing")
        self.assertEqual(response.document_ids, ["synthetic-document-id"])


if __name__ == "__main__":
    unittest.main()
