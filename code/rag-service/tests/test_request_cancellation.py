import asyncio
import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from app.answer_graph import build_answer_graph
from app.config import settings
from app.graph_transport import GraphRun
from app.main import app
from app.pkulaw import PkulawSource
from app.request_control import RequestCancelled, RequestControl, request_scope, run_async
from app.runtime_client import SDKRuntime
from app.embedding import EmbeddingClient
from app.rerank import HTTPReranker
from app.runtime_client import RuntimeErrorResponse
from app.backend_api import GraphStreamingResponse


class CancellationTests(unittest.TestCase):
    def test_concurrent_graph_runs_keep_request_state_and_cancellation_isolated(self):
        both_entered, release = threading.Barrier(3), threading.Event()

        class EchoGraph:
            def invoke(self, state, _config):
                both_entered.wait(timeout=5)
                if not release.wait(5):
                    raise TimeoutError("synthetic graph release timeout")
                return {"result": {"query": state["query"], "conversation": state["conversation"]}}

        slots = threading.BoundedSemaphore(2)
        self.assertTrue(slots.acquire(False))
        self.assertTrue(slots.acquire(False))
        first = GraphRun(EchoGraph(), {"query": "查询甲", "conversation": [{"content": "金额甲"}]}, slots)
        second = GraphRun(EchoGraph(), {"query": "查询乙", "conversation": [{"content": "金额乙"}]}, slots)
        try:
            both_entered.wait(timeout=5)
            first.cancel()
            release.set()
            self.assertTrue(first.done.wait(5))
            self.assertTrue(second.done.wait(5))
        finally:
            first.cancel()
            second.cancel()
            release.set()
            first.worker.join(5)
            second.worker.join(5)

        self.assertTrue(first.queue.empty(), "cancelled run must not publish a result")
        self.assertEqual(second.queue.get_nowait(), ("result", {"query": "查询乙", "conversation": [{"content": "金额乙"}]}))
        self.assertTrue(second.queue.empty())
        self.assertTrue(slots.acquire(False), "request capacity leaked")
        self.assertTrue(slots.acquire(False), "request capacity leaked")
        slots.release()
        slots.release()

    def test_cancel_inflight_model_closes_stream_and_never_retrieves(self):
        started, closed = threading.Event(), threading.Event()

        class WaitingBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b""

            async def aclose(self):
                closed.set()

        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=WaitingBody())))
        engine, slots = Mock(), threading.BoundedSemaphore(1)
        self.assertTrue(slots.acquire(False))
        with patch("app.runtime_client.httpx.AsyncClient", return_value=client), \
                patch.object(settings, "ASSISTANT_RUNTIME_URL", "http://synthetic-runtime"), \
                patch("app.runtime_client.runtime_token", return_value="synthetic-only"):
            run = GraphRun(build_answer_graph(engine, SDKRuntime()), {"query": "金额核对", "scope": "all", "top_k": 3}, slots, stream=True)
            try:
                self.assertTrue(started.wait(5), "model never started")
                run.cancel()
                self.assertTrue(run.done.wait(5), "cancel did not unwind model/graph")
            finally:
                run.cancel()
                run.worker.join(5)
        self.assertTrue(closed.is_set(), "upstream response leaked")
        engine.retrieve.assert_not_called()
        self.assertTrue(slots.acquire(False), "slot leaked")
        with self.assertRaises(ValueError):
            slots.release()
            slots.release()

    def test_blocked_database_keeps_slot_and_stops_followup_after_return(self):
        entered, unblock = threading.Event(), threading.Event()
        engine, runtime = Mock(), Mock()
        runtime.complete.return_value = '{"intent":"rule","queries":[]}'

        def retrieve(**kwargs):
            entered.set()
            unblock.wait(5)
            return []

        engine.retrieve.side_effect = retrieve
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        run = GraphRun(build_answer_graph(engine, runtime), {"query": "金额核对", "scope": "all", "top_k": 3}, slots)
        try:
            self.assertTrue(entered.wait(5))
            run.cancel()
            self.assertFalse(slots.acquire(False), "released capacity while DB still running")
            unblock.set()
            self.assertTrue(run.done.wait(5))
        finally:
            run.cancel()
            unblock.set()
            run.worker.join(5)
        self.assertEqual(runtime.complete.call_count, 1)
        self.assertEqual(engine.retrieve.call_count, 1)
        self.assertTrue(run.queue.empty(), "cancelled result was published")
        self.assertTrue(slots.acquire(False))
        slots.release()

    def test_mcp_cancellation_unwinds_async_session_without_provider_fallback(self):
        started, closed = threading.Event(), threading.Event()

        async def request(**kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        control, errors = RequestControl(), []

        def execute():
            try:
                with request_scope(control):
                    PkulawSource().retrieve(query="合成条件")
            except RequestCancelled:
                errors.append("cancelled")

        with patch.object(PkulawSource, "retrieve_async", side_effect=request):
            thread = threading.Thread(target=execute)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                control.cancel()
                thread.join(5)
                self.assertFalse(thread.is_alive())
            finally:
                control.cancel()
                thread.join(5)
        self.assertEqual(errors, ["cancelled"])
        self.assertTrue(closed.is_set())

    def test_precancelled_operation_does_not_start_and_context_does_not_leak(self):
        control, operation = RequestControl(), Mock()
        control.cancel()
        with self.assertRaises(RequestCancelled), request_scope(control):
            run_async(operation)
        operation.assert_not_called()
        self.assertEqual(run_async(lambda: asyncio.sleep(0, result="next request")), "next request")

    def test_embedding_and_rerank_cancel_pending_http_response(self):
        original_client = httpx.AsyncClient
        for provider in ("embedding", "rerank"):
            with self.subTest(provider=provider):
                started, closed = threading.Event(), threading.Event()
                control, outcomes = RequestControl(), []

                class WaitingBody(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        started.set()
                        await asyncio.Event().wait()
                        yield b""

                    async def aclose(self):
                        closed.set()

                def factory(**kwargs):
                    return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=WaitingBody())), **kwargs)

                def execute():
                    try:
                        with request_scope(control):
                            if provider == "embedding":
                                EmbeddingClient().embed_one("synthetic")
                            else:
                                HTTPReranker(client_factory=factory).rerank(query="synthetic", evidence=[{"content": "synthetic"}])
                    except RequestCancelled:
                        outcomes.append("cancelled")

                with patch.object(settings, "BAILIAN_BASE_URL", "http://synthetic"), \
                        patch.object(settings, "BAILIAN_API_KEY", "synthetic"), \
                        patch.object(settings, "RAG_RERANK_PROVIDER", "cohere_compatible"), \
                        patch.object(settings, "RAG_RERANK_URL", "http://127.0.0.1/rerank"), \
                        patch.object(settings, "RAG_RERANK_MODEL", "synthetic"), \
                        patch("app.embedding.httpx.AsyncClient", side_effect=factory):
                    thread = threading.Thread(target=execute)
                    thread.start()
                    try:
                        self.assertTrue(started.wait(5))
                        control.cancel()
                        thread.join(5)
                        self.assertFalse(thread.is_alive())
                    finally:
                        control.cancel()
                        thread.join(5)
                self.assertEqual(outcomes, ["cancelled"])
                self.assertTrue(closed.is_set())

    def test_model_total_deadline_closes_silent_stream_without_external_cancel(self):
        closed = threading.Event()

        class WaitingBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.Event().wait()
                yield b""

            async def aclose(self):
                closed.set()

        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=WaitingBody())))
        with patch("app.runtime_client.httpx.AsyncClient", return_value=client), \
                patch.object(settings, "ASSISTANT_RUNTIME_URL", "http://synthetic-runtime"), \
                patch("app.runtime_client.runtime_token", return_value="synthetic-only"):
            with self.assertRaises(RuntimeErrorResponse):
                SDKRuntime().complete(message="synthetic", instructions="synthetic", evidence=[], timeout_seconds=0.05)
        self.assertTrue(closed.is_set())


class ASGIDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_failure_before_generator_entry_still_cancels(self):
        run = Mock()

        async def events():
            yield "never delivered"

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            raise OSError("synthetic broken socket")

        response = GraphStreamingResponse(events(), run)
        # The repository's pinned Starlette wraps send OSError in its AnyIO
        # task group, including for a newer ASGI spec value. Check that exact
        # failure and still require cancellation before generator entry.
        with self.assertRaises(ExceptionGroup) as caught:
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        self.assertEqual(len(caught.exception.exceptions), 1)
        self.assertIsInstance(caught.exception.exceptions[0], OSError)
        self.assertEqual(str(caught.exception.exceptions[0]), "synthetic broken socket")
        run.cancel.assert_called_once()

    async def test_json_answer_and_evidence_disconnect_cancel_without_result(self):
        for path in ("/api/v1/answers", "/api/v1/retrievals"):
            with self.subTest(path=path):
                entered, cleaned = threading.Event(), threading.Event()

                class Runtime:
                    def complete(self, **kwargs):
                        async def call():
                            try:
                                entered.set()
                                await asyncio.Event().wait()
                            finally:
                                cleaned.set()
                        return run_async(call)

                first, messages = True, []

                async def receive():
                    nonlocal first
                    if first:
                        first = False
                        return {"type": "http.request", "body": b'{"query":"synthetic"}', "more_body": False}
                    if entered.is_set():
                        return {"type": "http.disconnect"}
                    await asyncio.Event().wait()

                async def send(message):
                    messages.append(message)

                scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                         "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                         "headers": [(b"authorization", b"Bearer synthetic-only"), (b"content-type", b"application/json")],
                         "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 80)}
                slots = threading.BoundedSemaphore(1)
                with patch.object(settings, "SERVICE_TOKEN", "synthetic-only"), \
                        patch("app.backend_api.postgres_engine", return_value=Mock()), \
                        patch("app.backend_api.answer_slots", slots), patch("app.answer_graph.SDKRuntime", Runtime):
                    await asyncio.wait_for(app(scope, receive, send), timeout=8)
                    async with asyncio.timeout(5):
                        while not cleaned.is_set():
                            await asyncio.sleep(0.01)
                        while not slots.acquire(False):
                            await asyncio.sleep(0.01)
                    slots.release()
                self.assertEqual(next(m["status"] for m in messages if m["type"] == "http.response.start"), 499)

    async def test_sse_disconnect_cancels_graph_and_releases_worker_slot(self):
        entered, cleaned = threading.Event(), threading.Event()

        class Runtime:
            def complete(self, **kwargs):
                async def call():
                    try:
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        cleaned.set()
                return run_async(call)

        body_sent, messages = False, []

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": b'{"query":"synthetic"}', "more_body": False}
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/v1/answers/stream", "raw_path": b"/api/v1/answers/stream",
                 "query_string": b"", "root_path": "", "headers": [(b"authorization", b"Bearer synthetic-only"), (b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 80)}
        slots, engine = threading.BoundedSemaphore(1), Mock()
        with patch.object(settings, "SERVICE_TOKEN", "synthetic-only"), \
                patch("app.backend_api.postgres_engine", return_value=engine), \
                patch("app.backend_api.answer_slots", slots), patch("app.answer_graph.SDKRuntime", Runtime):
            await asyncio.wait_for(app(scope, receive, send), timeout=8)
            async with asyncio.timeout(5):
                while not cleaned.is_set():
                    await asyncio.sleep(0.01)
                while not slots.acquire(False):
                    await asyncio.sleep(0.01)
            slots.release()
        engine.retrieve.assert_not_called()
        self.assertFalse(any(b"event: result" in message.get("body", b"") for message in messages))
