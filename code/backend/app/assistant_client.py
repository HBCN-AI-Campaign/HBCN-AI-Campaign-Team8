"""Typed business HTTP adapter for workflow/Agent callers, backed by OpenCode.

Supply a delegated business JWT; never pass an HSBC key or runtime token here.
No separate agent framework and no bypass of session/task access checks.
"""
from __future__ import annotations

import asyncio

import httpx


class AssistantClient:
    def __init__(self, base_url: str, user_jwt: str, *, transport=None):
        self.http = httpx.AsyncClient(base_url=base_url.rstrip('/') + '/',
                                     headers={"Authorization": f"Bearer {user_jwt}"},
                                     timeout=20, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.http.aclose()

    async def _json(self, method, path, **kwargs):
        response = await self.http.request(method, f"api/assistant/{path}", **kwargs)
        response.raise_for_status()
        return response.json()

    async def create_session(self, task_code: str, title="工作流审核辅助") -> dict:
        return await self._json('POST', 'sessions', json={"title": title, "task_code": task_code})

    async def events(self, session_id: int, after_id=0, run_id: str | None = None) -> dict:
        return await self._json('GET', f'sessions/{session_id}/events',
                                params={"after_id": after_id, **({"run_id": run_id} if run_id else {})})

    async def ask(self, session_id: int, content: str, *, client_message_id: str,
                  skill_id: str | None = None, timeout=280) -> dict:
        """Retry with the SAME client_message_id to resume, not invoke twice."""
        run = await self._json('POST', f'sessions/{session_id}/runs', json={
            "content": content, "client_message_id": client_message_id, "skill_id": skill_id,
        })
        cursor = 0
        async with asyncio.timeout(timeout):
            while True:
                page = await self.events(session_id, cursor, run['id'])
                cursor = page['cursor']
                for event in page['events']:
                    if event['event'] == 'message_end':
                        return event['message']
                    if event['event'] == 'run_end':
                        raise RuntimeError(f"Assistant run ended: {event.get('status', 'error')}")
                if not page['has_more']:
                    await asyncio.sleep(.7)

    async def cancel(self, session_id: int, run_id: str) -> dict:
        return await self._json('POST', f'sessions/{session_id}/runs/{run_id}/cancel')
