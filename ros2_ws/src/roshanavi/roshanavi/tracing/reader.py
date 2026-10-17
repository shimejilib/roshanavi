"""Read one rotated trace chunk with babeltrace2 (``python3-bt2``) into compact tuples.

Only the fields the model needs are copied out of each event, as plain
tuples (``model.K_*`` first): converting bt2 field objects is the dominant
cost (~13 µs / event measured), so nothing else is touched.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Tuple

from . import model as m

Event = Tuple[Any, ...]


@dataclass
class ChunkInfo:
    events: int = 0
    discarded: int = 0  # from the CTF packet counters (bt2 DiscardedEvents messages)


def bt2_available() -> bool:
    try:
        import bt2  # noqa: F401  (python3-bt2)
    except ImportError:
        return False
    return True


def _node(p: Any) -> tuple:
    return (int(p['node_handle']), str(p['node_name']), str(p['namespace']))


def _rcl_sub(p: Any) -> tuple:
    return (int(p['subscription_handle']), int(p['node_handle']),
            int(p['rmw_subscription_handle']), str(p['topic_name']))


def _cpp_sub(p: Any) -> tuple:
    return (int(p['subscription_handle']), int(p['subscription']))


def _cb_added(p: Any) -> tuple:
    return (int(p['subscription']), int(p['callback']))


def _cb_register(p: Any) -> tuple:
    return (int(p['callback']), str(p['symbol'])[:m.SYMBOL_MAX])


def _rcl_pub(p: Any) -> tuple:
    return (int(p['publisher_handle']), int(p['node_handle']),
            int(p['rmw_publisher_handle']), str(p['topic_name']))


# name -> (kind, payload extractor); per-message events are inlined in read_chunk.
_INIT: Dict[str, Tuple[int, Callable[[Any], tuple]]] = {
    'ros2:rcl_node_init': (m.K_NODE, _node),
    'ros2:rcl_subscription_init': (m.K_RCL_SUB, _rcl_sub),
    'ros2:rclcpp_subscription_init': (m.K_CPP_SUB, _cpp_sub),
    'ros2:rclcpp_subscription_callback_added': (m.K_CB_ADDED, _cb_added),
    'ros2:rclcpp_callback_register': (m.K_CB_REGISTER, _cb_register),
    'ros2:rcl_publisher_init': (m.K_RCL_PUB, _rcl_pub),
}


def read_chunk(path: str, info: ChunkInfo) -> Iterator[Event]:
    """Yield ``(kind, ts_ns, vpid, ...)`` for every known event of the chunk at ``path``.

    ``ts_ns`` is the raw CLOCK_MONOTONIC value (LTTng-UST's default clock).
    Unreadable chunks raise ``bt2`` errors; the caller drops the chunk.
    """
    import bt2
    event_msg = bt2._EventMessageConst
    discarded_msg = bt2._DiscardedEventsMessageConst
    iterator = bt2.TraceCollectionMessageIterator(path)
    msg = ev = ctx = p = None
    try:
        for msg in iterator:
            kind = type(msg)
            if kind is discarded_msg:
                info.discarded += msg.count or 0
                continue
            if kind is not event_msg:
                continue
            ev = msg.event
            name = ev.name
            ts = msg.default_clock_snapshot.value
            ctx = ev.common_context_field
            pid = int(ctx['vpid'])
            p = ev.payload_field
            info.events += 1
            if name == 'ros2:rmw_take':
                yield (m.K_TAKE, ts, pid, int(p['rmw_subscription_handle']))
            elif name == 'ros2:callback_start':
                yield (m.K_CB_START, ts, pid, int(ctx['vtid']), int(p['callback']),
                       bool(p['is_intra_process']))
            elif name == 'ros2:callback_end':
                yield (m.K_CB_END, ts, pid, int(ctx['vtid']), int(p['callback']))
            elif name == 'ros2:rmw_publish':
                yield (m.K_PUBLISH, ts, pid, int(p['rmw_publisher_handle']))
            else:
                known = _INIT.get(name)
                if known is not None:
                    procname = str(ctx['procname']) if 'procname' in ctx else ''
                    yield (known[0], ts, pid, procname, *known[1](p))
    finally:
        # The bt2 iterator owns a graph whose listeners point back at it (a reference
        # cycle), so refcounting never frees it. Drop our references; the chunk parser
        # child (chunk_parser.py) collects the cycle after each chunk, and what bt2 2.0.x
        # never closes itself (the metadata file) goes away with that disposable process.
        msg = ev = ctx = p = iterator = None
