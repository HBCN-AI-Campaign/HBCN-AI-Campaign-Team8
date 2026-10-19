"""本地引擎（百炼 Embedding + SQLite 向量库 + OCR）的单元测试。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.engine import LocalEngine, chunk_text, engine_kind, get_engine
from app.local_store import LocalVectorStore
from app.ragflow import RAGFlowClient, RAGFlowNotConfiguredError


class ChunkTextTests(unittest.TestCase):
    def test_empty_and_short(self):
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("短文本", size=100), ["短文本"])

    def test_split_with_overlap(self):
        chunks = chunk_text("abcdefghij", size=5, overlap=2)
        self.assertEqual(chunks, ["abcde", "defgh", "ghij"])


class LocalVectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LocalVectorStore(Path(self.tmp.name) / "store.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_query_by_cosine(self):
        chunks = [
            {"content": "贷款用途证明材料", "page": None, "metadata": {"source": "a.txt"}, "embedding": [1.0, 0.0]},
            {"content": "提单验真与制裁名单", "page": None, "metadata": {"source": "b.txt"}, "embedding": [0.0, 1.0]},
        ]
        self.store.add_document("demo.txt", "business_rules", chunks)

        results = self.store.query([1.0, 1.0], "business_rules", top_k=3)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["content"], "贷款用途证明材料")
        for item in results:
            self.assertGreaterEqual(item["similarity"], 0.7)

    def test_reupload_replaces_document_chunks(self):
        self.store.add_document("policy.md", "business_rules", [
            {"content": "旧规则", "embedding": [1.0, 0.0]},
        ])
        self.store.add_document("policy.md", "business_rules", [
            {"content": "新规则", "embedding": [0.0, 1.0]},
        ])

        documents = self.store.list_documents("business_rules")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["chunk_count"], 1)
        results = self.store.query([0.0, 1.0], "business_rules", top_k=3)
        self.assertEqual([item["content"] for item in results], ["新规则"])

    def test_scope_isolation(self):
        self.store.add_document("a.txt", "business_rules", [{"content": "规则", "embedding": [1.0, 0.0]}])
        self.assertEqual(self.store.query([1.0, 0.0], "project_design", top_k=5), [])

    def test_list_documents(self):
        self.store.add_document("a.txt", "business_rules", [{"content": "规则", "embedding": [1.0, 0.0]}])
        docs = self.store.list_documents()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "a.txt")
        self.assertEqual(docs[0]["chunk_count"], 1)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "RAG_ENGINE": settings.RAG_ENGINE,
            "RAGFLOW_BASE_URL": settings.RAGFLOW_BASE_URL,
            "RAGFLOW_API_KEY": settings.RAGFLOW_API_KEY,
            "BAILIAN_BASE_URL": settings.BAILIAN_BASE_URL,
            "BAILIAN_API_KEY": settings.BAILIAN_API_KEY,
            "LOCAL_STORE_PATH": settings.LOCAL_STORE_PATH,
        }

    def tearDown(self):
        for key, value in self.values.items():
            setattr(settings, key, value)

    def test_engine_kind_and_factory(self):
        settings.RAG_ENGINE = "auto"
        settings.RAGFLOW_BASE_URL = ""
        settings.RAGFLOW_API_KEY = ""
        settings.BAILIAN_BASE_URL = ""
        settings.BAILIAN_API_KEY = ""
        self.assertEqual(engine_kind(), "none")
        with self.assertRaises(RAGFlowNotConfiguredError):
            get_engine()

        settings.BAILIAN_BASE_URL = "https://bailian.example/v1"
        settings.BAILIAN_API_KEY = "k"
        self.assertEqual(engine_kind(), "local")
        self.assertIsInstance(get_engine(), LocalEngine)

        settings.RAGFLOW_BASE_URL = "http://ragflow:9380"
        settings.RAGFLOW_API_KEY = "k"
        self.assertEqual(engine_kind(), "ragflow")
        self.assertIsInstance(get_engine(), RAGFlowClient)

    def test_explicit_engine_selection_does_not_fall_back(self):
        settings.RAG_ENGINE = "ragflow"
        settings.RAGFLOW_BASE_URL = ""
        settings.RAGFLOW_API_KEY = ""
        settings.BAILIAN_BASE_URL = "https://bailian.example/v1"
        settings.BAILIAN_API_KEY = "k"
        self.assertEqual(engine_kind(), "none")

        settings.RAG_ENGINE = "local"
        settings.RAGFLOW_BASE_URL = "http://ragflow:9380"
        settings.RAGFLOW_API_KEY = "k"
        self.assertEqual(engine_kind(), "local")

    def test_local_engine_upload_and_retrieve(self):
        settings.RAG_ENGINE = "local"
        settings.RAGFLOW_BASE_URL = ""
        settings.RAGFLOW_API_KEY = ""
        settings.BAILIAN_BASE_URL = "https://bailian.example/v1"
        settings.BAILIAN_API_KEY = "k"
        settings.LOCAL_STORE_PATH = "test_store.sqlite3"

        with patch("app.engine.EmbeddingClient") as MockEmbedding, \
             patch("app.engine.OCRClient") as MockOCR, \
             patch("app.engine.LocalVectorStore") as MockStore:
            engine = LocalEngine()
            engine.ocr.extract.return_value = {"text": "贷款用途证明", "via_ocr": False, "error": None}
            engine.embedding.embed.return_value = [[1.0, 0.0]]
            engine.embedding.embed_one.return_value = [1.0, 0.0]
            engine.store.add_document.return_value = "doc-1"
            engine.store.query.return_value = [{"content": "贷款用途证明", "document_keyword": "a.txt", "similarity": 0.9}]

            ids = engine.upload(scope="business_rules", filename="a.txt", content=b"text")
            self.assertEqual(ids, ["doc-1"])

            chunks = engine.retrieve(query="用途", scope="business_rules", top_k=3)
            self.assertEqual(chunks[0]["content"], "贷款用途证明")


if __name__ == "__main__":
    unittest.main()
