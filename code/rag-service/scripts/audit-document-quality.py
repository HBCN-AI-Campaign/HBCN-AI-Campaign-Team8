"""Read-only quality inventory of an existing schema; no DDL or model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import MetaData, Table, func, select, text
from app.config import settings
from app.database import sql_engine
from app.document_quality import POLICY_VERSION
from app.postgres_engine import quality_predicate


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        engine = sql_engine()
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '10000'"))
            documents = Table("documents", MetaData(), schema=settings.RAG_DATABASE_SCHEMA, autoload_with=connection)
            rows = connection.execute(select(documents.c.state, func.count()).group_by(documents.c.state)).all()
            missing = connection.execute(select(func.count()).select_from(documents).where(documents.c.state == "ready",
                documents.c.embedding_model == settings.EMBEDDING_MODEL, func.coalesce(quality_predicate(documents), False).is_(False))).scalar_one()
        print(json.dumps({"policy_version": POLICY_VERSION, "states": dict(rows), "unverified_ready_documents": missing,
            "action": "quality-recheck and credentialed review required before accepting these legacy sources",
            "read_only": True}, ensure_ascii=False, indent=2))
    except Exception:
        print("Quality inventory failed; inspect schema/connectivity. No DDL or document writes performed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
