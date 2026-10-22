"""Consumer-facing V1 guarantees; model calls are intentionally mocked here."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from hbcn_assistant import AssistantClient

from app import models
from app.assistant_models import AssistantRun, AssistantMessageAuthor
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
        self.assertEqual(info['contract_version'], '1.1.0')
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
                self.assertEqual((await sdk.contract())['contract_version'], '1.1.0')
                room = await sdk.create_session('REVIEWER-ONLY')
                payload = {'client_message_id': 'consumer-workflow-001'}
                run = await sdk.start_run(room['id'], '核对依据', **payload)
                answer = await sdk.wait(room['id'], run['id'])
                replayed = await sdk.ask(room['id'], '核对依据', **payload)
                self.assertEqual(answer, replayed)
                snapshot = await sdk.run(room['id'], run['id'])
                self.assertEqual(snapshot['status'], 'completed')
                self.assertEqual(snapshot['message'], answer)
                # The consumer has already consumed all events and only kept
                # the cursor. A restart must fetch the saved final answer.
                page = await sdk.events(room['id'], run_id=run['id'])
                recovered = await sdk.wait(room['id'], run['id'], after_id=page['cursor'])
                self.assertEqual(recovered, answer)
                self.assertEqual((await sdk.session(room['id']))['active_run'], None)
                self.assertEqual(len(calls), 1)
                with self.assertRaises(httpx.HTTPStatusError) as conflict:
                    await sdk.start_run(room['id'], '改变内容', **payload)
                self.assertEqual(conflict.exception.response.status_code, 409)

        with patch('app.assistant_service.run_agent_events', model):
            asyncio.run(invoke())

    def test_run_result_never_exposes_incomplete_or_cancelled_message(self):
        room = self.client.post('/api/assistant/v1/sessions', headers=self.reviewer_headers,
                                json={'title': '结果查询'}).json()
        base = f"/api/assistant/v1/sessions/{room['id']}/runs"
        with patch('app.routers.assistant_collaboration.launch_run') as model:
            started = self.client.post(base, headers=self.reviewer_headers,
                                       json={'content': '核对', 'client_message_id': 'result-test-001'}).json()
            path = base + '/' + started['id']
            with self.session_factory() as db:
                stored = models.AssistantMessage(session_id=room['id'], role='assistant',
                                                  content='不得提前公开的答复', status='completed')
                db.add(stored); db.flush()
                db.add(AssistantMessageAuthor(message_id=stored.id, run_id=started['id'], display_name='慧眼助手'))
                db.commit()
            for status in ('running', 'error', 'cancelled'):
                with self.session_factory() as db:
                    run = db.get(AssistantRun, started['id'])
                    run.status = status
                    db.commit()
                response = self.client.get(path, headers=self.reviewer_headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], status)
                self.assertIsNone(response.json()['message'])
                self.assertNotIn('不得提前公开', response.text)
            # Status reads must never try to launch or retry the model.
            self.assertEqual(model.call_count, 1)  # admission only

    def test_run_result_is_bound_to_room_and_rechecks_membership(self):
        from app.security import create_access_token
        from app.assistant_models import AssistantMember
        room = self.client.post('/api/assistant/v1/sessions', headers=self.reviewer_headers,
                                json={'task_code': 'REVIEWER-ONLY'}).json()
        other = self.client.post('/api/assistant/v1/sessions', headers=self.reviewer_headers, json={}).json()
        with self.session_factory() as db:
            expert = models.User(username='result-expert', display_name='结果查询同事',
                                 hashed_password='unused', role=models.Role.REVIEWER)
            db.add(expert); db.flush()
            expert_id = expert.id
            db.add(AssistantMember(session_id=room['id'], user_id=expert_id, invited_by=self.reviewer_id))
            db.commit()
        expert_headers = {'Authorization': 'Bearer ' + create_access_token('result-expert', 'reviewer')}
        with patch('app.routers.assistant_collaboration.launch_run'):
            run = self.client.post(f"/api/assistant/v1/sessions/{room['id']}/runs", headers=self.reviewer_headers,
                                   json={'content': '核对'}).json()
        path = f"/api/assistant/v1/sessions/{room['id']}/runs/{run['id']}"
        self.assertEqual(self.client.get(path, headers=expert_headers).status_code, 200)
        self.assertEqual(self.client.get(path, headers=self.operator_headers).status_code, 403)
        wrong = f"/api/assistant/v1/sessions/{other['id']}/runs/{run['id']}"
        self.assertEqual(self.client.get(wrong, headers=self.reviewer_headers).status_code, 404)
        self.assertEqual(self.client.get(path + '-missing', headers=self.reviewer_headers).status_code, 404)
        self.client.delete(f"/api/assistant/v1/sessions/{room['id']}/members/{expert_id}", headers=self.reviewer_headers)
        self.assertEqual(self.client.get(path, headers=expert_headers).status_code, 404)
