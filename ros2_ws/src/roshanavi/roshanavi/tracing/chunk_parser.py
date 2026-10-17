"""Parse rotated trace chunks in a disposable child process (issue #17).

babeltrace2 2.0.x opens each chunk's ``metadata`` file from C code and never
closes it. Closing that descriptor behind bt2's back (the former workaround)
risks closing an unrelated file later, when bt2 closes the same number. So
chunks are parsed in a child process instead, and the child is replaced every
:data:`RECYCLE_EVERY` chunks: whatever bt2 leaks dies with the process, and the
worker itself never holds a bt2 handle.

Child protocol (``python3 -m roshanavi.tracing.chunk_parser``):

* stdin: one chunk path per line; EOF ends the child.
* the original stdout carries length-prefixed ``marshal`` frames (fd 1 is
  pointed at stderr so stray prints cannot corrupt them):
  ``('events', [event, ...])`` any number of times, then
  ``('done', events, discarded, error_or_None)``.

The parent (:class:`ChunkParser`) streams the events to the caller as they
arrive. A child that dies, hangs (no frame for :data:`FRAME_TIMEOUT_SEC`) or
desynchronises is killed and replaced on the next chunk.
"""

import gc
import marshal
import os
import select
import struct
import subprocess
import sys
from typing import Any, Callable, IO, Iterator, List, Optional, Tuple

from .reader import ChunkInfo, Event, read_chunk

RECYCLE_EVERY = 32         # chunks per child: bounds what bt2 leaks (one metadata fd per chunk)
FRAME_TIMEOUT_SEC = 30.0   # no frame for this long: the child is stuck
BATCH = 2048               # events per frame
MAX_FRAME_BYTES = 64 * 1024 * 1024
_HEADER = struct.Struct('>I')
_CLK_TCK = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100


class ChunkParseError(RuntimeError):
    """The chunk could not be parsed (bt2 error, or the child failed)."""


# ---- child -----------------------------------------------------------------------------
def _write_frame(out: IO[bytes], obj: Any) -> None:
    data = marshal.dumps(obj)
    out.write(_HEADER.pack(len(data)) + data)
    out.flush()


def _parse_one(path: str, out: IO[bytes],
               reader: Callable[[str, ChunkInfo], Iterator[Event]]) -> None:
    info = ChunkInfo()
    batch: List[Event] = []
    error: Optional[str] = None
    try:
        for event in reader(path, info):
            batch.append(event)
            if len(batch) >= BATCH:
                _write_frame(out, ('events', batch))
                batch = []
    except Exception as exc:  # reported to the parent, which counts a parse error
        error = f'{type(exc).__name__}: {exc}'
    if batch:
        _write_frame(out, ('events', batch))
    _write_frame(out, ('done', info.events, info.discarded, error))
    # The bt2 graph is a reference cycle; collecting it closes the stream files. What bt2
    # itself never closes (the metadata file) goes away with this process.
    gc.collect()


def child_main(reader: Callable[[str, ChunkInfo], Iterator[Event]] = read_chunk) -> int:
    out = os.fdopen(os.dup(1), 'wb')
    os.dup2(2, 1)  # anything printed by bt2 / Python goes to stderr, not into the frames
    sys.stdout = sys.stderr
    for line in sys.stdin:
        path = line.rstrip('\n')
        if not path:
            continue
        try:
            _parse_one(path, out, reader)
        except BrokenPipeError:
            return 0
    return 0


# ---- parent ----------------------------------------------------------------------------
class ChunkParser:
    """Parses chunks through a child process that is replaced every ``recycle_every`` chunks."""

    def __init__(self, recycle_every: int = RECYCLE_EVERY,
                 frame_timeout: float = FRAME_TIMEOUT_SEC,
                 argv: Optional[List[str]] = None):
        self.recycle_every = max(1, recycle_every)
        self.frame_timeout = frame_timeout
        self._argv = argv or [sys.executable, '-m', 'roshanavi.tracing.chunk_parser']
        self._proc: Optional[subprocess.Popen] = None
        self._parsed = 0          # chunks parsed by the current child
        self.children_started = 0
        self._buffer = b''

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None and self._proc.poll() is None else None

    def _spawn(self) -> subprocess.Popen:
        self._buffer = b''
        self._parsed = 0
        self.children_started += 1
        self._proc = subprocess.Popen(self._argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      close_fds=True)
        return self._proc

    def _child(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None \
                and self._parsed < self.recycle_every:
            return self._proc
        self._retire()
        return self._spawn()

    def _retire(self, kill: bool = False) -> None:
        """End the current child (EOF on stdin, or kill) and reap it."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if kill:
                proc.kill()
            elif proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=5.0)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()
        finally:
            for pipe in (proc.stdin, proc.stdout):
                try:
                    if pipe is not None:
                        pipe.close()
                except OSError:
                    pass

    def _read_exact(self, proc: subprocess.Popen, size: int) -> bytes:
        fd = proc.stdout.fileno()
        while len(self._buffer) < size:
            ready, _, _ = select.select([fd], [], [], self.frame_timeout)
            if not ready:
                raise ChunkParseError(f'chunk parser gave no output for {self.frame_timeout:.0f} s')
            data = os.read(fd, max(65536, size - len(self._buffer)))
            if not data:
                raise ChunkParseError(f'chunk parser exited (code {proc.poll()})')
            self._buffer += data
        out, self._buffer = self._buffer[:size], self._buffer[size:]
        return out

    def _frame(self, proc: subprocess.Popen) -> Tuple[Any, ...]:
        (size,) = _HEADER.unpack(self._read_exact(proc, _HEADER.size))
        if size > MAX_FRAME_BYTES:
            raise ChunkParseError(f'chunk parser frame too large ({size} bytes)')
        frame = marshal.loads(self._read_exact(proc, size))
        if not isinstance(frame, tuple) or not frame:
            raise ChunkParseError('chunk parser sent a malformed frame')
        return frame

    def parse(self, path: str, info: ChunkInfo) -> Iterator[Event]:
        """Yield the chunk's events (same tuples as :func:`reader.read_chunk`).

        Raises :class:`ChunkParseError` when bt2 cannot read the chunk or the child
        fails; the child is then replaced on the next call.
        """
        if '\n' in path:
            raise ChunkParseError('chunk path contains a newline')
        proc = self._child()
        self._parsed += 1
        finished = False
        try:
            try:
                proc.stdin.write(path.encode() + b'\n')
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise ChunkParseError(f'chunk parser is gone: {exc}') from exc
            while True:
                frame = self._frame(proc)
                if frame[0] == 'events':
                    yield from frame[1]
                    continue
                if frame[0] != 'done' or len(frame) != 4:
                    raise ChunkParseError('chunk parser sent an unknown frame')
                _, info.events, info.discarded, error = frame
                finished = True
                if error:
                    raise ChunkParseError(error)
                return
        finally:
            if not finished:  # the caller stopped early or the child failed: start fresh
                self._retire(kill=True)

    def cpu_seconds(self) -> float:
        """CPU time of the live child (reaped children count in RUSAGE_CHILDREN)."""
        pid = self.pid
        if pid is None:
            return 0.0
        try:
            with open(f'/proc/{pid}/stat', encoding='ascii') as fh:
                fields = fh.read().rsplit(')', 1)[1].split()
            return (int(fields[11]) + int(fields[12])) / _CLK_TCK
        except (OSError, IndexError, ValueError):
            return 0.0

    def close(self) -> None:
        self._retire()


if __name__ == '__main__':
    sys.exit(child_main())
