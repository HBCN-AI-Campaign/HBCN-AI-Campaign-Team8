"""Request cancellation shared by the HTTP adapter and graph worker threads.

This is transport cleanup, not an agent scheduler. Blocking database statements
keep their resource timeout; a cancelled worker keeps its slot until it exits.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from contextvars import ContextVar


class RequestCancelled(asyncio.CancelledError):
    """Control flow must not become an ordinary model/provider failure."""


class RequestControl:
    def __init__(self):
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set():
            raise RequestCancelled("RAG request cancelled")


current_control: ContextVar[RequestControl | None] = ContextVar("rag_request_control", default=None)


@contextmanager
def request_scope(control):
    token = current_control.set(control)
    try:
        control.check()
        yield
    finally:
        current_control.reset(token)


def check_cancelled():
    control = current_control.get()
    if control is not None:
        control.check()


def run_async(operation):
    """Run an async HTTP/SDK operation from a synchronous graph node.

Use a factory so a pre-cancelled request never creates an unawaited coroutine.
Cancelling its task lets the client's async context managers close sockets and
MCP sessions. No unsafe cross-thread response.close or thread termination.
"""
    check_cancelled()
    control = current_control.get()

    async def guarded():
        if control is None:
            return await operation()

        async def watch():
            while not control.cancelled.is_set():
                await asyncio.sleep(0.05)

        task = asyncio.create_task(operation())
        watcher = asyncio.create_task(watch())
        try:
            await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
            control.check()
            return await task
        finally:
            for pending in (task, watcher):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, watcher, return_exceptions=True)

    return asyncio.run(guarded())
