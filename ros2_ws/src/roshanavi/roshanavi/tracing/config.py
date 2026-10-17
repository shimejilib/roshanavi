"""Event selection, channel sizing and filters for the tracing sessions (pure).

Two sessions per server (docs/design/measurement.md):

* **init** — from server start while LTTng is available: only the events a
  node emits once when it creates nodes / subscriptions / publishers. Nothing
  is recorded per message, so the target nodes pay nothing; it lets roshanavi
  map later per-message events to nodes and topics without restarting them.
* **rt** — only while 詳細計測モード is on: per-message events (take,
  callback start / end, publish), created on enable and destroyed on disable
  so its ring buffers exist only while measuring.
"""

import math
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional

INIT_EVENTS = (
    'ros2:rcl_node_init',
    'ros2:rcl_subscription_init',
    'ros2:rclcpp_subscription_init',
    'ros2:rclcpp_subscription_callback_added',
    'ros2:rclcpp_callback_register',
    'ros2:rcl_publisher_init',
)
TAKE_EVENT = 'ros2:rmw_take'
RT_EVENTS = ('ros2:callback_start', 'ros2:callback_end', 'ros2:rmw_publish')
INIT_CONTEXTS = ('vpid', 'procname')
RT_CONTEXTS = ('vpid', 'vtid')

KIB = 1024
MIB = 1024 * KIB
PAGE = 4 * KIB
DEFAULT_RT_PER_CPU = 4 * MIB      # docs/design/measurement.md: "CPU 1 個あたり 4 MiB"
RT_SUBBUF_COUNT = 4
INIT_SUBBUF = 64 * KIB            # node start bursts: ~40 events x ~150 B per node
INIT_SUBBUF_COUNT = 2
SHM_SHARE = 0.5                   # never plan more than half of the free /dev/shm


class ShmTooSmall(Exception):
    """/dev/shm cannot hold even the smallest ring buffers."""


@dataclass(frozen=True)
class ChannelSize:
    subbuf_bytes: int
    subbuf_count: int

    @property
    def per_cpu(self) -> int:
        return self.subbuf_bytes * self.subbuf_count


def _floor_pow2(value: int) -> int:
    return 1 << int(math.floor(math.log2(value))) if value >= 1 else 0


def possible_cpus(path: str = '/sys/devices/system/cpu/possible') -> int:
    """LTTng allocates one buffer per *possible* CPU (e.g. ``0-23`` -> 24)."""
    try:
        with open(path, encoding='ascii') as handle:
            text = handle.read().strip()
    except OSError:
        return os.cpu_count() or 1
    total = 0
    for part in text.split(','):
        lo, _, hi = part.partition('-')
        total += (int(hi) - int(lo) + 1) if hi else 1
    return max(total, 1)


def rt_channel_size(cpus: int, shm_free: Optional[int],
                    wanted_per_cpu: int = DEFAULT_RT_PER_CPU) -> ChannelSize:
    """Per-CPU buffer for the rt channel, shrunk to fit ``SHM_SHARE`` of free /dev/shm.

    Docker's default /dev/shm is 64 MB: 4 MiB x 24 CPUs would not fit, and
    LTTng then silently records nothing. Sub-buffers are powers of two >= 4 KiB.
    """
    per_cpu = wanted_per_cpu
    if shm_free is not None:
        budget = int(shm_free * SHM_SHARE) - INIT_SUBBUF * INIT_SUBBUF_COUNT * cpus
        per_cpu = min(per_cpu, budget // max(cpus, 1))
    subbuf = _floor_pow2(per_cpu // RT_SUBBUF_COUNT)
    if subbuf >= PAGE:
        return ChannelSize(subbuf, RT_SUBBUF_COUNT)
    if per_cpu >= 2 * PAGE:
        return ChannelSize(PAGE, 2)
    raise ShmTooSmall(f'/dev/shm has {shm_free} bytes free; need {2 * PAGE * cpus}')


def init_channel_size() -> ChannelSize:
    return ChannelSize(INIT_SUBBUF, INIT_SUBBUF_COUNT)


def exclude_filter(pids: Iterable[int]) -> Optional[str]:
    """LTTng filter that drops roshanavi's own processes (server, probe) at the source."""
    unique = sorted({int(p) for p in pids if p})
    if not unique:
        return None
    return ' && '.join(f'$ctx.vpid != {p}' for p in unique)


def take_filter(pids: Iterable[int]) -> str:
    """Only successful takes (``taken == 1``); ``rmw_take`` also fires for empty polls."""
    rest = exclude_filter(pids)
    return 'taken == 1' if rest is None else f'taken == 1 && {rest}'


def session_name(prefix: str, kind: str) -> str:
    return f'{prefix}-{kind}'


def stale_owner_pid(name: str, prefix_root: str = 'roshanavi') -> Optional[int]:
    """Server pid encoded in ``roshanavi-<pid>-<id>-<kind>``, or None for foreign names."""
    parts: List[str] = name.split('-')
    if len(parts) < 4 or parts[0] != prefix_root or not parts[1].isdigit():
        return None
    return int(parts[1])
