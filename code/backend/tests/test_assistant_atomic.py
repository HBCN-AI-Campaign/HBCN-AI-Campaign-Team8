"""Final-answer failure injection against real SQLAlchemy transactions/API routes."""
import time
import unittest
from unittest.mock import patch

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app import models
from app.assistant_collaboration import public_event
from app.assistant_models import AssistantEvent, AssistantMessageAuthor, AssistantRun
from tests import test_assistant_api as baseline


async def final_answer(*args, **kwargs):
    yield {'event': 'assistant_result', 'answer': '最终结论必须由有权限的审核人员确认。', 'citations': []}


class AtomicCompletionTests(unittest.TestCase):
    def setUp(self):
        baseline.AssistantApiTests.setUp(self)
        self.session_factory.configure(expire_on_commit=True)

    def tearDown(self):
        baseline.AssistantApiTests.tearDown(self)

    def room(self):
        response = self.client.post('/api/assistant/v1/sessions', headers=self.reviewer_headers,
                                    json={'task_code': 'REVIEWER-ONLY'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def invoke(self, room_id, legacy):
        base = f'/api/assistant/v1/sessions/{room_id}'
        if legacy:
            response = self.client.post(base + '/messages/stream', headers=self.reviewer_headers,
                                        json={'content': '核对授权材料'})
            self.assertEqual(response.status_code, 200)
            with self.session_factory() as db:
                return db.query(AssistantRun).filter_by(session_id=room_id).one().id
        response = self.client.post(base + '/runs', headers=self.reviewer_headers,
                                    json={'content': '核对授权材料', 'client_message_id': 'atomic-request-001'})
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()['id']
        for _ in range(100):
            snapshot = self.client.get(base + '/runs/' + run_id, headers=self.reviewer_headers)
            self.assertEqual(snapshot.status_code, 200, snapshot.text)
            if snapshot.json()['status'] != 'running':
                return run_id
            time.sleep(.01)
        self.fail('Background run did not terminate')

    def test_each_committed_answer_has_terminal_run_author_and_both_events(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), self.client:
                room_id = self.room()
                observed = []

                def inspect_commit(db):
                    if db.get_bind() is not self.engine:
                        return
                    connection = db.connection()
                    answers = connection.execute(select(models.AssistantMessage.id).where(
                        models.AssistantMessage.session_id == room_id,
                        models.AssistantMessage.role == 'assistant',
                    )).scalars().all()
                    if not answers:
                        return
                    run = connection.execute(select(AssistantRun.status, AssistantRun.active_session_id).where(
                        AssistantRun.session_id == room_id,
                    )).one()
                    events = connection.execute(select(AssistantEvent.payload).where(
                        AssistantEvent.session_id == room_id,
                    )).scalars().all()
                    authors = connection.execute(select(AssistantMessageAuthor.message_id).where(
                        AssistantMessageAuthor.message_id.in_(answers),
                    )).scalars().all()
                    observed.append((run.status, run.active_session_id, len(authors),
                                     [item['event'] for item in events][-2:]))

                event.listen(Session, 'before_commit', inspect_commit)
                try:
                    with patch('app.assistant_service.run_agent_events', final_answer):
                        run_id = self.invoke(room_id, legacy)
                finally:
                    event.remove(Session, 'before_commit', inspect_commit)
                self.assertTrue(observed)
                self.assertTrue(all(row == ('completed', None, 1, ['message_end', 'run_end']) for row in observed), observed)
                with self.session_factory() as db:
                    self.assertEqual(db.get(AssistantRun, run_id).status, 'completed')
                    completions = [row.payload for row in db.query(AssistantEvent).filter_by(run_id=run_id)
                                   if row.payload['event'] == 'run_end']
                    self.assertEqual(completions, [{'event': 'run_end', 'status': 'completed'}])

    def test_final_event_failures_roll_back_answer_and_release_slot(self):
        for legacy in (False, True):
            for failed_event in ('message_end', 'run_end'):
                with self.subTest(legacy=legacy, failed_event=failed_event), self.client:
                    room_id = self.room()

                    def fail_completion(db, session_id, payload, run_id=None):
                        if payload['event'] == failed_event and (
                            failed_event == 'message_end' or payload.get('status') == 'completed'
                        ):
                            raise RuntimeError('injected completion event failure')
                        return public_event(db, session_id, payload, run_id)

                    with patch('app.assistant_service.run_agent_events', final_answer), patch(
                        'app.assistant_collaboration.public_event', side_effect=fail_completion
                    ):
                        run_id = self.invoke(room_id, legacy)
                    with self.session_factory() as db:
                        run = db.get(AssistantRun, run_id)
                        self.assertEqual(run.status, 'error')
                        self.assertIsNone(run.active_session_id)
                        self.assertEqual(db.query(models.AssistantMessage).filter_by(
                            session_id=room_id, role='assistant').count(), 0)
                        self.assertEqual(db.query(models.AssistantMessage).filter_by(
                            session_id=room_id, role='user').count(), 1)
                        payloads = [row.payload for row in db.query(AssistantEvent).filter_by(run_id=run_id)]
                        self.assertFalse(any(row['event'] == 'message_end' for row in payloads))
                        self.assertEqual([row for row in payloads if row['event'] == 'run_end'],
                                         [{'event': 'run_end', 'status': 'error'}])

    def test_completion_commit_failure_cannot_leave_saved_success(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), self.client:
                room_id = self.room()
                failures = []

                def reject_completion_commit(db):
                    if db.get_bind() is not self.engine or failures:
                        return
                    completed = db.connection().execute(select(AssistantRun.id).where(
                        AssistantRun.session_id == room_id, AssistantRun.status == 'completed',
                    )).scalar()
                    if completed:
                        failures.append(completed)
                        raise RuntimeError('injected final transaction commit failure')

                event.listen(Session, 'before_commit', reject_completion_commit)
                try:
                    with patch('app.assistant_service.run_agent_events', final_answer):
                        run_id = self.invoke(room_id, legacy)
                finally:
                    event.remove(Session, 'before_commit', reject_completion_commit)
                self.assertEqual(failures, [run_id])
                snapshot = self.client.get(f'/api/assistant/v1/sessions/{room_id}/runs/{run_id}',
                                           headers=self.reviewer_headers).json()
                self.assertEqual(snapshot['status'], 'error')
                self.assertIsNone(snapshot['message'])
                with self.session_factory() as db:
                    self.assertIsNone(db.get(AssistantRun, run_id).active_session_id)
                    self.assertEqual(db.query(models.AssistantMessage).filter_by(
                        session_id=room_id, role='assistant').count(), 0)
                    self.assertEqual(db.query(AssistantMessageAuthor).filter_by(run_id=run_id).count(), 1)
                    payloads = [row.payload for row in db.query(AssistantEvent).filter_by(run_id=run_id)]
                    self.assertFalse(any(row['event'] == 'message_end' for row in payloads))
                    self.assertEqual([row for row in payloads if row['event'] == 'run_end'],
                                     [{'event': 'run_end', 'status': 'error'}])
