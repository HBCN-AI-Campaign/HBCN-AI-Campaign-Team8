"""Read-only assistant deployment checks: python -m app.assistant_preflight.

Uses the deployment environment, never app.main/startup/create_all. No model
requests, DDL, seeds, user records, secret values or upstream exception output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from . import assistant_models, models  # register assistant and existing metadata
from .assistant_readiness import rag_readiness, runtime_readiness
from .config import settings
from .database import Base


def database_status(connection) -> dict:
    """Inspect schema/constraints, never user or task contents."""
    schema = inspect(connection)
    present = set(schema.get_table_names())
    # Tasks/documents are consumed through the existing ORM, so a missing
    # existing column is a deployment error even though assistants don't own it.
    tables = [table for table in Base.metadata.sorted_tables
              if table.name.startswith('assistant_') or table.name in {
                  models.User.__tablename__, models.ReviewTask.__tablename__,
                  models.Document.__tablename__, models.CheckResult.__tablename__,
              }]
    missing = {}
    for table in tables:
        actual = {column['name'] for column in schema.get_columns(table.name)} if table.name in present else set()
        absent = sorted({column.name for column in table.columns} - actual)
        if absent:
            missing[table.name] = absent
    expected = set(ScriptDirectory(str(Path(__file__).resolve().parents[1] / 'assistant_migrations')).get_heads())
    applied = set(connection.execute(text('SELECT version_num FROM assistant_alembic_version')).scalars()) if 'assistant_alembic_version' in present else set()
    required = {frozenset({'active_session_id'}), frozenset({'session_id', 'user_id', 'client_message_id'})}
    unique = set()
    if 'assistant_runs' in present:
        for item in [*schema.get_unique_constraints('assistant_runs'), *schema.get_indexes('assistant_runs')]:
            if 'unique' not in item or item['unique']:
                unique.add(frozenset(item['column_names']))
    constraints_ok = required <= unique
    return {"ready": not missing and applied == expected and constraints_ok,
            "missing_columns": missing, "migration_current": applied == expected,
            "run_uniqueness": constraints_ok}


def check_database(database_url: str) -> dict:
    engine = None
    try:
        url = make_url(database_url)
        if url.get_backend_name() == 'sqlite':
            # URI read-only mode also prevents creation of a misspelled DB file.
            if not url.database or url.database == ':memory:' or url.query:
                return {"ready": False, "code": "persistent_sqlite_file_required"}
            path = Path(url.database).resolve()
            url = url.set(database=f'file:{path.as_posix()}', query={"mode": "ro", "uri": "true"})
        engine = create_engine(url, echo=False, connect_args={"connect_timeout": 5} if url.get_backend_name() == 'postgresql' else {})
        with engine.connect() as connection:
            if url.get_backend_name() == 'postgresql':
                connection.execute(text('SET TRANSACTION READ ONLY'))
            elif url.get_backend_name() == 'sqlite':
                connection.execute(text('PRAGMA query_only=ON'))
            return database_status(connection)
    except Exception:
        # Driver errors can contain credentials/hostnames; emit only this code.
        return {"ready": False, "code": "database_unavailable_or_incompatible"}
    finally:
        if engine is not None:
            engine.dispose()


async def preflight(*, require_rag: bool = False, transport=None) -> dict:
    database = await asyncio.to_thread(check_database, settings.DATABASE_URL)
    async with httpx.AsyncClient(timeout=httpx.Timeout(6, connect=3), transport=transport, follow_redirects=False) as client:
        runtime = await runtime_readiness(client, settings.ASSISTANT_RUNTIME_URL, settings.ASSISTANT_RUNTIME_TOKEN)
        rag = {"required": require_rag, "ready": False, "code": "not_checked"}
        if require_rag:
            rag.update(await rag_readiness(client, settings.RAG_BASE_URL, settings.RAG_SERVICE_TOKEN))
    return {"ready": database['ready'] and runtime['ready'] and (rag['ready'] or not require_rag),
            "database": database, "runtime": runtime, "rag": rag,
            "model_call_verified": False, "deployment_mode": "single_api_worker"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-rag', action='store_true', help='also require the existing authenticated RAG readiness API')
    args = parser.parse_args()
    report = asyncio.run(preflight(require_rag=args.require_rag))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
