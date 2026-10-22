"""Opt-in HTTP deployment acceptance; never modifies business tasks or users.

Requires two reviewer JWTs in HBCN_VERIFY_OWNER_JWT / HBCN_VERIFY_EXPERT_JWT.
Creates and deletes one assistant session tied to an existing authorized demo
task. Makes one model run; do not use a confidential real task for acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

import httpx

from .client import AssistantClient


class VerificationFailure(RuntimeError):
    """Only safe stage names are included in command-line output."""
    def __init__(self, stage: str, *, cleanup_complete: bool = True):
        self.stage = stage
        self.cleanup_complete = cleanup_complete
        super().__init__(stage)


def require(condition: bool, stage: str):
    if not condition:
        raise VerificationFailure(stage)


async def expect_denied(client: AssistantClient, path: str, stage: str):
    try:
        await client._json('GET', path)
    except httpx.HTTPStatusError as exc:
        require(exc.response.status_code == 404, stage)
        return
    raise VerificationFailure(stage)


async def cleanup_room(owner: AssistantClient, session_id: int) -> bool:
    """Only clean this command's newly created room, never caller-owned history."""
    try:
        for _ in range(20):
            detail = await owner.session(session_id)
            active = detail.get('active_run')
            if active:
                await owner.cancel(session_id, active['id'])
                await asyncio.sleep(.25)
                continue
            await owner._json('DELETE', f'sessions/{session_id}')
            return True
    except Exception:
        return False
    return False


async def verify_site(site: str, owner_jwt: str, expert_jwt: str, task_code: str,
                      expert_id: int, *, require_rag=False, transport=None) -> dict:
    """Real HTTP by default; transport is injectable solely for deterministic tests."""
    stage = 'configuration'
    require(bool(owner_jwt and expert_jwt and task_code and expert_id > 0), stage)
    started = time.monotonic()
    session_id = None
    cleanup_complete = True
    report = {}
    failure = None
    async with AssistantClient(site, owner_jwt, transport=transport) as owner, AssistantClient(
        site, expert_jwt, transport=transport
    ) as expert:
        try:
            stage = 'contract'
            contract = await owner.contract()
            stage = 'readiness'
            capabilities = await owner.capabilities()
            require(capabilities.get('configured') is True, stage)
            require(not require_rag or capabilities.get('rag_available') is True, 'rag_readiness')
            # Validate the second identity before creating or calling the model.
            await expert.contract()
            stage = 'create_disposable_room'
            room = await owner.create_session(task_code, title='[验收临时会话] ' + uuid4().hex[:8])
            session_id = room['id']
            prefix = f'sessions/{session_id}'
            stage = 'uninvited_isolation'
            await expect_denied(expert, prefix, stage)
            stage = 'invite_identity'
            await owner.invite(session_id, expert_id)
            members = await expert.members(session_id)
            require(any(row['user_id'] == expert_id and row['is_self'] for row in members), stage)
            require(expert_id != room['owner_id'], stage)
            stage = 'named_discussion'
            discussion = await expert.discuss(session_id, '验收讨论：请依据授权任务概要核对币种与金额。')
            require(discussion.get('author_id') == expert_id, stage)
            stage = 'real_model_answer'
            content = ('本轮为演示环境联通验收。请读取授权任务概要，保留币种代码和数字金额，'
                       '用两句话概述核对重点并标注本轮证据编号 [E编号]；'
                       '说明最终结论必须由有权限的审核人员确认。不要查询外部法规。')
            key = 'verify_' + uuid4().hex
            run = await owner.start_run(session_id, content, client_message_id=key)
            # The submitting request has returned; a second identity now reads
            # the admitted background run without submitting another question.
            answer = await expert.wait(session_id, run['id'], timeout=380)
            require(bool(answer.get('content', '').strip()), stage)
            stage = 'citations'
            citations = answer.get('citations') or []
            require(bool(citations) and all('[' + row['reference_id'] + ']' in answer['content']
                                           for row in citations), stage)
            require(any(row.get('source_id') == task_code for row in citations), stage)
            stage = 'same_history'
            owner_room, expert_room = await owner.session(session_id), await expert.session(session_id)
            require(owner_room['messages'] == expert_room['messages'], stage)
            require([row['author_id'] for row in owner_room['messages'] if row['role'] == 'user'] ==
                    [expert_id, room['owner_id']], stage)
            stage = 'idempotent_retry'
            duplicate = await owner.start_run(session_id, content, client_message_id=key)
            require(duplicate['id'] == run['id'], stage)
            stage = 'saved_result'
            snapshot = await expert.run(session_id, run['id'])
            require(snapshot['status'] == 'completed' and snapshot['message'] == answer, stage)
            # Exhaust public events; restore after the consumed cursor.
            cursor = 0
            while True:
                page = await expert.events(session_id, cursor, run['id'])
                require(not any(row['event'] == 'reasoning' for row in page['events']), 'public_events')
                cursor = page['cursor']
                if not page['has_more']:
                    break
            require(await owner.wait(session_id, run['id'], after_id=cursor) == answer, stage)
            stage = 'revocation'
            await owner.revoke(session_id, expert_id)
            for suffix in ('', '/events', '/runs/' + run['id'], '/members'):
                await expect_denied(expert, prefix + suffix, stage)
            report = {
                'passed': True, 'transport': 'http' if transport is None else 'test_transport',
                'contract_version': contract['contract_version'],
                'rag_available': capabilities.get('rag_available') is True,
                'same_history': True, 'citations_resolved': True, 'idempotent_retry': True,
                'saved_cursor_recovered': True, 'revocation_blocks_access': True,
            }
        except Exception as exc:
            failure = exc.stage if isinstance(exc, VerificationFailure) else stage
        finally:
            if session_id is not None:
                cleanup_complete = await cleanup_room(owner, session_id)
    if failure or not cleanup_complete:
        raise VerificationFailure(failure or 'cleanup', cleanup_complete=cleanup_complete)
    return {**report, 'cleanup_complete': True, 'seconds': round(time.monotonic() - started, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='Website root, including any proxy prefix')
    parser.add_argument('--task', required=True, help='Existing authorized synthetic/demo task code')
    parser.add_argument('--expert-id', required=True, type=int, help='User ID belonging to the second reviewer JWT')
    parser.add_argument('--live', required=True, action='store_true', help='Allow one real model run and a temporary assistant room')
    parser.add_argument('--require-rag', action='store_true', help='Fail before model call if the knowledge service is not ready')
    args = parser.parse_args()
    try:
        result = asyncio.run(verify_site(args.site, os.environ.get('HBCN_VERIFY_OWNER_JWT', ''),
                                        os.environ.get('HBCN_VERIFY_EXPERT_JWT', ''),
                                        args.task, args.expert_id, require_rag=args.require_rag))
    except VerificationFailure as exc:
        print(json.dumps({'passed': False, 'stage': exc.stage, 'cleanup_complete': exc.cleanup_complete}))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
