"""Helpers for async (FastAPI / WebSocket) handlers."""

from typing import Any, Callable

from fastapi.concurrency import run_in_threadpool


async def run_cleanup(fn: Callable[..., Any], *args: Any) -> Any:
    """Run blocking cleanup ``fn(*args)`` in the thread pool, exactly once.

    A handler's ``finally`` can run in a task that is already cancelled (server shutdown;
    Starlette 0.4x's TestClient cancels the WebSocket task right after the client closes).
    Awaiting the thread pool then raises before ``fn`` starts, so the subscription or job
    would leak; in that case ``fn`` runs here, on the event loop thread.
    """
    started = False

    def call() -> Any:
        nonlocal started
        started = True
        return fn(*args)

    try:
        return await run_in_threadpool(call)
    finally:
        if not started:
            call()
