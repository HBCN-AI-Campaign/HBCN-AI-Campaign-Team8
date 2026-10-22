"""Internal readiness contract, shared by capabilities and deployment preflight.

Configuration/authentication only; it does not claim a successful model call.
Never include an upstream exception, URL, response body or token in the result.
"""
from __future__ import annotations

import httpx


async def runtime_readiness(client: httpx.AsyncClient, base_url: str, token: str) -> dict:
    if not base_url or not token:
        return {"ready": False, "code": "unconfigured", "model": None}
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/readyz", headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code in (401, 403):
            return {"ready": False, "code": "token_rejected", "model": None}
        info = response.json()
        ready = response.is_success and isinstance(info, dict) and info.get("configured") is True and info.get("status") == "ready"
        return {"ready": ready, "code": "ready" if ready else "not_ready",
                "model": info.get("model") if ready and isinstance(info.get("model"), str) else None}
    except (httpx.HTTPError, ValueError):
        return {"ready": False, "code": "unreachable_or_invalid", "model": None}


async def rag_readiness(client: httpx.AsyncClient, base_url: str, token: str) -> dict:
    """Use the RAG module's existing authenticated readiness contract."""
    if not base_url or not token:
        return {"ready": False, "code": "unconfigured"}
    try:
        response = await client.get(f"{base_url.rstrip('/')}/api/v1/ready",
                                    headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            return {"ready": False, "code": "token_rejected", "http_status": response.status_code}
        info = response.json()
        ready = response.is_success and isinstance(info, dict) and info.get('status') == 'ready'
        return {"ready": ready, "code": "ready" if ready else "not_ready", "http_status": response.status_code}
    except (httpx.HTTPError, ValueError):
        return {"ready": False, "code": "unreachable_or_invalid"}
