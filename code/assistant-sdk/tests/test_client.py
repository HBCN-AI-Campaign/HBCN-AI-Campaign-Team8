import asyncio
import unittest

import httpx

from hbcn_assistant import AssistantClient, AssistantRunError


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_pages_through_unknown_events_and_only_returns_matching_final(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.params['after_id'] == '0':
                return httpx.Response(200, json={'cursor': 4, 'has_more': True, 'events': [
                    {'event': 'future_public_event', 'run_id': 'run-1'},
                    {'event': 'message_end', 'run_id': 'other-run', 'message': {'content': 'wrong'}},
                ]})
            return httpx.Response(200, json={'cursor': 5, 'has_more': False, 'events': [
                {'event': 'message_end', 'run_id': 'run-1', 'message': {'content': 'reviewer confirms'}},
            ]})

        async with AssistantClient('https://site.example', 'reviewer-jwt', transport=httpx.MockTransport(handler)) as client:
            answer = await client.wait(7, 'run-1')
        self.assertEqual(answer['content'], 'reviewer confirms')
        self.assertTrue(all(request.method == 'GET' for request in requests))
        self.assertEqual(requests[-1].url.params['after_id'], '4')
        self.assertEqual(requests[-1].headers['Authorization'], 'Bearer reviewer-jwt')

    async def test_timeout_does_not_cancel_or_resubmit_run(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'cursor': 0, 'has_more': False, 'events': []})
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(TimeoutError):
                await client.wait(7, 'run-1', timeout=.01)
        self.assertTrue(requests)
        self.assertTrue(all(request.method == 'GET' for request in requests))

    async def test_terminal_failure_is_identifiable_and_http_errors_are_preserved(self):
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'cursor': 1, 'has_more': False, 'events': [
                {'event': 'run_end', 'run_id': 'run-1', 'status': 'cancelled'},
            ]})
        )) as client:
            with self.assertRaises(AssistantRunError) as ended:
                await client.wait(7, 'run-1')
            self.assertEqual((ended.exception.run_id, ended.exception.status), ('run-1', 'cancelled'))
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(
            lambda _: httpx.Response(403, json={'detail': 'not authorized'})
        )) as client:
            with self.assertRaises(httpx.HTTPStatusError) as denied:
                await client.sessions()
            self.assertEqual(denied.exception.response.status_code, 403)

    async def test_explicit_contract_check_rejects_another_major(self):
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'contract_version': '2.0.0'})
        )) as client:
            with self.assertRaises(RuntimeError):
                await client.contract()

    async def test_saved_cursor_fetches_completed_result_without_replaying_or_posting(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'id': 'run-1', 'status': 'completed', 'message': {'content': 'saved result'}})
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(handler)) as client:
            result = await client.wait(7, 'run-1', after_id=900)
        self.assertEqual(result['content'], 'saved result')
        self.assertEqual([(r.method, r.url.path) for r in requests], [('GET', '/api/assistant/v1/sessions/7/runs/run-1')])

    async def test_completion_event_after_saved_message_fetches_canonical_result(self):
        fetches = []
        def handler(request):
            fetches.append(request)
            if request.url.path.endswith('/events'):
                return httpx.Response(200, json={'cursor': 9, 'has_more': False, 'events': [
                    {'event': 'run_end', 'run_id': 'run-1', 'status': 'completed'},
                ]})
            return httpx.Response(200, json={'status': 'completed', 'message': {'content': 'canonical result'}})
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(handler)) as client:
            result = await client.wait(7, 'run-1')
        self.assertEqual(result['content'], 'canonical result')
        self.assertEqual(len(fetches), 2)
        self.assertTrue(all(request.method == 'GET' for request in fetches))

    async def test_inconsistent_completed_snapshot_is_not_reported_as_success(self):
        async with AssistantClient('https://site.example', 'jwt', transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'status': 'completed', 'message': None})
        )) as client:
            with self.assertRaises(AssistantRunError) as failed:
                await client.wait(7, 'run-1', after_id=900)
            self.assertEqual(failed.exception.status, 'result_unavailable')
