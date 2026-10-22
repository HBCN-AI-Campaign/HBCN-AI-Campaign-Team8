from __future__ import annotations

import math
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import MetaData, Table, inspect, select, text, update, func
from sqlalchemy.dialects.postgresql.base import ischema_names
from pgvector.sqlalchemy import Vector

from .config import settings
from .database import ResourceError, database_url
from .document_store import DocumentStore, utc_now
from .embedding import EmbeddingClient, EmbeddingError
from .parsing import ParseError, extract_pages
from .lexical_index import TOKENIZER_VERSION, index_chunk, lexical_table, pending_chunks, query_expression
from .retrieval_fusion import fuse_channels


SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv", ".json", ".mmd", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}


class BailianEmbeddings(Embeddings):
    def embed_documents(self, texts):
        vectors = EmbeddingClient().embed(texts)
        if any(len(vector) != settings.EMBEDDING_DIMENSIONS or not all(math.isfinite(value) for value in vector) for vector in vectors):
            raise EmbeddingError("Embedding 维度或数值无效，请检查模型配置")
        return vectors

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class PostgresEngine:
    synchronous_upload_ready = True

    def __init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,48}", settings.RAG_VECTOR_TABLE):
            raise ResourceError("向量表配置无效")
        self.documents = DocumentStore()
        url = database_url()
        query = dict(url.query)
        sslmode = query.pop("sslmode", "require")
        timeout = int(query.pop("connect_timeout", "12"))
        if sslmode == "verify-full":
            import ssl

            ssl_context = ssl.create_default_context()
        else:
            ssl_context = False if sslmode == "disable" else "require"
        self.pg_engine = PGEngine.from_connection_string(
            url.set(drivername="postgresql+asyncpg", query=query),
            connect_args={"ssl": ssl_context, "timeout": timeout, "command_timeout": 60},
            pool_size=3, max_overflow=2, pool_pre_ping=True, hide_parameters=True,
        )
        columns = [Column("document_id", "TEXT", False), Column("scope", "TEXT", False),
                   Column("embedding_model", "TEXT", False), Column("searchable", "BOOLEAN", False)]
        if not inspect(self.documents.engine).has_table(settings.RAG_VECTOR_TABLE, schema=settings.RAG_DATABASE_SCHEMA):
            self.pg_engine.init_vectorstore_table(
                settings.RAG_VECTOR_TABLE, settings.EMBEDDING_DIMENSIONS,
                schema_name=settings.RAG_DATABASE_SCHEMA, metadata_columns=columns,
            )
        self.vectors = PGVectorStore.create_sync(
            engine=self.pg_engine, embedding_service=BailianEmbeddings(),
            table_name=settings.RAG_VECTOR_TABLE, schema_name=settings.RAG_DATABASE_SCHEMA,
            metadata_columns=[column.name for column in columns],
        )
        index_name = f"{settings.RAG_VECTOR_TABLE}_hnsw"
        if index_name not in {item["name"] for item in inspect(self.documents.engine).get_indexes(settings.RAG_VECTOR_TABLE, schema=settings.RAG_DATABASE_SCHEMA)}:
            self.vectors.apply_vector_index(HNSWIndex(name=index_name))
        ischema_names.setdefault("vector", Vector)
        self.chunks = Table(settings.RAG_VECTOR_TABLE, MetaData(), schema=settings.RAG_DATABASE_SCHEMA, autoload_with=self.documents.engine)
        self.lexical = lexical_table(self.chunks)
        if settings.RAG_SEARCH_MODE == "hybrid":
            self._require_lexical_ready()
        self.executor = ThreadPoolExecutor(max_workers=settings.RAG_MAX_CONCURRENT_JOBS, thread_name_prefix="rag-ingest")
        self.slots = threading.BoundedSemaphore(settings.RAG_MAX_CONCURRENT_JOBS * 4)

    def submit(self, *, scope, filename, content, content_type, provenance=None):
        if not self.slots.acquire(blocking=False):
            raise ResourceError("处理队列已满，请稍后重试")
        try:
            row, created = self.documents.create(filename, scope, content, content_type, provenance)
            if not created:
                self.slots.release()
                return self.documents.public(row), False
            self.executor.submit(self._job, row["id"])
            return self.documents.public(row), True
        except Exception:
            self.slots.release()
            raise

    def retry(self, document_id):
        if not self.slots.acquire(blocking=False):
            raise ResourceError("处理队列已满，请稍后重试")
        try:
            with self.documents.engine.begin() as connection:
                row = connection.execute(select(self.documents.table).where(self.documents.table.c.id == document_id).with_for_update()).mappings().first()
                if not row or row["state"] != "failed":
                    raise ResourceError("只能重试处理失败的文档")
                connection.execute(update(self.documents.table).where(self.documents.table.c.id == document_id).values(
                    state="queued", stage="received", error=None, updated_at=utc_now(),
                ))
            self.executor.submit(self._job, document_id)
        except Exception:
            self.slots.release()
            raise
        return self.documents.public(self.documents.get(document_id))

    def _job(self, document_id):
        try:
            self.process(document_id)
        finally:
            self.slots.release()

    def process(self, document_id):
        try:
            row = self.documents.get(document_id)
            self.vectors.delete(filter={"document_id": document_id})
            self.documents.set_stage(document_id, "parsing", "正在提取原文", state="processing", error=None)
            pages = extract_pages(row["name"], self.documents.original_path(document_id).read_bytes())
            self.documents.set_stage(document_id, "splitting", "正在切分可引用片段", pages=pages)
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP,
                add_start_index=True, separators=["\n\n", "\n", "。", "；", " ", ""],
            )
            inputs = [Document(page_content=page["text"], metadata={
                "document_id": document_id, "scope": row["scope"], "filename": row["name"],
                "embedding_model": settings.EMBEDDING_MODEL, "searchable": False,
                "page": page["page"], "section": page.get("section"), **row["provenance"],
            }) for page in pages if page["text"].strip()]
            chunks = splitter.split_documents(inputs)
            if not chunks:
                raise ParseError("没有可索引片段")
            for index, chunk in enumerate(chunks):
                chunk.metadata["chunk_index"] = index
            self.documents.set_stage(document_id, "embedding", "正在调用百炼生成向量")
            chunk_ids = [str(uuid.uuid4()) for _ in chunks]
            self.vectors.add_documents(chunks, ids=chunk_ids)
            self.documents.set_stage(document_id, "indexing", "正在提交检索索引")
            with self.documents.engine.begin() as connection:
                events = connection.execute(select(self.documents.table.c.events).where(self.documents.table.c.id == document_id).with_for_update()).scalar_one()
                if settings.RAG_SEARCH_MODE == "hybrid":
                    for chunk_id, chunk in zip(chunk_ids, chunks):
                        index_chunk(connection, self.lexical, uuid.UUID(chunk_id), chunk.page_content)
                connection.execute(update(self.chunks).where(self.chunks.c.document_id == document_id).values(searchable=True))
                connection.execute(update(self.documents.table).where(self.documents.table.c.id == document_id).values(
                    state="ready", stage="ready", chunk_count=len(chunks), updated_at=utc_now(),
                    events=[*events, {"stage": "ready", "label": "已完成，可开始问答", "at": utc_now().isoformat()}],
                ))
        except Exception as exc:
            message = str(exc) if isinstance(exc, ParseError) else "处理失败，请检查解析、向量服务或数据库连接后重试"
            self.documents.set_stage(document_id, "failed", "处理失败", state="failed", error=message)

    def upload(self, *, scope, filename, content, content_type="application/octet-stream"):
        row, created = self.documents.create(filename, scope, content, content_type)
        if created:
            self.process(row["id"])
        if self.documents.get(row["id"])["state"] != "ready":
            raise ResourceError("文档未完成索引，请通过处理状态接口检查或重试")
        return [row["id"]]

    def retrieve(self, *, query, scope, top_k):
        if settings.RAG_SEARCH_MODE == "hybrid":
            self._require_lexical_ready()
        filters = {"embedding_model": settings.EMBEDDING_MODEL, "searchable": True}
        if scope != "all":
            filters["scope"] = scope
        matches = self.vectors.similarity_search_with_score(query, k=top_k, filter=filters)
        results = []
        for document, distance in matches:
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            if score < settings.RAG_RETRIEVAL_MIN_SCORE:
                continue
            metadata = document.metadata
            document_id = metadata["document_id"]
            results.append({
                "content": document.page_content, "document_id": document_id,
                "document_keyword": metadata["filename"], "page_num": metadata.get("page"),
                "similarity": score, "chunk_id": str(document.id), "metadata": metadata,
                "source_url": f"/api/v1/documents/{document_id}/source",
                "reader_url": f"/api/v1/documents/{document_id}/content?chunk_id={document.id}",
            })
        if settings.RAG_SEARCH_MODE == "hybrid":
            return fuse_channels(results, self._lexical_retrieve(query=query, scope=scope, top_k=top_k), top_k=top_k)
        return results

    def _require_lexical_ready(self):
        inspector = inspect(self.documents.engine)
        if not inspector.has_table(self.lexical.name, schema=self.chunks.schema):
            raise ResourceError("混合检索词法索引尚未创建，请先运行 python -m app.lexical_index --apply")
        if self.chunks.name + "_lex_gin" not in {item["name"] for item in inspector.get_indexes(self.lexical.name, schema=self.chunks.schema)}:
            raise ResourceError("词法 GIN 索引缺失，请修复索引后再启用混合检索")
        with self.documents.engine.connect() as connection:
            missing = connection.execute(pending_chunks(self.chunks, self.lexical).where(
                self.chunks.c.searchable.is_(True), self.chunks.c.embedding_model == settings.EMBEDDING_MODEL,
            ).limit(1)).first()
        if missing:
            raise ResourceError("词法索引存在未回填或分词器版本不一致的片段，请运行词法回填命令")

    def _lexical_retrieve(self, *, query, scope, top_k):
        expression = query_expression(query)
        if expression is None:
            return []
        rank = func.ts_rank_cd(self.lexical.c.terms, expression, 32).label("lexical_rank")
        statement = select(self.chunks, rank).join(self.lexical, self.chunks.c.langchain_id == self.lexical.c.chunk_id).where(
            self.chunks.c.searchable.is_(True), self.chunks.c.embedding_model == settings.EMBEDDING_MODEL,
            self.lexical.c.tokenizer_version == TOKENIZER_VERSION, self.lexical.c.terms.op("@@")(expression),
        )
        if scope != "all":
            statement = statement.where(self.chunks.c.scope == scope)
        statement = statement.order_by(rank.desc(), self.chunks.c.langchain_id).limit(top_k)
        with self.documents.engine.begin() as connection:
            connection.execute(text("SELECT set_config('statement_timeout', '10000', true)"))
            matches = connection.execute(statement).mappings().all()
        results = []
        for row in matches:
            metadata = dict(row["langchain_metadata"] or {})
            document_id, chunk_id = row["document_id"], str(row["langchain_id"])
            results.append({"content": row["content"], "document_id": document_id,
                            "document_keyword": metadata.get("filename", document_id), "page_num": metadata.get("page"),
                            "similarity": float(row["lexical_rank"]), "chunk_id": chunk_id, "metadata": metadata,
                            "source_url": f"/api/v1/documents/{document_id}/source",
                            "reader_url": f"/api/v1/documents/{document_id}/content?chunk_id={chunk_id}"})
        return results

    def content(self, document_id, chunk_id=None):
        row = self.documents.get(document_id)
        if not row:
            return None
        focus = None
        if chunk_id:
            with self.documents.engine.connect() as connection:
                chunk = connection.execute(select(self.chunks).where(
                    self.chunks.c.document_id == document_id, self.chunks.c.langchain_id == uuid.UUID(chunk_id),
                )).mappings().first()
            if not chunk:
                raise LookupError("片段不属于该文档或不存在")
            focus = {"chunk_id": chunk_id, "text": chunk["content"], **(chunk["langchain_metadata"] or {})}
        return {"document": self.documents.public(row), "pages": row["pages"], "focus": focus}

    def readiness(self):
        with self.documents.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            version = connection.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar_one()
            dimension = connection.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = CAST(:table_name AS regclass) AND attname='embedding'"), {"table_name": f"{settings.RAG_DATABASE_SCHEMA}.{settings.RAG_VECTOR_TABLE}"}).scalar_one()
        if dimension != f"vector({settings.EMBEDDING_DIMENSIONS})":
            raise ResourceError("现有向量表与模型维度不同，请配置独立的新向量表并重新索引")
        if settings.RAG_SEARCH_MODE == "hybrid":
            self._require_lexical_ready()
        return {"database": "ok", "pgvector": version, "embedding_column": dimension,
                "search_mode": settings.RAG_SEARCH_MODE,
                "lexical_tokenizer": TOKENIZER_VERSION if settings.RAG_SEARCH_MODE == "hybrid" else None}


@lru_cache(maxsize=1)
def get_postgres_engine():
    return PostgresEngine()
