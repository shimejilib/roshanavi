"""The disposable chunk-parser child (issue #17), with a fake reader (no bt2 / lttng needed).

The fake child reads "chunk paths" of the form ``<n>`` (yield n events), ``fail``
(raise inside the reader), ``crash`` (exit the process), ``hang`` (sleep) and
``leak`` (open a file and never close it, like bt2's metadata handle).
"""

import os
import sys
import textwrap
import time

import pytest

from roshanavi.tracing.chunk_parser import ChunkParseError, ChunkParser
from roshanavi.tracing.reader import ChunkInfo

FAKE_CHILD = textwrap.dedent('''
    import os, sys, time
    from roshanavi.tracing.chunk_parser import child_main
    LEAKED = []
    def reader(path, info):
        if path == 'fail':
            raise ValueError('bad chunk')
        if path == 'crash':
            os._exit(3)
        if path == 'hang':
            time.sleep(60)
        if path == 'leak':
            LEAKED.append(open(os.devnull))
            path = '1'
        for i in range(int(path)):
            info.events += 1
            yield (1, i, 42, 'x' * (i % 3), True)
        info.discarded = 7
    sys.exit(child_main(reader))
''')


def _parser(**kwargs):
    return ChunkParser(argv=[sys.executable, '-c', FAKE_CHILD], **kwargs)


def _fds(pid):
    return len(os.listdir(f'/proc/{pid}/fd'))


def test_events_stream_in_order_across_frames_with_counts():
    parser = _parser()
    try:
        info = ChunkInfo()
        events = list(parser.parse('5000', info))  # > one frame (2048 events)
        assert len(events) == 5000 and events[0] == (1, 0, 42, '', True)
        assert [e[1] for e in events] == list(range(5000))
        assert (info.events, info.discarded) == (5000, 7)
        assert list(parser.parse('0', ChunkInfo())) == []
    finally:
        parser.close()


def test_reader_error_is_raised_and_the_child_keeps_serving():
    parser = _parser()
    try:
        with pytest.raises(ChunkParseError, match='bad chunk'):
            list(parser.parse('fail', ChunkInfo()))
        assert len(list(parser.parse('3', ChunkInfo()))) == 3
    finally:
        parser.close()


def test_crashed_child_is_replaced():
    parser = _parser()
    try:
        list(parser.parse('1', ChunkInfo()))
        first = parser.pid
        with pytest.raises(ChunkParseError, match='exited'):
            list(parser.parse('crash', ChunkInfo()))
        assert len(list(parser.parse('2', ChunkInfo()))) == 2
        assert parser.pid != first and parser.children_started == 2
    finally:
        parser.close()


def test_hung_child_times_out_and_is_killed():
    parser = _parser(frame_timeout=0.5)
    try:
        started = time.monotonic()
        with pytest.raises(ChunkParseError, match='no output'):
            list(parser.parse('hang', ChunkInfo()))
        assert time.monotonic() - started < 5.0
        assert parser.pid is None
        assert len(list(parser.parse('1', ChunkInfo()))) == 1
    finally:
        parser.close()


def test_stopping_early_does_not_desync_the_next_chunk():
    parser = _parser()
    try:
        gen = parser.parse('5000', ChunkInfo())
        next(gen)
        gen.close()  # the caller gave up mid-chunk: the child is dropped
        assert [e[1] for e in parser.parse('3', ChunkInfo())] == [0, 1, 2]
    finally:
        parser.close()


def test_child_is_recycled_so_leaked_descriptors_stay_bounded():
    recycle = 4
    parser = _parser(recycle_every=recycle)
    own_before = _fds(os.getpid())
    try:
        pids, child_fds = set(), []
        for _ in range(recycle * 5):
            list(parser.parse('leak', ChunkInfo()))
            pids.add(parser.pid)
            child_fds.append(_fds(parser.pid))
        assert len(pids) == 5 and parser.children_started == 5
        # Each child leaks one fd per chunk, at most `recycle` before it is replaced.
        assert max(child_fds) - min(child_fds) <= recycle - 1, child_fds
        assert _fds(os.getpid()) <= own_before + 3  # only the current child's two pipes
    finally:
        parser.close()
    assert _fds(os.getpid()) <= own_before


def test_newline_in_path_is_rejected():
    parser = _parser()
    try:
        with pytest.raises(ChunkParseError):
            list(parser.parse('1\n2', ChunkInfo()))
    finally:
        parser.close()
