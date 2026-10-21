import asyncio
import time
import unittest
from unittest.mock import patch

from app import models
from app.assistant_collaboration import admit_run
from app.assistant_models import AssistantAudit, AssistantEvent, AssistantRun
from app.assistant_schemas import AssistantChatIn
from app.security import create_access_token
from tests import test_assistant_api as baseline


class CollaborationTests(unittest.TestCase):
    """Two real JWT principals, real DB/API; only the external model is mocked."""
    def setUp(self):
        baseline.AssistantApiTests.setUp(self)
        with self.session_factory() as db:
            expert = models.User(username="expert-test", display_name="单证同事", hashed_password="unused", role=models.Role.REVIEWER)
            outsider = models.User(username="outsider-test", display_name="未邀请同事", hashed_password="unused", role=models.Role.REVIEWER)
            db.add_all([expert, outsider]); db.commit()
            self.expert_id, self.outsider_id = expert.id, outsider.id
        self.expert_headers = {"Authorization": f"Bearer {create_access_token('expert-test', 'reviewer')}"}
        self.outsider_headers = {"Authorization": f"Bearer {create_access_token('outsider-test', 'reviewer')}"}
        self.room = self.client.post('/api/assistant/sessions', headers=self.reviewer_headers,
                                     json={"title": "协作测试", "task_code": "REVIEWER-ONLY"}).json()['id']
        self.base = f'/api/assistant/sessions/{self.room}'

    def tearDown(self):
        baseline.AssistantApiTests.tearDown(self)

    def invite(self):
        result = self.client.post(self.base + '/members', headers=self.reviewer_headers, json={"user_id": self.expert_id})
        self.assertEqual(result.status_code, 201, result.text)

    def test_shared_room_rechecks_membership_and_revocation(self):
        for suffix in ('', '/members', '/events'):
            self.assertEqual(self.client.get(self.base + suffix, headers=self.expert_headers).status_code, 404)
        self.invite()
        room = self.client.get(self.base, headers=self.expert_headers).json()
        self.assertTrue(room['shared']); self.assertFalse(room['can_manage'])
        self.assertIn(self.room, [row['id'] for row in self.client.get('/api/assistant/sessions', headers=self.expert_headers).json()])
        self.assertEqual(self.client.get(self.base, headers=self.outsider_headers).status_code, 404)
        self.assertEqual(self.client.delete(self.base, headers=self.expert_headers).status_code, 403)
        self.assertEqual(self.client.delete(self.base + f'/members/{self.expert_id}', headers=self.reviewer_headers).status_code, 200)
        for suffix in ('', '/members', '/events'):
            self.assertEqual(self.client.get(self.base + suffix, headers=self.expert_headers).status_code, 404)
        audit = self.client.get(self.base + '/audit', headers=self.reviewer_headers).json()
        self.assertEqual([row['action'] for row in reversed(audit)], ['member_invited', 'member_revoked'])

    def test_experts_use_real_profiles_and_reviewer_permissions(self):
        self.assertEqual(self.client.get('/api/assistant/experts', headers=self.operator_headers).status_code, 403)
        self.client.put('/api/assistant/experts/me', headers=self.expert_headers,
                        json={"specialty": "国际单证", "bio": "核验贸易材料", "tags": ["提单", "贸易融资"]})
        people = self.client.get('/api/assistant/experts', params={"session_id": self.room, "q": "提单"}, headers=self.reviewer_headers).json()
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]['user_id'], self.expert_id)
        self.assertEqual(people[0]['bio'], '核验贸易材料')
        result = self.client.post(self.base + '/members', headers=self.reviewer_headers, json={"user_id": self.operator_id})
        self.assertEqual(result.status_code, 404)

    def test_discussion_keeps_author_and_never_calls_model(self):
        self.invite()
        with patch('app.assistant_service.run_agent_events') as model:
            result = self.client.post(self.base + '/messages', headers=self.expert_headers, json={"content": "请先复核提单收货人", "author_id": self.reviewer_id})
            self.assertEqual(result.status_code, 201, result.text)
            self.assertEqual(result.json()['author_id'], self.expert_id)
            self.assertEqual(result.json()['author_name'], '单证同事')
            model.assert_not_called()
        history = self.client.get(self.base, headers=self.reviewer_headers).json()
        self.assertEqual(history['messages'][0]['author_id'], self.expert_id)
        page = self.client.get(self.base + '/events', headers=self.expert_headers).json()
        self.assertTrue(any(event['event'] == 'discussion' for event in page['events']))
        empty = self.client.get(self.base + '/events', params={"after_id": page['cursor']}, headers=self.expert_headers).json()
        self.assertEqual(empty['events'], [])

    def test_invite_requires_task_and_owner(self):
        private = self.client.post('/api/assistant/sessions', headers=self.reviewer_headers, json={}).json()['id']
        self.assertEqual(self.client.post(f'/api/assistant/sessions/{private}/members', headers=self.reviewer_headers, json={"user_id": self.expert_id}).status_code, 409)
        self.invite()
        self.assertEqual(self.client.post(self.base + '/members', headers=self.expert_headers, json={"user_id": self.outsider_id}).status_code, 403)

    def test_database_admission_is_idempotent_and_one_run_per_room(self):
        with self.session_factory() as db:
            user = db.get(models.User, self.reviewer_id)
            room = db.get(models.AssistantSession, self.room)
            payload = AssistantChatIn(content="核验主体", client_message_id="retry-key-001")
            first, created = admit_run(db, user, room, payload)
            self.assertTrue(created)
            duplicate, created = admit_run(db, user, room, payload)
            self.assertFalse(created); self.assertEqual(first.id, duplicate.id)
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as same_key:
                admit_run(db, user, room, AssistantChatIn(content="不同问题", client_message_id="retry-key-001"))
            self.assertEqual(same_key.exception.status_code, 409)
            with self.assertRaises(HTTPException) as busy:
                admit_run(db, user, room, AssistantChatIn(content="新问题", client_message_id="retry-key-002"))
            self.assertEqual(busy.exception.status_code, 409)

    def test_legacy_stream_owns_database_session_through_response(self):
        # Match production SessionLocal. An admission commit expires ORM state,
        # and FastAPI may close the HTTP dependency before consuming the SSE body.
        self.session_factory.configure(expire_on_commit=True)
        async def final(*args, **kwargs):
            yield {"event": "assistant_result", "answer": "请由有权限的审核人员确认结论。", "citations": []}
        with patch('app.assistant_service.run_agent_events', final):
            response = self.client.post(self.base + '/messages/stream', headers=self.reviewer_headers,
                                        json={"content": "解释关联任务", "task_code": "REVIEWER-ONLY"})
        self.assertIn('event: message_end', response.text)
        history = self.client.get(self.base, headers=self.reviewer_headers).json()
        self.assertEqual([row['role'] for row in history['messages']], ['user', 'assistant'])
        self.assertIsNone(history['active_run'])

    def test_background_run_is_shared_and_retry_does_not_call_model_twice(self):
        self.invite()
        calls = []
        async def fake_events(*args, **kwargs):
            calls.append(args)
            yield {"event": "step", "step": {"key": "review", "label": "核对授权材料", "status": "running"}}
            await asyncio.sleep(.05)
            yield {"event": "assistant_result", "answer": "请审核人员确认主体依据。", "citations": []}
        with self.client, patch('app.assistant_service.run_agent_events', fake_events):
            payload = {"content": "核验主体", "client_message_id": "client-retry-001"}
            response = self.client.post(self.base + '/runs', headers=self.expert_headers, json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            run_id = response.json()['id']
            for _ in range(40):
                page = self.client.get(self.base + '/events', headers=self.reviewer_headers).json()
                if any(event['event'] == 'run_end' for event in page['events']): break
                time.sleep(.02)
            self.assertTrue(any(event['event'] == 'message_end' for event in page['events']), page)
            self.assertEqual(self.client.post(self.base + '/runs', headers=self.expert_headers, json=payload).json()['id'], run_id)
            self.assertEqual(len(calls), 1)
            room = self.client.get(self.base, headers=self.expert_headers).json()
            self.assertEqual(room['messages'][0]['author_id'], self.expert_id)
            self.assertEqual(room['messages'][-1]['author_name'], '慧眼助手')
            self.assertIsNone(room['active_run'])

    def test_cancelled_run_cannot_commit_a_completed_answer(self):
        async def cancelled_before_final(*args, **kwargs):
            with self.session_factory() as db:
                run = db.query(AssistantRun).filter_by(active_session_id=self.room).one()
                run.status = 'cancelled'
                db.commit()
            yield {"event": "assistant_result", "answer": "请由有权限的审核人员确认结论。", "citations": []}
        with patch('app.assistant_service.run_agent_events', cancelled_before_final):
            response = self.client.post(self.base + '/messages/stream', headers=self.reviewer_headers,
                                        json={"content": "取消同时模型返回"})
        self.assertNotIn('event: message_end', response.text)
        history = self.client.get(self.base, headers=self.reviewer_headers).json()
        self.assertEqual([row['role'] for row in history['messages']], ['user'])
        self.assertIsNone(history['active_run'])

    def test_inactive_invited_user_loses_access(self):
        self.invite()
        with self.session_factory() as db:
            user = db.get(models.User, self.expert_id); user.is_active = False; db.commit()
        self.assertEqual(self.client.get(self.base, headers=self.expert_headers).status_code, 401)

    def test_shared_room_cannot_switch_task_or_use_legacy_stream(self):
        self.invite()
        self.assertEqual(self.client.post(self.base + '/runs', headers=self.expert_headers,
            json={"content": "test", "task_code": "OTHER-TASK"}).status_code, 409)
        self.assertEqual(self.client.post(self.base + '/messages/stream', headers=self.expert_headers,
            json={"content": "test"}).status_code, 409)

    def test_run_cancellation_and_busy_requests_are_authorized(self):
        self.invite()
        async def waiting(*args, **kwargs):
            yield {"event": "step", "step": {"key": "wait", "label": "正在查询模型", "status": "running"}}
            await asyncio.sleep(30)
        with self.client, patch('app.assistant_service.run_agent_events', waiting):
            result = self.client.post(self.base + '/runs', headers=self.expert_headers, json={"content": "核对材料"})
            run_id = result.json()['id']
            self.assertEqual(self.client.post(self.base + '/runs', headers=self.reviewer_headers, json={"content": "并发问题"}).status_code, 409)
            self.assertEqual(self.client.post(self.base + f'/runs/{run_id}/cancel', headers=self.outsider_headers).status_code, 404)
            self.assertEqual(self.client.post(self.base + f'/runs/{run_id}/cancel', headers=self.reviewer_headers).status_code, 200)
            for _ in range(30):
                page = self.client.get(self.base + '/events', headers=self.expert_headers).json()
                if not page['active_run']: break
                time.sleep(.02)
            self.assertIsNone(page['active_run'])
            self.assertTrue(any(event['event'] == 'run_end' and event['status'] == 'cancelled' for event in page['events']))

    def test_task_deleted_after_invitation_blocks_history(self):
        self.invite()
        with self.session_factory() as db:
            task = db.query(models.ReviewTask).filter_by(task_code='REVIEWER-ONLY').one()
            db.delete(task); db.commit()
        for headers in (self.expert_headers, self.reviewer_headers):
            self.assertEqual(self.client.get(self.base, headers=headers).status_code, 404)

    def test_revoking_active_initiator_stops_run_and_releases_room(self):
        self.invite()
        async def waiting(*args, **kwargs):
            yield {"event": "step", "step": {"key": "wait", "label": "查询模型", "status": "running"}}
            await asyncio.sleep(30)
        with self.client, patch('app.assistant_service.run_agent_events', waiting):
            run = self.client.post(self.base + '/runs', headers=self.expert_headers,
                                   json={"content": "核验合同"}).json()
            self.assertEqual(self.client.delete(self.base + f'/members/{self.expert_id}',
                                              headers=self.reviewer_headers).status_code, 200)
            for _ in range(30):
                page = self.client.get(self.base + '/events', headers=self.reviewer_headers).json()
                if page['active_run'] is None: break
                time.sleep(.02)
            self.assertIsNone(page['active_run'])
            self.assertTrue(any(event['event'] == 'run_end' and event['run_id'] == run['id']
                                and event['status'] == 'cancelled' for event in page['events']))
            self.assertEqual(self.client.get(self.base + '/events', headers=self.expert_headers).status_code, 404)

    def test_downgraded_owner_cannot_list_or_read_shared_history(self):
        self.invite()
        with self.session_factory() as db:
            owner = db.get(models.User, self.reviewer_id)
            owner.role = models.Role.OPERATOR
            db.commit()
        self.assertEqual(self.client.get(self.base, headers=self.reviewer_headers).status_code, 404)
        listed = self.client.get('/api/assistant/sessions', headers=self.reviewer_headers).json()
        self.assertNotIn(self.room, [row['id'] for row in listed])

    def test_legacy_rows_have_owner_attribution_and_shared_delete_cleans_tables(self):
        with self.session_factory() as db:
            db.add(models.AssistantMessage(session_id=self.room, role='user', content='旧消息')); db.commit()
        self.invite()
        room = self.client.get(self.base, headers=self.expert_headers).json()
        self.assertEqual(room['messages'][0]['author_id'], self.reviewer_id)
        self.assertEqual(self.client.delete(self.base, headers=self.reviewer_headers).status_code, 200)
        with self.session_factory() as db:
            self.assertEqual(db.query(AssistantEvent).filter_by(session_id=self.room).count(), 0)
            self.assertEqual(db.query(AssistantAudit).filter_by(session_id=self.room).count(), 0)

    def test_expired_run_releases_database_lock_without_rerunning_model(self):
        from datetime import datetime, timedelta, timezone
        with self.session_factory() as db:
            run, _ = admit_run(db, db.get(models.User, self.reviewer_id), db.get(models.AssistantSession, self.room),
                               AssistantChatIn(content='过期运行'))
            run.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
        with patch('app.assistant_service.run_agent_events') as model:
            page = self.client.get(self.base + '/events', headers=self.reviewer_headers).json()
            self.assertIsNone(page['active_run'])
            self.assertIn('run_end', [event['event'] for event in page['events']])
            model.assert_not_called()

    def test_skill_library_is_per_user_and_cannot_install_arbitrary_urls(self):
        catalog = self.client.get('/api/assistant/skill-library', headers=self.reviewer_headers).json()
        self.assertGreater(len(catalog), 0)
        skill_id = catalog[0]['id']
        self.assertFalse(catalog[0]['installed'])
        self.assertNotIn('instructions', catalog[0])
        self.assertEqual(self.client.put('/api/assistant/skill-library/' + skill_id, headers=self.reviewer_headers).status_code, 200)
        mine = self.client.get('/api/assistant/skill-library', headers=self.reviewer_headers).json()
        other = self.client.get('/api/assistant/skill-library', headers=self.expert_headers).json()
        self.assertTrue(next(item for item in mine if item['id'] == skill_id)['installed'])
        self.assertFalse(next(item for item in other if item['id'] == skill_id)['installed'])
        self.assertEqual(self.client.put('/api/assistant/skill-library/not-approved', headers=self.reviewer_headers).status_code, 404)

    def test_workflow_client_uses_delegated_business_auth_and_resumes_same_run(self):
        import httpx
        from app.assistant_client import AssistantClient
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == 'POST':
                return httpx.Response(202, json={"id": "run-contract"})
            return httpx.Response(200, json={"cursor": 4, "has_more": False, "events": [
                {"id": 4, "event": "message_end", "message": {"role": "assistant", "content": "需人工确认"}}
            ]})
        async def call():
            async with AssistantClient('http://business-api', 'delegated-jwt', transport=httpx.MockTransport(handler)) as sdk:
                return await sdk.ask(self.room, '核验材料', client_message_id='workflow-request-001')
        result = asyncio.run(call())
        self.assertEqual(result['content'], '需人工确认')
        self.assertTrue(all(request.headers['Authorization'] == 'Bearer delegated-jwt' for request in requests))
        self.assertTrue(all(request.url.path.startswith('/api/assistant/') for request in requests))
