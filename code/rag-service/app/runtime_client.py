from __future__ import annotations

import json
import asyncio

import httpx
from dotenv import dotenv_values

from .config import settings
from .evidence_context import ContextBudgetError, MAX_RUNTIME_BODY_BYTES, payload_bytes, runtime_payload
from .request_control import run_async


class RuntimeErrorResponse(RuntimeError):
    pass


def runtime_token():
    token = settings.ASSISTANT_RUNTIME_TOKEN.get_secret_value()
    if not token and settings.ASSISTANT_RUNTIME_RESOURCE_FILE:
        try:
            token = dotenv_values(settings.ASSISTANT_RUNTIME_RESOURCE_FILE).get("ASSISTANT_RUNTIME_TOKEN") or ""
        except OSError:
            raise RuntimeErrorResponse("OpenCode SDK 服务凭证文件无法读取") from None
    return token


class SDKRuntime:
    @property
    def configured(self):
        return bool(settings.ASSISTANT_RUNTIME_URL and runtime_token())

    def health(self):
        if not self.configured:
            return False
        try:
            response = httpx.get(f"{settings.ASSISTANT_RUNTIME_URL.rstrip('/')}/healthz", timeout=5)
            return response.is_success and response.json().get("configured") is True
        except (httpx.HTTPError, ValueError):
            return False

    def complete(self, *, message, instructions, evidence, conversation=None, timeout_seconds=None):
        if not self.configured:
            raise RuntimeErrorResponse("OpenCode SDK 运行时尚未配置")
        try:
            payload = runtime_payload(message=message, instructions=instructions, evidence=evidence, conversation=conversation)
            if payload_bytes(payload) > MAX_RUNTIME_BODY_BYTES:
                raise ContextBudgetError("SDK 请求体超过字节预算，不能静默截断")
        except ContextBudgetError as exc:
            raise RuntimeErrorResponse(str(exc)) from None
        duration = min(settings.RAG_ANSWER_TIMEOUT_SECONDS, timeout_seconds) if timeout_seconds is not None else settings.RAG_ANSWER_TIMEOUT_SECONDS
        if duration <= 0:
            raise RuntimeErrorResponse("OpenCode SDK 调用预算已耗尽")
        return run_async(lambda: self._complete(payload, duration))

    async def _complete(self, payload, duration):
        try:
            async with asyncio.timeout(duration):
                async with httpx.AsyncClient(timeout=httpx.Timeout(duration, connect=min(10, duration)), follow_redirects=False) as client:
                    async with client.stream(
                        "POST", f"{settings.ASSISTANT_RUNTIME_URL.rstrip('/')}/runs",
                        headers={"Authorization": f"Bearer {runtime_token()}"}, json=payload,
                    ) as response:
                        if not response.is_success:
                            raise RuntimeErrorResponse(f"OpenCode SDK 暂不可用（HTTP {response.status_code}）")
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                event = json.loads(line[5:])
                            except ValueError:
                                continue
                            if event.get("event") == "assistant_result":
                                answer = event.get("answer")
                                if isinstance(answer, str) and answer.strip():
                                    return answer.strip()
                                raise RuntimeErrorResponse("OpenCode SDK 未生成回答，请稍后重试")
        except TimeoutError:
            raise RuntimeErrorResponse("OpenCode SDK 调用达到时间预算") from None
        except httpx.HTTPError:
            raise RuntimeErrorResponse("OpenCode SDK 连接失败或超时，请稍后重试") from None
        raise RuntimeErrorResponse("OpenCode SDK 响应中缺少最终回答")
