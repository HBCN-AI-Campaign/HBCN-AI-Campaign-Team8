"""Opt-in real PostgreSQL acceptance using one random disposable schema.

Set HBCN_ASSISTANT_TEST_POSTGRES_URL to an authorized scratch PostgreSQL DB.
Run python -m tests.postgres_assistant_acceptance --live-database. Never points
at the configured business DB implicitly; model/runtime are mocked, not HSBC.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import models
from app.assistant_collaboration import admit_run
from app.assistant_models import AssistantRun
from app.assistant_preflight import check_database
from app.assistant_schemas import AssistantChatIn
from app.config import settings
from app.database import get_db
from app.routers.assistant import router
from app.security import create_access_token
from hbcn_assistant.verify import VerificationFailure, verify_site


async def synthetic_model(*args, **kwargs):
    yield {'event': 'assistant_result', 'answer': '本合成任务 USD 100，最终结论必须由有权限的审核人员确认 [E1]。',
           'citations': [{'id': 'E1', 'reference_id': 'E1', 'source_id': 'PG-ACCEPTANCE',
                          'label': '任务', 'source': '任务概要'}]}


def verify_database(database_url: str) -> dict:
    stage = 'configuration'
    admin = scoped = None
    schema = 'assistant_acceptance_' + uuid4().hex
    created = False
    cleanup = True
    checks = []
    version = None
    session_timezone = None
    failed = None
    try:
        url = make_url(database_url)
        if url.get_backend_name() != 'postgresql':
            raise ValueError('PostgreSQL required')
        stage = 'scratch_schema'
        admin = create_engine(url, echo=False, connect_args={'connect_timeout': 5})
        # schema is generated here, never supplied by the caller; all destructive
        # cleanup is confined to this schema. Public/RAG tables are never used.
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            version = connection.execute(text("SELECT current_setting('server_version_num')")).scalar()
        options = dict(url.query)
        # Deliberately exercise a non-UTC deployment, not just a lucky default.
        options['options'] = '-csearch_path=' + schema + ' -c timezone=Asia/Shanghai'
        isolated_url = url.set(query=options)
        scoped = create_engine(isolated_url, echo=False, connect_args={'connect_timeout': 5})
        with scoped.connect() as connection:
            session_timezone = connection.execute(text('SHOW TIME ZONE')).scalar()
        factory = sessionmaker(bind=scoped, expire_on_commit=False)
        business = [models.User.__table__, models.ReviewTask.__table__, models.Document.__table__, models.CheckResult.__table__]
        stage = 'business_fixture'
        for table in business:
            table.create(scoped)
        with factory() as db:
            owner = models.User(username='pg-owner', display_name='合成审核人员', hashed_password='not-a-login', role=models.Role.REVIEWER)
            expert = models.User(username='pg-expert', display_name='合成审核同事', hashed_password='not-a-login', role=models.Role.REVIEWER)
            db.add_all([owner, expert]); db.flush()
            owner_id, expert_id = owner.id, expert.id
            db.add(models.ReviewTask(task_code='PG-ACCEPTANCE', borrower='Synthetic only',
                                    drawdown_currency='USD', drawdown_amount=100, submitted_by=owner_id))
            db.commit()

        def business_schema():
            inspector = inspect(scoped)
            return {table.name: [(row['name'], str(row['type']), row['nullable'], row.get('default'))
                                 for row in inspector.get_columns(table.name)] for table in business}

        before = business_schema()
        stage = 'first_and_repeated_migration'
        config = Config(str(Path(__file__).resolve().parents[1] / 'assistant-alembic.ini'))
        with patch.object(settings, 'DATABASE_URL', isolated_url.render_as_string(hide_password=False)):
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
        assert check_database(isolated_url.render_as_string(hide_password=False))['ready']
        assert business_schema() == before
        with factory() as db:
            task = db.query(models.ReviewTask).one()
            assert task.task_code == 'PG-ACCEPTANCE' and task.drawdown_amount == 100
            assert db.query(models.User).count() == 2
        checks.append('migration_preserves_business_data_and_schema')

        stage = 'concurrent_idempotent_admission'
        with factory() as db:
            room = models.AssistantSession(user_id=owner_id, title='Concurrent synthetic room')
            db.add(room); db.commit(); room_id = room.id

        def admit(_):
            with factory() as db:
                run, created_run = admit_run(db, db.get(models.User, owner_id),
                    db.get(models.AssistantSession, room_id),
                    AssistantChatIn(content='合成并发问题', client_message_id='postgres-concurrent-001'))
                return run.id, created_run

        with ThreadPoolExecutor(max_workers=4) as pool:
            admissions = list(pool.map(admit, range(4)))
        assert len({row[0] for row in admissions}) == 1
        assert sum(row[1] for row in admissions) == 1
        with factory() as db:
            run = db.get(AssistantRun, admissions[0][0])
            assert run.active_session_id == room_id
            assert 250 < (run.expires_at - datetime.now(timezone.utc)).total_seconds() <= 300
            from fastapi import HTTPException
            try:
                admit_run(db, db.get(models.User, owner_id), db.get(models.AssistantSession, room_id),
                          AssistantChatIn(content='另一个问题', client_message_id='postgres-concurrent-002'))
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError('Busy room accepted another run')
            run.status = 'cancelled'; run.active_session_id = None; db.commit()
        checks.append('concurrent_admission_one_run_and_safe_retry')

        stage = 'postgres_collaboration_api'
        app = FastAPI()
        app.include_router(router)
        def database():
            with factory() as db:
                yield db
        app.dependency_overrides[get_db] = database

        async def invoke():
            return await verify_site('http://synthetic-api', create_access_token('pg-owner', 'reviewer'),
                create_access_token('pg-expert', 'reviewer'), 'PG-ACCEPTANCE', expert_id,
                transport=httpx.ASGITransport(app=app))

        with patch('app.routers.assistant.runtime_readiness', return_value={'ready': True, 'model': 'mock', 'code': 'ready'}), patch(
            'app.routers.assistant.rag_readiness', return_value={'ready': False}
        ), patch('app.routers.assistant.sdk_configured', return_value=True), patch(
            'app.assistant_service.run_agent_events', synthetic_model
        ):
            report = asyncio.run(invoke())
        assert report['passed'] and report['cleanup_complete']
        checks.append('two_jwt_history_results_citations_retry_recovery_revocation')
        checks.append('non_utc_session_preserves_utc_results_and_expiry')
    except Exception as exc:
        # Driver failures can include private host/user details. Only emit stage.
        failed = stage + ('.' + exc.stage if isinstance(exc, VerificationFailure) else '')
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            try:
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                with admin.connect() as connection:
                    assert not connection.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:schema'),
                                                  {'schema': schema}).scalar()
            except Exception:
                cleanup = False
        if admin is not None:
            admin.dispose()
    return {'passed': failed is None and cleanup, 'stage': failed or ('complete' if cleanup else 'cleanup'),
            'postgres_version_num': version, 'postgres_session_timezone': session_timezone,
            'checks': checks, 'cleanup_complete': cleanup,
            'cleanup_schema': schema if not cleanup else None,
            'model': 'mock', 'business_transport': 'asgi', 'cloud_verified': False}


def main():
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-database', required=True, action='store_true')
    parser.parse_args()
    report = verify_database(os.environ.get('HBCN_ASSISTANT_TEST_POSTGRES_URL', ''))
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
