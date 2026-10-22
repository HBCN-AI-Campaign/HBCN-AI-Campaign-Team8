import os
import re
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import Boolean, Column, MetaData, String, Table, Text, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import settings
from app.database import ResourceError, sql_engine
from app.lexical_index import TOKENIZER_VERSION, backfill, lexical_table, lexical_tokens, query_expression
from app.postgres_engine import PostgresEngine
from app.retrieval_fusion import fuse_channels


class HybridMechanismTests(unittest.TestCase):
    def test_tokenization_keeps_chinese_terms_and_normalizes_latin(self):
        tokens = lexical_tokens("支付指令金额错误，USD５０００；payment instruction")
        self.assertIn("金额", tokens)
        self.assertIn("支付", tokens)
        self.assertIn("payment", tokens)
        self.assertIn("5000", " ".join(tokens))
        self.assertTrue(all(re.fullmatch(r"[^\W_]+", value) for value in lexical_tokens("' OR ! & | : * () -- 金额")))
        self.assertIsNone(query_expression("!!!"))

    def test_both_channels_can_contribute_without_score_threshold_mixing(self):
        def item(key, score):
            return {"content": key, "document_id": key, "chunk_id": key, "similarity": score, "metadata": {}}
        result = fuse_channels([item("vector-only", 0.9), item("shared", 0.8)],
                               [item("lexical-only", 0.01), item("shared", 0.001)], top_k=3)
        self.assertEqual(result[0]["document_id"], "shared")
        self.assertEqual({entry["document_id"] for entry in result}, {"shared", "lexical-only", "vector-only"})
        self.assertTrue(all(entry["similarity"] is None for entry in result))
        self.assertEqual({hit["score_type"] for hit in result[0]["metadata"]["channel_fusion"]["hits"]},
                         {"cosine_similarity", "ts_rank_cd"})
        lexical_only = fuse_channels([], [item("first", 0.9), item("second", 0.1)], top_k=2)
        self.assertEqual([entry["document_id"] for entry in lexical_only], ["first", "second"])


@unittest.skipUnless(os.environ.get("HBCN_TEST_POSTGRES") == "1", "explicit opt-in required for isolated PostgreSQL schema test")
class HybridPostgresTests(unittest.TestCase):
    """Actual PostgreSQL FTS, FK, filters and migration; synthetic data only.

    Creates/drops exactly one random test schema, never the configured RAG schema.
    This does not test live embeddings, quality benchmarks or production rollout.
    """
    def test_live_lexical_hybrid_and_lifecycle(self):
        engine = sql_engine()
        schema = "rag_lex_test_" + uuid.uuid4().hex
        self.assertRegex(schema, r"^rag_lex_test_[0-9a-f]{32}$")
        metadata = MetaData(schema=schema)
        chunks = Table("chunks", metadata, Column("langchain_id", UUID(as_uuid=True), primary_key=True),
                       Column("content", Text, nullable=False), Column("document_id", String, nullable=False),
                       Column("scope", String, nullable=False), Column("embedding_model", String, nullable=False),
                       Column("searchable", Boolean, nullable=False), Column("langchain_metadata", JSONB, nullable=False))
        def row(content, *, scope="business_rules", model=None, searchable=True):
            key = uuid.uuid4()
            return {"langchain_id": key, "document_id": str(key), "content": content, "scope": scope,
                    "embedding_model": settings.EMBEDDING_MODEL if model is None else model,
                    "searchable": searchable, "langchain_metadata": {"filename": "synthetic.txt", "scope": scope}}
        data = [row("支付指令金额错误，应核对支持单据并按更正流程重新提交。"),
                row("Payment instruction amount discrepancy requires correction."),
                row("金额错误：内部项目设计资料", scope="project_design"),
                row("金额错误：尚未完成处理", searchable=False), row("金额错误：旧模型", model="old-model")]
        service = PostgresEngine.__new__(PostgresEngine)
        service.documents = SimpleNamespace(engine=engine)
        service.chunks = chunks
        service.lexical = lexical_table(chunks)
        service.vectors = Mock()
        service.vectors.similarity_search_with_score.return_value = []
        try:
            with engine.begin() as connection:
                connection.execute(CreateSchema(schema))
            chunks.create(engine)
            with engine.begin() as connection:
                connection.execute(chunks.insert(), data)
            with patch.object(settings, "RAG_SEARCH_MODE", "hybrid"):
                with self.assertRaises(ResourceError):
                    service.retrieve(query="金额错误", scope="business_rules", top_k=5)
                self.assertEqual(backfill(engine, chunks, batch_size=2), 5)
                self.assertEqual(backfill(engine, chunks), 0)
                next(iter(service.lexical.indexes)).drop(engine)
                with self.assertRaises(ResourceError):
                    service.retrieve(query="金额", scope="all", top_k=5)
                self.assertEqual(backfill(engine, chunks), 0)
                result = service.retrieve(query="支付指令金额错误", scope="business_rules", top_k=5)
                self.assertEqual([item["document_id"] for item in result], [data[0]["document_id"]])
                self.assertIsNone(result[0]["similarity"])
                service.vectors.similarity_search_with_score.assert_called_with(
                    "支付指令金额错误", k=5,
                    filter={"embedding_model": settings.EMBEDDING_MODEL, "searchable": True, "scope": "business_rules"})
                english = service.retrieve(query="payment amount correction", scope="business_rules", top_k=5)
                self.assertEqual([item["document_id"] for item in english], [data[1]["document_id"]])
                scoped = service.retrieve(query="金额错误", scope="all", top_k=5)
                self.assertEqual({item["document_id"] for item in scoped}, {data[0]["document_id"], data[2]["document_id"]})
                with engine.begin() as connection:
                    connection.execute(update(service.lexical).where(service.lexical.c.chunk_id == data[0]["langchain_id"])
                                       .values(tokenizer_version="obsolete"))
                with self.assertRaises(ResourceError):
                    service.retrieve(query="金额", scope="all", top_k=5)
                self.assertEqual(backfill(engine, chunks), 1)
                with engine.begin() as connection:
                    connection.execute(delete(chunks).where(chunks.c.langchain_id == data[0]["langchain_id"]))
                    self.assertEqual(connection.execute(select(func.count()).select_from(service.lexical)).scalar_one(), 4)
                    versions = connection.execute(select(service.lexical.c.tokenizer_version).distinct()).scalars().all()
                    self.assertEqual(versions, [TOKENIZER_VERSION])
        finally:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))


if __name__ == "__main__":
    unittest.main()
