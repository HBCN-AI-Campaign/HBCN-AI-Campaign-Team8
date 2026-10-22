"""Versioned jieba + PostgreSQL FTS index, with an explicit resumable backfill.

No embeddings or source files are changed. The chunk FK makes ordinary vector
deletion remove its lexical derivative in the same database transaction.
"""
from __future__ import annotations

import argparse
import logging
import re
import unicodedata
from functools import lru_cache

import jieba
from sqlalchemy import Column, ForeignKey, Index, String, Table, func, literal_column, select
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID, insert

from .database import ResourceError

TOKENIZER_VERSION = "jieba-0.42.1-search-hmm0-nfkc-casefold-v1"
SIMPLE = literal_column("'pg_catalog.simple'::regconfig")


@lru_cache(maxsize=1)
def tokenizer():
    jieba.setLogLevel(logging.WARNING)
    instance = jieba.Tokenizer()
    instance.initialize()
    return instance


def lexical_tokens(content):
    normalized = unicodedata.normalize("NFKC", content).casefold()
    # Strip tsquery syntax and punctuation, without discarding Chinese tokens.
    return [word for part in tokenizer().cut_for_search(normalized, HMM=False)
            for word in re.findall(r"[^\W_]+", part, re.UNICODE)]


def query_expression(query):
    words = list(dict.fromkeys(lexical_tokens(query)))
    if len(words) > 256:
        raise ResourceError("词法查询超过 256 个词，请缩短或拆分问题")
    # OR recall is deliberately broad; fusion/rerank/coverage handle precision.
    return func.websearch_to_tsquery(SIMPLE, " OR ".join(words)) if words else None


def lexical_table(chunks):
    name = chunks.name + "_lexical"
    key = f"{chunks.schema}.{name}" if chunks.schema else name
    if key in chunks.metadata.tables:
        return chunks.metadata.tables[key]
    table = Table(name, chunks.metadata,
                  Column("chunk_id", UUID(as_uuid=True), ForeignKey(chunks.c.langchain_id, ondelete="CASCADE"), primary_key=True),
                  Column("terms", TSVECTOR, nullable=False),
                  Column("tokenizer_version", String(100), nullable=False), schema=chunks.schema)
    # PostgreSQL truncates identifiers at 63 bytes; the validated source name is <=49.
    Index(chunks.name + "_lex_gin", table.c.terms, postgresql_using="gin")
    return table


def index_chunk(connection, table, chunk_id, content):
    statement = insert(table).values(
        chunk_id=chunk_id, terms=func.to_tsvector(SIMPLE, " ".join(lexical_tokens(content))),
        tokenizer_version=TOKENIZER_VERSION,
    )
    connection.execute(statement.on_conflict_do_update(
        index_elements=[table.c.chunk_id],
        set_={"terms": statement.excluded.terms, "tokenizer_version": TOKENIZER_VERSION},
    ))


def pending_chunks(chunks, table):
    return select(chunks.c.langchain_id, chunks.c.content).select_from(chunks.outerjoin(
        table, chunks.c.langchain_id == table.c.chunk_id,
    )).where((table.c.chunk_id.is_(None)) | (table.c.tokenizer_version != TOKENIZER_VERSION))


def backfill(engine, chunks, *, batch_size=200):
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be 1..1000")
    table = lexical_table(chunks)
    table.create(engine, checkfirst=True)
    for index in table.indexes:
        index.create(engine, checkfirst=True)
    count = 0
    while True:
        with engine.begin() as connection:
            # Lock source rows so concurrent re-ingestion/deletion cannot race the FK.
            rows = connection.execute(pending_chunks(chunks, table).order_by(chunks.c.langchain_id)
                                      .limit(batch_size).with_for_update(of=chunks)).all()
            if not rows:
                return count
            for chunk_id, content in rows:
                index_chunk(connection, table, chunk_id, content)
            count += len(rows)


def main():
    parser = argparse.ArgumentParser(description="Create/backfill lexical derivatives; source vectors are unchanged")
    parser.add_argument("--apply", action="store_true", help="Explicitly allow derivative table/index creation and backfill")
    args = parser.parse_args()
    if not args.apply:
        parser.error("use --apply to explicitly run the migration")
    # Construct the existing vector engine in vector mode, never a half-ready hybrid.
    from .config import settings
    from .postgres_engine import PostgresEngine
    settings.RAG_SEARCH_MODE = "vector"
    engine = PostgresEngine()
    count = backfill(engine.documents.engine, engine.chunks)
    print(f"Lexical backfill complete: {count} chunks, tokenizer={TOKENIZER_VERSION}")


if __name__ == "__main__":
    main()
