from __future__ import annotations

import json

import httpx
from dotenv import dotenv_values

from .config import settings


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

    def complete(self, *, message, instructions, evidence, conversation=None):
        if not self.configured:
            raise RuntimeErrorResponse("OpenCode SDK 运行时尚未配置")
        payload = {
            "message": message, "instructions": instructions,
            "conversation": conversation or [],
            "evidence": [{"type": "rag", "id": str(index + 1), "text": item["content"][:4000],
                          "source": (item["document_keyword"] + " | " +
                                     str(item.get("metadata", {}).get("scope", "")) + " | " +
                                     str(item.get("metadata", {}).get("jurisdiction", "")) +
                                     (" | 法规效力及附件完整性未核验" if item.get("metadata", {}).get("scope") == "law" else ""))[:500],
                          "page": item.get("page_num")}
                         for index, item in enumerate(evidence)],
        }
        try:
            with httpx.stream(
                "POST", f"{settings.ASSISTANT_RUNTIME_URL.rstrip('/')}/runs",
                headers={"Authorization": f"Bearer {runtime_token()}"}, json=payload,
                timeout=httpx.Timeout(settings.RAG_ANSWER_TIMEOUT_SECONDS, connect=10),
            ) as response:
                if not response.is_success:
                    raise RuntimeErrorResponse(f"OpenCode SDK 暂不可用（HTTP {response.status_code}）")
                for line in response.iter_lines():
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
        except httpx.HTTPError:
            raise RuntimeErrorResponse("OpenCode SDK 连接失败或超时，请稍后重试") from None
        raise RuntimeErrorResponse("OpenCode SDK 响应中缺少最终回答")
