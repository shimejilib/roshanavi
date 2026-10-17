"""Call an action method of a running class node from outside (UI button, scenario step).

The way in is the topic ``/<node>/<method>`` (``std_msgs/Empty``), the same one ``ros2 topic pub``
uses, so every caller exercises the real path. The node records every call in its status
(count, time, result, error); the caller waits for the count to grow so it can report the outcome.
"""

import time
from typing import Any, Callable, Dict, Optional

from ..injector import Injector
from ..jobs import InjectError, InjectSpec

EMPTY_TYPE = 'std_msgs/msg/Empty'
DISCOVERY_SEC = 3.0
POLL_SEC = 0.05

Record = Optional[Dict[str, Any]]


class ActionCallError(Exception):
    """The call could not be made or did not run (a message for the user)."""


def full_node_name(name: str, namespace: Optional[str] = None) -> str:
    if name.startswith('/'):
        return name
    ns = (namespace or '').strip('/')
    return f'/{ns}/{name}' if ns else f'/{name}'


def action_topic(name: str, namespace: Optional[str], method: str) -> str:
    return f'{full_node_name(name, namespace)}/{method}'


def call_action(injector: Injector, has_subscriber: Callable[[str], bool], topic: str,
                read_record: Callable[[], Record], timeout: float = 5.0,
                tick: Callable[[], None] = lambda: None) -> Record:
    """Publish one Empty to ``topic`` and wait until the node has run it.

    ``read_record`` returns the action's status record (None when the node's status cannot be
    read: then the call is only sent and the result is None). Raises ActionCallError."""
    deadline = time.monotonic() + DISCOVERY_SEC
    while not has_subscriber(topic):
        if time.monotonic() >= deadline:
            raise ActionCallError(
                f'{topic} を受け取るノードが見つかりません。ノードが動いているか、メソッドを'
                '「操作メソッド」に指定したか確認してください')
        tick()
        time.sleep(POLL_SEC)
    before = read_record()
    count_before = (before or {}).get('count', 0)
    try:
        injector.start(InjectSpec(mode='once', topic=topic, type=EMPTY_TYPE, payload={}))
    except InjectError as exc:
        raise ActionCallError(f'{topic} に送れませんでした: {exc}') from exc
    if before is None:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = read_record()
        if record is not None and record.get('count', 0) > count_before:
            return record
        tick()
        time.sleep(POLL_SEC)
    raise ActionCallError(f'{topic} に送りましたが、{timeout:g} 秒待っても呼ばれた形跡がありません '
                          '(別のメソッドの処理が長引いているのかもしれません)')
