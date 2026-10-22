"""Internal readiness contract, shared by capabilities and deployment preflight.

Configuration/authentication only; it does not claim a successful model call.
Never include an upstream exception, URL, response body or token in the result.
"""
from __future__ import annotations

import re

import httpx

ASSISTANT_PROTOCOL = 2
RAG_CONTRACT_MINIMUM = (1, 2, 0)
_RAG_CONTRACT_VERSION = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')


def rag_contract_version_status(headers) -> tuple[str | None, str | None]:
    """Require the RAG v1.2 evidence contract before readiness or use.

    The RAG service publishes its contract in X-RAG-Contract-Version. The
    assistant depends on the v1.2 retrieval semantics and accepts compatible
    v1 minor/patch releases, but must stop on missing, older, or new-major APIs.
    """
    version = (headers.get('X-RAG-Contract-Version') or '').strip()
    match = _RAG_CONTRACT_VERSION.fullmatch(version)
    if not match:
        return None, 'contract_missing'
    parsed = tuple(int(part) for part in match.groups())
    if parsed[0] != 1 or parsed < RAG_CONTRACT_MINIMUM:
        return version, 'contract_mismatch'
    return version, None


def runtime_problem(code: str) -> str:
    """Safe, actionable diagnosis shared by the page, runs and deployment checks."""
    return {
        'unconfigured': '助手内部服务未配置，请设置后端的 runtime 地址和服务令牌',
        'token_rejected': '助手内部服务鉴权失败，请检查后端与 runtime 的令牌是否一致',
        'contract_missing': '该地址未提供助手就绪接口，请检查 runtime 地址、端口及运行版本',
        'protocol_mismatch': '助手后端与 runtime 协议版本不一致，请使用同一发布版本并重启 runtime',
    }.get(code, 'OpenCode runtime 未就绪，请检查运行时地址、进程及汇丰模型配置')


async def runtime_readiness(client: httpx.AsyncClient, base_url: str, token: str) -> dict:
    if not base_url or not token:
        return {"ready": False, "code": "unconfigured", "model": None}
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/readyz", headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code in (401, 403):
            return {"ready": False, "code": "token_rejected", "model": None}
        if response.status_code in (404, 405):
            return {"ready": False, "code": "contract_missing", "model": None}
        info = response.json()
        ready = response.is_success and isinstance(info, dict) and info.get("configured") is True and info.get("status") == "ready"
        if ready and (type(info.get('assistant_protocol')) is not int or info['assistant_protocol'] != ASSISTANT_PROTOCOL):
            return {"ready": False, "code": "protocol_mismatch", "model": None}
        return {"ready": ready, "code": "ready" if ready else "not_ready",
                "model": info.get("model") if ready and isinstance(info.get("model"), str) else None}
    except (httpx.HTTPError, ValueError):
        return {"ready": False, "code": "unreachable_or_invalid", "model": None}


async def rag_readiness(client: httpx.AsyncClient, base_url: str, token: str) -> dict:
    """Require authenticated readiness and a compatible RAG evidence contract."""
    if not base_url or not token:
        return {"ready": False, "code": "unconfigured"}
    try:
        response = await client.get(f"{base_url.rstrip('/')}/api/v1/ready",
                                    headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            return {"ready": False, "code": "token_rejected", "http_status": response.status_code}
        version, version_problem = rag_contract_version_status(response.headers)
        if version_problem:
            return {"ready": False, "code": version_problem, "http_status": response.status_code}
        info = response.json()
        ready = response.is_success and isinstance(info, dict) and info.get('status') == 'ready'
        return {"ready": ready, "code": "ready" if ready else "not_ready",
                "http_status": response.status_code, "contract_version": version}
    except (httpx.HTTPError, ValueError):
        return {"ready": False, "code": "unreachable_or_invalid"}
