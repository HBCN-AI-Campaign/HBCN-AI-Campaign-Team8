"""Validate a disposable local PostgreSQL target without printing its DSN."""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings


ALLOWED_DATABASE = "hbcn_rag_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validated_test_url(raw_url: str):
    if not raw_url:
        raise ValueError("RAG_DATABASE_URL is required")
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("RAG_DATABASE_URL is invalid; connection details suppressed") from None
    if url.get_backend_name() != "postgresql":
        raise ValueError("the integration target must be PostgreSQL")
    if url.host not in LOCAL_HOSTS:
        raise ValueError("the integration target must be loopback; shared/remote databases are refused")
    if url.database != ALLOWED_DATABASE:
        raise ValueError(f"the database name must be exactly {ALLOWED_DATABASE}")
    if url.query.get("sslmode") != "disable":
        raise ValueError("the disposable loopback test target must explicitly use sslmode=disable")
    return url


def main():
    try:
        url = validated_test_url(settings.RAG_DATABASE_URL.get_secret_value())
    except Exception as error:
        print(f"FAIL: isolated PostgreSQL configuration: {error}", file=sys.stderr)
        return 1

    try:
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        try:
            with engine.connect() as connection:
                version_num = int(connection.execute(text("SHOW server_version_num")).scalar_one())
                can_create_schema = connection.execute(
                    text("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")
                ).scalar_one()
            if version_num < 160000:
                raise ValueError("PostgreSQL 16 or later is required")
            if not can_create_schema:
                raise ValueError("the test role needs CREATE privilege on the disposable database")
        finally:
            engine.dispose()
    except Exception:
        print("FAIL: isolated PostgreSQL connection, version, or privilege check; DSN and provider details suppressed", file=sys.stderr)
        return 1
    print("PASS: local disposable PostgreSQL target, version 16+, CREATE privilege; DSN not displayed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
