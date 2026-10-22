"""V1 business HTTP adapter. Supply a reviewer JWT, never a model/runtime key."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


class AssistantRunError(RuntimeError):
    def __init__(self, run_id: str, status: str):
        self.run_id = run_id
        self.status = status
        super().__init__(f"Assistant run {run_id} ended: {status}")


class AssistantClient:
    def __init__(self, base_url: str, user_jwt: str, *, transport=None):
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip('/') + '/',
            headers={"Authorization": f"Bearer {user_jwt}"}, timeout=20, transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.http.aclose()

    async def _json(self, method: str, path: str, **kwargs) -> Any:
        response = await self.http.request(method, f"api/assistant/v1/{path}", **kwargs)
        response.raise_for_status()
        return response.json()

    async def contract(self) -> dict:
        result = await self._json('GET', 'contract')
        if not str(result.get('contract_version', '')).startswith('1.'):
            raise RuntimeError('Server does not provide the supported assistant V1 contract')
        return result

    async def capabilities(self) -> dict:
        return await self._json('GET', 'capabilities')

    async def create_session(self, task_code: str | None = None, title="工作流审核辅助") -> dict:
        return await self._json('POST', 'sessions', json={"title": title, "task_code": task_code})

    async def sessions(self) -> list[dict]:
        return await self._json('GET', 'sessions')

    async def session(self, session_id: int) -> dict:
        return await self._json('GET', f'sessions/{session_id}')

    async def start_run(self, session_id: int, content: str, *, client_message_id: str,
                        skill_id: str | None = None) -> dict:
        """Persist this ID before calling; reuse it with the same body on retry."""
        return await self._json('POST', f'sessions/{session_id}/runs', json={
            "content": content, "client_message_id": client_message_id, "skill_id": skill_id,
        })

    async def events(self, session_id: int, after_id=0, run_id: str | None = None) -> dict:
        return await self._json('GET', f'sessions/{session_id}/events',
                                params={"after_id": after_id, **({"run_id": run_id} if run_id else {})})

    async def wait(self, session_id: int, run_id: str, *, after_id=0, timeout=280) -> dict:
        """Read an existing run only. Timeout/disconnect does not cancel it."""
        cursor = after_id
        async with asyncio.timeout(timeout):
            while True:
                page = await self.events(session_id, cursor, run_id)
                cursor = page['cursor']
                for event in page['events']:
                    if event.get('run_id', run_id) != run_id:
                        continue
                    if event['event'] == 'message_end':
                        return event['message']
                    if event['event'] == 'run_end':
                        raise AssistantRunError(run_id, event.get('status', 'error'))
                if not page['has_more']:
                    await asyncio.sleep(.7)

    async def ask(self, session_id: int, content: str, *, client_message_id: str,
                  skill_id: str | None = None, timeout=280) -> dict:
        """Retry with the SAME client_message_id to resume, not invoke twice."""
        run = await self.start_run(session_id, content, client_message_id=client_message_id, skill_id=skill_id)
        return await self.wait(session_id, run['id'], timeout=timeout)

    async def cancel(self, session_id: int, run_id: str) -> dict:
        return await self._json('POST', f'sessions/{session_id}/runs/{run_id}/cancel')

    async def discuss(self, session_id: int, content: str) -> dict:
        return await self._json('POST', f'sessions/{session_id}/messages', json={"content": content})

    async def experts(self, session_id: int, query="") -> list[dict]:
        return await self._json('GET', 'experts', params={"session_id": session_id, "q": query})

    async def members(self, session_id: int) -> list[dict]:
        return await self._json('GET', f'sessions/{session_id}/members')

    async def invite(self, session_id: int, user_id: int) -> dict:
        return await self._json('POST', f'sessions/{session_id}/members', json={"user_id": user_id})

    async def revoke(self, session_id: int, user_id: int) -> dict:
        return await self._json('DELETE', f'sessions/{session_id}/members/{user_id}')

    async def skills(self) -> list[dict]:
        return await self._json('GET', 'skills')

    async def skill_library(self) -> list[dict]:
        return await self._json('GET', 'skill-library')
