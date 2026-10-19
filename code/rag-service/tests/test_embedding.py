import unittest
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

    @patch("app.embedding.httpx.post")
    def test_embed_splits_batches_and_preserves_order(self, post):
        offset = 0

        def create_response(*args, json, **kwargs):
            nonlocal offset
            size = len(json["input"])
            items = [
                {"index": index, "embedding": [float(offset + index)]}
                for index in reversed(range(size))
            ]
            offset += size
            response = Mock(status_code=200)
            response.json.return_value = {"data": items}
            return response

        post.side_effect = create_response
        texts = [f"text-{index}" for index in range(EMBEDDING_BATCH_SIZE + 1)]

        vectors = EmbeddingClient().embed(texts)

        self.assertEqual(post.call_count, 2)
        self.assertEqual([len(call.kwargs["json"]["input"]) for call in post.call_args_list], [20, 1])
        self.assertEqual(vectors, [[float(index)] for index in range(len(texts))])


if __name__ == "__main__":
    unittest.main()
