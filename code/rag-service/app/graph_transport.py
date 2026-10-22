"""Bounded HTTP-to-LangGraph bridge; retain capacity until worker cleanup."""
from __future__ import annotations

import asyncio
import queue
import threading
from contextlib import closing

from .request_control import RequestCancelled, RequestControl, request_scope


class GraphRun:
    def __init__(self, graph, state, slots, *, stream=False):
        self.control = RequestControl()
        self.queue = queue.Queue(maxsize=64)
        self.done = threading.Event()
        self.graph, self.state, self.slots, self.stream = graph, state, slots, stream
        # Capacity has already been reserved by the route. Do not release it on
        # client disconnect while a blocking dependency may still be executing.
        self.worker = threading.Thread(target=self._work, name="rag-request", daemon=True)
        try:
            self.worker.start()
        except BaseException:
            slots.release()
            raise

    def cancel(self):
        self.control.cancel()

    def _put(self, item):
        while True:
            self.control.check()
            try:
                self.queue.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def _work(self):
        try:
            with request_scope(self.control):
                if self.stream:
                    with closing(self.graph.stream(self.state, {"recursion_limit": 12}, stream_mode=["custom", "updates"])) as updates:
                        for mode, update in updates:
                            self.control.check()
                            if mode == "custom":
                                self._put(("step", update))
                            elif "generate" in update:
                                self._put(("result", update["generate"]["result"]))
                else:
                    result = self.graph.invoke(self.state, {"recursion_limit": 12})["result"]
                    self._put(("result", result))
        except RequestCancelled:
            pass
        except Exception:
            # No exception object, provider body, credential or evidence enters
            # this transport error. Existing clients receive only a safe error.
            if not self.control.cancelled.is_set():
                try:
                    self._put(("error", {"message": "检索或生成服务未完成本轮请求，请稍后重试。"}))
                except RequestCancelled:
                    pass
        finally:
            self.slots.release()
            self.done.set()

    async def next(self):
        """Return None only after completion and after draining queued events."""
        self.control.check()
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            if self.done.is_set():
                return None
        # Bounded waiting avoids blocking the event loop or leaving a permanent
        # queue.get in an executor when the ASGI response is cancelled.
        await asyncio.sleep(0.05)
        return ("pending", None)
