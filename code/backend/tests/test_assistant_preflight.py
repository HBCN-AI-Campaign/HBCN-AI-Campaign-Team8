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
from app.assistant_readiness import ASSISTANT_PROTOCOL, rag_readiness, runtime_readiness
from app.config import settings
from app import models
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

    def test_first_install_on_business_only_database_creates_all_assistant_tables_without_startup(self):
        Base.metadata.drop_all(self.engine)
        business = [models.User.__table__, models.ReviewTask.__table__, models.Document.__table__, models.CheckResult.__table__]
        for table in business:
            table.create(self.engine)
        def business_schema():
            return {table.name: [(col['name'], str(col['type']), col['nullable'], col.get('default'), col.get('primary_key'))
                                 for col in inspect(self.engine).get_columns(table.name)] for table in business}
        before = business_schema()
        with self.engine.begin() as connection:
            connection.execute(models.User.__table__.insert().values(
                username='migration-sentinel', display_name='Synthetic', hashed_password='not-a-login', role=models.Role.REVIEWER))
        self.assertFalse(any(name.startswith('assistant_') for name in inspect(self.engine).get_table_names()))
        self.migrate()
        self.migrate()
        self.assertTrue(check_database(self.url)['ready'])
        self.assertEqual(before, business_schema())
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT username FROM users')).scalar(), 'migration-sentinel')

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
            headers = {'X-RAG-Contract-Version': '1.2.0'} if request.url.path == '/api/v1/ready' else {}
            return httpx.Response(200, json={'status': 'ready', 'configured': True, 'model': 'test-model', 'assistant_protocol': ASSISTANT_PROTOCOL}, headers=headers)
        with patch.object(settings, 'DATABASE_URL', self.url), patch.object(settings, 'ASSISTANT_RUNTIME_URL', 'http://runtime'), patch.object(
            settings, 'ASSISTANT_RUNTIME_TOKEN', 'private-runtime-token'
        ), patch.object(settings, 'RAG_BASE_URL', 'http://rag'), patch.object(settings, 'RAG_SERVICE_TOKEN', 'private-rag-token'):
            report = asyncio.run(preflight(require_rag=True, transport=httpx.MockTransport(handler)))
        self.assertTrue(report['ready'])
        self.assertFalse(report['model_call_verified'])
        self.assertEqual(requests, [('GET', '/readyz', 'Bearer private-runtime-token'), ('GET', '/api/v1/ready', 'Bearer private-rag-token')])
        self.assertNotIn('private-', json.dumps(report))

    def test_production_mode_rejects_default_jwt_and_debug_but_development_mode_reports_without_blocking(self):
        self.migrate()
        def handler(request):
            return httpx.Response(200, json={'status': 'ready', 'configured': True,
                                             'model': 'test-model', 'assistant_protocol': ASSISTANT_PROTOCOL})
        common = {
            'DATABASE_URL': self.url, 'ASSISTANT_RUNTIME_URL': 'http://runtime',
            'ASSISTANT_RUNTIME_TOKEN': 'runtime-token',
        }
        with patch.multiple(settings, **common), patch.object(settings, 'JWT_SECRET', 'change-me-in-production-please'), patch.object(settings, 'DEBUG', True):
            development = asyncio.run(preflight(transport=httpx.MockTransport(handler)))
            production = asyncio.run(preflight(require_production=True, transport=httpx.MockTransport(handler)))
        self.assertTrue(development['ready'])
        self.assertFalse(development['security']['production_ready'])
        self.assertFalse(production['ready'])
        self.assertEqual(production['security']['issues'], ['jwt_secret_weak_or_default', 'debug_enabled'])
        self.assertNotIn('change-me-in-production-please', json.dumps(production))

    def test_production_mode_accepts_strong_jwt_when_debug_is_disabled(self):
        self.migrate()
        def handler(request):
            return httpx.Response(200, json={'status': 'ready', 'configured': True,
                                             'model': 'test-model', 'assistant_protocol': ASSISTANT_PROTOCOL})
        with patch.object(settings, 'DATABASE_URL', self.url), patch.object(settings, 'ASSISTANT_RUNTIME_URL', 'http://runtime'), patch.object(
            settings, 'ASSISTANT_RUNTIME_TOKEN', 'runtime-token'
        ), patch.object(settings, 'JWT_SECRET', 'a-secure-random-secret-with-at-least-32-characters'), patch.object(settings, 'DEBUG', False):
            report = asyncio.run(preflight(require_production=True, transport=httpx.MockTransport(handler)))
        self.assertTrue(report['ready'])
        self.assertEqual(report['security'], {'required': True, 'production_ready': True, 'issues': []})

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


class AssistantRuntimeReadinessTests(unittest.TestCase):
    def test_old_missing_and_invalid_protocols_cannot_claim_ready(self):
        async def probe(protocol):
            def handler(request):
                payload = {'status': 'ready', 'configured': True, 'model': 'private-model'}
                if protocol is not None:
                    payload['assistant_protocol'] = protocol
                return httpx.Response(200, json=payload)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await runtime_readiness(client, 'http://runtime', 'private-token')
        for protocol in (None, 1, 3, True, '2', 2.0):
            with self.subTest(protocol=protocol):
                self.assertEqual(asyncio.run(probe(protocol)), {'ready': False, 'code': 'protocol_mismatch', 'model': None})
        self.assertTrue(asyncio.run(probe(ASSISTANT_PROTOCOL))['ready'])

    def test_missing_endpoint_and_invalid_body_have_redacted_diagnostics(self):
        async def probe(status, body):
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text=body)
            )) as client:
                return await runtime_readiness(client, 'http://private-endpoint', 'private-token')
        for status, body, code in ((404, 'private upstream detail', 'contract_missing'),
                                   (405, '', 'contract_missing'), (200, 'private invalid body', 'unreachable_or_invalid')):
            with self.subTest(status=status):
                report = asyncio.run(probe(status, body))
                self.assertFalse(report['ready'])
                self.assertEqual(report['code'], code)
                self.assertNotIn('private', json.dumps(report))


class AssistantRagReadinessTests(unittest.TestCase):
    def probe(self, version, *, status=200, readiness='ready'):
        headers = {'X-RAG-Contract-Version': version} if version is not None else {}
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(status, json={'status': readiness}, headers=headers)
            )) as client:
                return await rag_readiness(client, 'http://rag', 'rag-token')
        return asyncio.run(run())

    def test_requires_supported_v1_2_contract_and_accepts_compatible_v1_updates(self):
        for version in (None, '', 'invalid', '1.1.9', '2.0.0'):
            with self.subTest(version=version):
                report = self.probe(version)
                self.assertFalse(report['ready'])
                self.assertEqual(report['code'], 'contract_missing' if version in (None, '', 'invalid') else 'contract_mismatch')
        for version in ('1.2.0', '1.2.5', '1.3.0', '1.3.2', '1.3.3'):
            with self.subTest(version=version):
                report = self.probe(version)
                self.assertTrue(report['ready'])
                self.assertEqual(report['contract_version'], version)

    def test_compatible_but_degraded_rag_is_not_ready(self):
        report = self.probe('1.2.0', status=503, readiness='degraded')
        self.assertFalse(report['ready'])
        self.assertEqual(report['code'], 'not_ready')
