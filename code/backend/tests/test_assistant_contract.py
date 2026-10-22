"""Consumer-facing V1 guarantees; model calls are intentionally mocked here."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from hbcn_assistant import AssistantClient

from app.routers.assistant import public_openapi
from tests import test_assistant_api as baseline


class ContractTests(unittest.TestCase):
    def setUp(self):
        baseline.AssistantApiTests.setUp(self)

    def tearDown(self):
        baseline.AssistantApiTests.tearDown(self)

    def test_contract_is_authenticated_and_independent_of_runtime_readiness(self):
        path = '/api/assistant/v1/contract'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.operator_headers).status_code, 403)
        info = self.client.get(path, headers=self.reviewer_headers).json()
        self.assertEqual(info['contract_version'], '1.0.0')
        self.assertEqual(info['api_base'], '/api/assistant/v1')
        self.assertEqual(info['authentication'], 'delegated_reviewer_jwt')
        self.assertFalse(info['approval_authority'])

    def test_versioned_and_legacy_routes_share_data_and_authorization(self):
        created = self.client.post('/api/assistant/v1/sessions', headers=self.reviewer_headers,
                                   json={'task_code': 'REVIEWER-ONLY', 'title': 'V1 调用'} )
        self.assertEqual(created.status_code, 201, created.text)
        identifier = created.json()['id']
        old = self.client.get(f'/api/assistant/sessions/{identifier}', headers=self.reviewer_headers)
        new = self.client.get(f'/api/assistant/v1/sessions/{identifier}', headers=self.reviewer_headers)
        self.assertEqual(old.json(), new.json())
        for prefix in ('/api/assistant', '/api/assistant/v1'):
            self.assertEqual(self.client.get(f'{prefix}/sessions/{identifier}', headers=self.operator_headers).status_code, 403)
            self.assertEqual(self.client.post(f'{prefix}/sessions/{identifier}/runs', headers=self.operator_headers,
                                             json={'content': '禁止调用'}).status_code, 403)

    def test_openapi_matches_reviewed_v1_baseline(self):
        baseline = Path(__file__).resolve().parents[3] / 'docs/ai-assistant/contracts/assistant-v1.openapi.json'
        current = public_openapi()
        self.assertEqual(current, json.loads(baseline.read_text(encoding='utf-8')),
                         'Review API compatibility before exporting a new baseline')
        self.assertTrue(all(path.startswith('/api/assistant/v1/') for path in current['paths']))
        self.assertIn('securitySchemes', current['components'])

    def test_installed_sdk_uses_real_v1_auth_run_replay_and_idempotency(self):
        calls = []

        async def model(*args, **kwargs):
            calls.append(1)
            yield {'event': 'assistant_result', 'answer': '请有权限的审核人员确认。', 'citations': []}

        async def invoke():
            jwt = self.reviewer_headers['Authorization'].removeprefix('Bearer ')
            async with AssistantClient('http://business', jwt, transport=httpx.ASGITransport(app=self.client.app)) as sdk:
                self.assertEqual((await sdk.contract())['contract_version'], '1.0.0')
                room = await sdk.create_session('REVIEWER-ONLY')
                payload = {'client_message_id': 'consumer-workflow-001'}
                run = await sdk.start_run(room['id'], '核对依据', **payload)
                answer = await sdk.wait(room['id'], run['id'])
                replayed = await sdk.ask(room['id'], '核对依据', **payload)
                self.assertEqual(answer, replayed)
                self.assertEqual((await sdk.session(room['id']))['active_run'], None)
                self.assertEqual(len(calls), 1)
                with self.assertRaises(httpx.HTTPStatusError) as conflict:
                    await sdk.start_run(room['id'], '改变内容', **payload)
                self.assertEqual(conflict.exception.response.status_code, 409)

        with patch('app.assistant_service.run_agent_events', model):
            asyncio.run(invoke())
