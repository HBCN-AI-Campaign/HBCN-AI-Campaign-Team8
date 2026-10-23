"""Opt-in live HSBC collaboration check, using disposable synthetic business data.

Run in a fresh process: python -m tests.live_assistant_acceptance --live
Requires the existing server-side runtime/RAG configuration. Makes a real model
request; never replaces the shared business DB, prints credentials, or seeds
fictional experts into it. HTTPX drives the real ASGI app/auth/DB routes; only
the network hop to this in-process API is bypassed. Runtime/model are real HTTP.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

import httpx


def seed_fixture(password):
    # Import settings/engine only after pointing this fresh process at a new DB.
    from app import models
    from app.assistant_models import AssistantExpertProfile
    from app.database import Base, SessionLocal, engine
    from app.main import app
    from app.security import hash_password

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        people = [models.User(username=name, display_name=label, role=models.Role.REVIEWER,
                              hashed_password=hash_password(password)) for name, label in (
            ('acceptance-owner', '验收审核人员'), ('acceptance-expert', '验收同事'),
            ('acceptance-outsider', '未邀请验收账号'))]
        db.add_all(people); db.flush()
        expert_id = people[1].id
        db.add(models.ReviewTask(task_code='SYNTHETIC-COLLAB-1', borrower='合成验收企业',
                                drawdown_currency='USD', drawdown_amount=100, submitted_by=people[0].id))
        db.add(AssistantExpertProfile(user_id=expert_id, specialty='合成资料验收', bio='仅用于隔离测试', tags=['合同']))
        db.commit()
    return expert_id


async def verify():
    from app.database import engine
    from app.main import app
    password = secrets.token_urlsafe(24)
    expert_id = seed_fixture(password)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://acceptance', timeout=30) as client:
        async def login(name):
            response = await client.post('/api/auth/login', data={'username': name, 'password': password})
            response.raise_for_status()
            return {'Authorization': 'Bearer ' + response.json()['access_token']}

        owner, expert, outsider = [await login(name) for name in
                                   ('acceptance-owner', 'acceptance-expert', 'acceptance-outsider')]
        async def call(method, path, headers=owner, body=None):
            response = await client.request(method, '/api/assistant/v1' + path, headers=headers,
                                            **({'json': body} if body is not None else {}))
            response.raise_for_status()
            return response.json()

        capability = await call('GET', '/capabilities')
        assert capability['configured'], 'Configure a real HSBC OpenCode runtime before this check'
        room = await call('POST', '/sessions', body={'title': '隔离协作验收', 'task_code': 'SYNTHETIC-COLLAB-1'})
        path = f"/sessions/{room['id']}"
        assert (await client.get('/api/assistant/v1' + path, headers=expert)).status_code == 404
        assert (await client.get('/api/assistant/v1' + path, headers=outsider)).status_code == 404

        payload = {'content': '这是合成验收数据。先读取授权证据，准确说明本任务的币种（保留代码）和金额（使用数字），标注本轮证据编号 [E编号]，说明下一步核对重点，明确结论必须由有权限的审核人员确认。不要查询外部法规。',
                   'client_message_id': 'live-collaboration-001'}
        started = time.monotonic()
        run = await call('POST', path + '/runs', body=payload)
        # No event reader is attached. Reopening a private room must find the
        # same durable run; inviting an expert must not restart the model.
        await asyncio.sleep(.4)
        reopened = await call('GET', path)
        assert not reopened['shared']
        assert ((reopened['active_run'] or {}).get('id') == run['id'] or
                any(row.get('run_id') == run['id'] and row['role'] == 'assistant' for row in reopened['messages']))
        await call('POST', path + '/members', body={'user_id': expert_id})
        await call('POST', path + '/messages', headers=expert, body={'content': '建议下轮核对合同币种与提款申请是否一致。'})
        cursor, received = 0, []
        async with asyncio.timeout(380):
            while True:
                page = await call('GET', path + f"/events?after_id={cursor}&run_id={run['id']}")
                received.extend(page['events']); cursor = page['cursor']
                if any(event['event'] == 'run_end' for event in received):
                    break
                if not page['has_more']:
                    await asyncio.sleep(.7)
        final = [event for event in received if event['event'] == 'message_end']
        assert len(final) == 1 and received[-1]['status'] == 'completed', 'Real model run did not finish'
        assert final[0]['message']['content'].strip()
        answer = final[0]['message']['content']
        cited = final[0]['message']['citations']
        assert 'USD' in answer and '100' in answer, 'Authorized task fields did not reach the answer'
        assert cited and all('[' + row['reference_id'] + ']' in answer for row in cited), 'Source attribution is missing'
        assert any(row['source_id'] == 'SYNTHETIC-COLLAB-1' for row in cited), 'Task overview was not cited'
        assert not any(event['event'] == 'reasoning' for event in received)
        duplicate = await call('POST', path + '/runs', body=payload)
        assert duplicate['id'] == run['id']
        owner_history, expert_history = await call('GET', path), await call('GET', path, headers=expert)
        assert owner_history['messages'] == expert_history['messages']
        assert len(owner_history['messages']) == 3
        assert [row['author_id'] for row in owner_history['messages'] if row['role'] == 'user'] == [room['owner_id'], expert_id]
        expert_events = await call('GET', path + f"/events?run_id={run['id']}", headers=expert)
        assert expert_events['events'] == received
        from hbcn_assistant import AssistantClient
        async with AssistantClient('http://acceptance', owner['Authorization'].removeprefix('Bearer '),
                                   transport=httpx.ASGITransport(app=app)) as sdk:
            assert (await sdk.contract())['contract_version'] == '1.3.0'
            replayed = await sdk.ask(room['id'], payload['content'], client_message_id=payload['client_message_id'])
            assert replayed == final[0]['message'], 'V1 SDK must replay the same canonical answer'
            snapshot = await sdk.run(room['id'], run['id'])
            assert snapshot['message'] == replayed, 'Run status must return the persisted final answer'
            assert await sdk.wait(room['id'], run['id'], after_id=cursor) == replayed
        await call('DELETE', path + f'/members/{expert_id}')
        for suffix in ('', '/events', '/members'):
            assert (await client.get('/api/assistant/v1' + path + suffix, headers=expert)).status_code == 404
        audit = await call('GET', path + '/audit')
        assert {row['action'] for row in audit} >= {'member_invited', 'member_revoked'}
        print(json.dumps({'passed': True, 'model': capability['model'], 'seconds': round(time.monotonic() - started, 2),
                          'same_history': True, 'same_events': True, 'idempotent_retry': True,
                          'private_run_reopened': True, 'private_to_shared_same_run': True,
                          'versioned_sdk_replay': True,
                          'saved_cursor_result_recovered': True,
                          'revocation_blocks_access': True, 'real_model': True, 'synthetic_disposable_db': True,
                          'authorized_task_fields_answered': True, 'source_ids_resolved': True}))
    engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--live', action='store_true', help='explicitly allow a real HSBC model call')
    mode.add_argument('--browser-fixture', action='store_true', help='serve a disposable loopback API for manual browser QA')
    parser.add_argument('--port', type=int, default=8033)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hbcn-live-assistant-') as temporary:
        os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(temporary) / 'acceptance.db').as_posix()
        os.environ['DEBUG'] = 'false'
        try:
            if args.live:
                asyncio.run(verify())
            else:
                # Public test password for synthetic data in a loopback-only,
                # disposable process. Never use these accounts in a shared DB.
                seed_fixture('local-acceptance-only')
                from app import models
                from app.database import SessionLocal
                with SessionLocal() as db:
                    owner = db.query(models.User).filter_by(username='acceptance-owner').one()
                    db.add(models.ReviewTask(task_code='SYNTHETIC-COLLAB-2', borrower='第二家合成验收企业',
                                             drawdown_currency='EUR', drawdown_amount=200,
                                             submitted_by=owner.id))
                    db.commit()
                import uvicorn
                from app.main import app
                print('Disposable browser QA: acceptance-owner / acceptance-expert; password: local-acceptance-only', flush=True)
                uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
        finally:
            # Release pooled SQLite file handles even when an assertion fails.
            from app.database import engine
            engine.dispose()
