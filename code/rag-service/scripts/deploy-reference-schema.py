"""Inspect or explicitly create separate reference-governance tables.

The default only checks readiness. --apply is an operator deployment action;
neither command imports cases, credentials, files, embeddings or model output.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import sql_engine
from app.reference_store import ReferenceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create reference-only tables in the configured existing schema")
    args = parser.parse_args()
    store = ReferenceStore(sql_engine(), schema=settings.RAG_DATABASE_SCHEMA)
    if args.apply:
        store.apply_schema()
    store.require_ready()
    print("Reference governance tables ready; public KB tables and case data unchanged.")


if __name__ == "__main__":
    main()
