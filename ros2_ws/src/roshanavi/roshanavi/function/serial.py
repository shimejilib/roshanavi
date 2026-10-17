"""One worker thread that runs every call into a class node's user code, one at a time.

A class keeps state between calls and its author should not need locks, so ``__init__``, every
processing and action method, parameter changes, hot reload and ``close()`` all run on this one
thread, in the order they were submitted. ROS callbacks only convert a message and queue a job.
The queue is bounded: when the class cannot keep up, new messages are dropped (and counted) rather
than piling up in memory.
"""

import logging
import queue
import threading
from typing import Any, Callable, Optional

LOG = logging.getLogger('roshanavi.function')
MAX_PENDING = 1000


class _Job:
    def __init__(self, fn: Callable[[], Any]):
        self.fn = fn
        self.done = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


class SerialExecutor:
    def __init__(self, name: str = 'class-worker', max_pending: int = MAX_PENDING):
        self._queue: 'queue.Queue[Optional[_Job]]' = queue.Queue(maxsize=max_pending)
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()

    @property
    def ident(self) -> Optional[int]:
        return self._thread.ident

    def on_worker(self) -> bool:
        return threading.get_ident() == self._thread.ident

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                job.result = job.fn()
            except BaseException as exc:  # handed to whoever waits; fire-and-forget: logged
                job.error = exc
                if not isinstance(exc, Exception):
                    LOG.exception('class worker: %s', exc)
            finally:
                job.done.set()

    def submit(self, fn: Callable[[], Any]) -> bool:
        """Queue ``fn`` without waiting; False when stopped or the queue is full."""
        if self._stopped:
            return False
        try:
            self._queue.put_nowait(_Job(fn))
        except queue.Full:
            return False
        return True

    def run(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        """Run ``fn`` on the worker and return its result (raises what it raised).

        Called from the worker itself, ``fn`` runs inline. ``TimeoutError`` when it did not start
        and finish in ``timeout`` seconds (it may still run later)."""
        if self.on_worker():
            return fn()
        if self._stopped:
            raise RuntimeError('the class worker is stopped')
        job = _Job(fn)
        try:
            self._queue.put(job, timeout=timeout)
        except queue.Full:
            raise TimeoutError('the class node is too busy') from None
        if not job.done.wait(timeout):
            raise TimeoutError(f'the call did not finish in {timeout:g} s')
        if job.error is not None:
            raise job.error
        return job.result

    def stop(self, timeout: float = 1.0) -> None:
        """No more jobs; the worker ends after the queued ones (a stuck one is abandoned)."""
        self._stopped = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if not self.on_worker():
            self._thread.join(timeout)
