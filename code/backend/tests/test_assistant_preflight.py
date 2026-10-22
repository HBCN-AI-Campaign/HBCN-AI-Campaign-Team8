import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.assistant_preflight import check_database, preflight
from app.config import settings
from app.database import Base


class AssistantPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='assistant-preflight-')
        self.path = Path(self.temp.name) / 'existing.db'
        self.url = 'sqlite:///' + self.path.as_posix()
        self.engine = create_engine(self.url)
        # Same starting point as a create_all legacy deployment. Migration must
        # be stamped explicitly, not inferred merely from tables existing.
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def migrate(self):
        config = Config(str(Path(__file__).resolve().parents[1] / 'assistant-alembic.ini'))
        with patch.object(settings, 'DATABASE_URL', self.url):
            command.upgrade(config, 'head')

    def test_requires_explicit_current_migration_and_never_applies_it(self):
        before = set(inspect(self.engine).get_table_names())
        report = check_database(self.url)
        self.assertFalse(report['ready'])
        self.assertFalse(report['migration_current'])
        self.assertEqual(before, set(inspect(self.engine).get_table_names()))
        self.migrate()
        self.assertEqual(check_database(self.url), {
            'ready': True, 'missing_columns': {}, 'migration_current': True, 'run_uniqueness': True,
        })

    def test_misspelled_sqlite_path_does_not_create_an_empty_database(self):
        absent = self.path.with_name('does-not-exist.db')
        report = check_database('sqlite:///' + absent.as_posix())
        self.assertFalse(report['ready'])
        self.assertFalse(absent.exists())
        self.assertNotIn(str(absent), json.dumps(report))

    def test_existing_migration_stamp_cannot_hide_missing_run_constraints(self):
        self.migrate()
        with self.engine.begin() as conn:
            conn.execute(text('ALTER TABLE assistant_runs RENAME TO broken_runs'))
            conn.execute(text('CREATE TABLE assistant_runs AS SELECT * FROM broken_runs WHERE 0'))
        report = check_database(self.url)
        self.assertTrue(report['migration_current'])
        self.assertEqual(report['missing_columns'], {})
        self.assertFalse(report['run_uniqueness'])
        self.assertFalse(report['ready'])

    def test_legacy_business_column_gap_is_reported_without_altering_schema(self):
        self.migrate()
        with self.engine.begin() as conn:
            conn.execute(text('ALTER TABLE review_tasks DROP COLUMN supplement_note'))
        report = check_database(self.url)
        self.assertFalse(report['ready'])
        self.assertEqual(report['missing_columns']['review_tasks'], ['supplement_note'])
        self.assertNotIn('supplement_note', {col['name'] for col in inspect(self.engine).get_columns('review_tasks')})

    def test_probe_checks_internal_auth_and_optional_rag_without_model_calls_or_secrets(self):
        self.migrate()
        requests = []
        def handler(request):
            requests.append((request.method, request.url.path, request.headers.get('Authorization')))
            return httpx.Response(200, json={'status': 'ready', 'configured': True, 'model': 'test-model'})
        with patch.object(settings, 'DATABASE_URL', self.url), patch.object(settings, 'ASSISTANT_RUNTIME_URL', 'http://runtime'), patch.object(
            settings, 'ASSISTANT_RUNTIME_TOKEN', 'private-runtime-token'
        ), patch.object(settings, 'RAG_BASE_URL', 'http://rag'), patch.object(settings, 'RAG_SERVICE_TOKEN', 'private-rag-token'):
            report = asyncio.run(preflight(require_rag=True, transport=httpx.MockTransport(handler)))
        self.assertTrue(report['ready'])
        self.assertFalse(report['model_call_verified'])
        self.assertEqual(requests, [('GET', '/readyz', 'Bearer private-runtime-token'), ('GET', '/api/v1/ready', 'Bearer private-rag-token')])
        self.assertNotIn('private-', json.dumps(report))

    def test_failed_dependency_is_redacted_and_does_not_claim_ready(self):
        self.migrate()
        def handler(request):
            raise httpx.ConnectError('password=private-secret endpoint=http://private-host', request=request)
        with patch.object(settings, 'DATABASE_URL', self.url), patch.object(settings, 'ASSISTANT_RUNTIME_URL', 'http://runtime'), patch.object(
            settings, 'ASSISTANT_RUNTIME_TOKEN', 'private-runtime-token'
        ):
            report = asyncio.run(preflight(transport=httpx.MockTransport(handler)))
        self.assertFalse(report['ready'])
        self.assertNotIn('private-', json.dumps(report))
        self.assertNotIn(str(self.path), json.dumps(report))
