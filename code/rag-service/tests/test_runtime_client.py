"""The deployed OpenCode runtime requires protocol 2 and authenticated readiness."""
import json
import unittest
from unittest.mock import patch

import httpx

from app.config import settings
from app.runtime_client import SDKRuntime


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.url = patch.object(settings, "ASSISTANT_RUNTIME_URL", "http://runtime.test")
        self.token = patch("app.runtime_client.runtime_token", return_value="test-runtime-token")
        self.url.start()
        self.token.start()
        self.addCleanup(self.url.stop)
        self.addCleanup(self.token.stop)

    def test_readiness_checks_caller_token_and_protocol(self):
        response = httpx.Response(200, json={"status": "ready", "configured": True, "assistant_protocol": 2})
        with patch("app.runtime_client.httpx.get", return_value=response) as get:
            self.assertTrue(SDKRuntime().health())
        self.assertEqual(get.call_args.args, ("http://runtime.test/readyz",))
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer test-runtime-token"})

    def test_liveness_or_wrong_protocol_does_not_claim_ready(self):
        for payload in (
            {"status": "ok", "configured": True, "assistant_protocol": 2},
            {"status": "ready", "configured": True},
            {"status": "ready", "configured": True, "assistant_protocol": 1},
            {"status": "ready", "configured": True, "assistant_protocol": True},
            {"status": "ready", "configured": False, "assistant_protocol": 2},
            [],
        ):
            with self.subTest(payload=payload), patch("app.runtime_client.httpx.get", return_value=httpx.Response(200, json=payload)):
                self.assertFalse(SDKRuntime().health())
        with patch("app.runtime_client.httpx.get", return_value=httpx.Response(401)):
            self.assertFalse(SDKRuntime().health())

    def test_real_http_wire_payload_is_accepted_by_protocol_two_runtime(self):
        received = []

        def handle(request):
            payload = json.loads(request.content)
            received.append(payload)
            if request.headers.get("authorization") != "Bearer test-runtime-token":
                return httpx.Response(401)
            if payload.get("assistant_protocol") != 2:
                return httpx.Response(422)
            self.assertEqual(request.url.path, "/runs")
            self.assertEqual(payload["evidence"][0]["text"], "金额不符时应先核对原件。")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                text='event: assistant_result\ndata: {"event":"assistant_result","answer":"已读取授权原文"}\n\n')

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("app.runtime_client.httpx.AsyncClient", return_value=client):
            result = SDKRuntime().complete(message="金额不符怎么办？", instructions="根据原文回答",
                evidence=[{"content": "金额不符时应先核对原件。", "document_keyword": "synthetic.txt", "metadata": {}}])
        self.assertEqual(result, "已读取授权原文")
        self.assertEqual(len(received), 1)
