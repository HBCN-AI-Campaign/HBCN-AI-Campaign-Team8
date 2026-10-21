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
            response = await client.request(method, '/api/assistant' + path, headers=headers,
                                            **({'json': body} if body is not None else {}))
            response.raise_for_status()
            return response.json()

        capability = await call('GET', '/capabilities')
        assert capability['configured'], 'Configure a real HSBC OpenCode runtime before this check'
        room = await call('POST', '/sessions', body={'title': '隔离协作验收', 'task_code': 'SYNTHETIC-COLLAB-1'})
        path = f"/sessions/{room['id']}"
        assert (await client.get('/api/assistant' + path, headers=expert)).status_code == 404
        await call('POST', path + '/members', body={'user_id': expert_id})
        await call('POST', path + '/messages', headers=expert, body={'content': '建议先核对合同币种与提款申请是否一致。'})
        assert (await client.get('/api/assistant' + path, headers=outsider)).status_code == 404

        payload = {'content': '这是合成验收数据。根据同事刚才的建议，用两句话说明下一步核对重点，明确结论必须由有权限的审核人员确认。不要查询外部法规。',
                   'client_message_id': 'live-collaboration-001'}
        started = time.monotonic()
        run = await call('POST', path + '/runs', headers=expert, body=payload)
        cursor, received = 0, []
        async with asyncio.timeout(260):
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
        assert not any(event['event'] == 'reasoning' for event in received)
        duplicate = await call('POST', path + '/runs', headers=expert, body=payload)
        assert duplicate['id'] == run['id']
        owner_history, expert_history = await call('GET', path), await call('GET', path, headers=expert)
        assert owner_history['messages'] == expert_history['messages']
        assert len(owner_history['messages']) == 3
        assert [row['author_id'] for row in owner_history['messages'][:2]] == [expert_id, expert_id]
        expert_events = await call('GET', path + f"/events?run_id={run['id']}", headers=expert)
        assert expert_events['events'] == received
        await call('DELETE', path + f'/members/{expert_id}')
        for suffix in ('', '/events', '/members'):
            assert (await client.get('/api/assistant' + path + suffix, headers=expert)).status_code == 404
        audit = await call('GET', path + '/audit')
        assert {row['action'] for row in audit} >= {'member_invited', 'member_revoked'}
        print(json.dumps({'passed': True, 'model': capability['model'], 'seconds': round(time.monotonic() - started, 2),
                          'same_history': True, 'same_events': True, 'idempotent_retry': True,
                          'revocation_blocks_access': True, 'real_model': True, 'synthetic_disposable_db': True}))
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
                import uvicorn
                from app.main import app
                print('Disposable browser QA: acceptance-owner / acceptance-expert; password: local-acceptance-only', flush=True)
                uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
        finally:
            # Release pooled SQLite file handles even when an assertion fails.
            from app.database import engine
            engine.dispose()
