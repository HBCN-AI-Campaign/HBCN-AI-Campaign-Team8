import unittest
import json
import httpx
from unittest.mock import Mock, patch

from app.config import settings
from app.embedding import EMBEDDING_BATCH_SIZE, EmbeddingClient


class EmbeddingClientTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "BAILIAN_BASE_URL": settings.BAILIAN_BASE_URL,
            "BAILIAN_API_KEY": settings.BAILIAN_API_KEY,
        }
        settings.BAILIAN_BASE_URL = "https://bailian.example/v1"
        settings.BAILIAN_API_KEY = "test-key"

    def tearDown(self):
        for key, value in self.values.items():
            setattr(settings, key, value)

    def test_embed_splits_batches_and_preserves_order(self):
        offset = 0
        batches = []

        def create_response(request):
            nonlocal offset
            payload = json.loads(request.content)
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            size = len(payload["input"])
            batches.append(size)
            items = [
                {"index": index, "embedding": [float(offset + index)]}
                for index in reversed(range(size))
            ]
            offset += size
            return httpx.Response(200, json={"data": items})

        texts = [f"text-{index}" for index in range(EMBEDDING_BATCH_SIZE + 1)]
        original_client = httpx.AsyncClient
        with patch("app.embedding.httpx.AsyncClient", side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(create_response), **kwargs)):
            vectors = EmbeddingClient().embed(texts)
        self.assertEqual(batches, [20, 1])
        self.assertEqual(vectors, [[float(index)] for index in range(len(texts))])


if __name__ == "__main__":
    unittest.main()
