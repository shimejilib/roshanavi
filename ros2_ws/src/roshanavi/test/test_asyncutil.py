"""run_cleanup: the cleanup of a WebSocket handler runs exactly once, even when cancelled."""

import asyncio
import threading

import anyio
import pytest

from roshanavi.asyncutil import run_cleanup


def test_runs_once_in_a_worker_thread():
    calls = []

    async def main():
        return await run_cleanup(lambda x: calls.append(threading.current_thread()) or x, 7)

    assert asyncio.run(main()) == 7
    assert len(calls) == 1 and calls[0] is not threading.main_thread()


def test_runs_once_when_the_task_is_already_cancelled():
    # anyio (Starlette) cancellation is level-triggered: every await in the scope raises,
    # so the thread pool is never reached and the cleanup runs on the loop thread
    calls = []

    async def handler():
        with anyio.CancelScope() as scope:
            scope.cancel()
            try:
                await anyio.sleep(10)
            finally:
                await run_cleanup(lambda: calls.append(threading.current_thread()))

    anyio.run(handler)
    assert calls == [threading.main_thread()]


def test_a_failing_cleanup_is_not_retried():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError('cleanup failed')

    with pytest.raises(RuntimeError):
        asyncio.run(run_cleanup(boom))
    assert calls == [1]
