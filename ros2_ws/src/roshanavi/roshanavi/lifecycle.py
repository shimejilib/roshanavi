"""Lifecycle (managed) nodes: read the state and request transitions (docs/design/launcher.md).

Uses only the ROS-official lifecycle services every managed node offers
(``<node>/get_state``, ``get_available_transitions``, ``change_state`` from
lifecycle_msgs), so it works for nodes roshanavi did not start: no process is
ever signalled. Only configure / activate / deactivate / cleanup are offered;
shutdown (irreversible) is not.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from lifecycle_msgs.msg import Transition
from lifecycle_msgs.srv import ChangeState, GetAvailableTransitions, GetState

from .api_errors import ApiError
from .params import check_node_name
from .ros_runtime import RosRuntime
from .service_call import ServiceCaller, ServiceErrors

LOG = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = ('configure', 'activate', 'deactivate', 'cleanup')
GOALS = ('active', 'inactive')
QUERY_TIMEOUT_SEC = 2.0
CHANGE_TIMEOUT_SEC = 10.0  # on_configure may do real work
STATE_CACHE_SEC = 1.5
STATE_POLL_TIMEOUT_SEC = 1.0
MAX_PARALLEL = 8
LIFECYCLE_ERRORS = ServiceErrors('lifecycle_unavailable', 'lifecycle_timeout',
                                 'lifecycle_call_failed', 'lifecycle')


def plan_goal(state: str, goal: str) -> List[str]:
    """Transitions that bring a node from ``state`` to ``goal`` ('active' / 'inactive')."""
    if goal == 'active':
        return {'unconfigured': ['configure', 'activate'], 'inactive': ['activate']}.get(state, [])
    if goal == 'inactive':
        return ['deactivate'] if state == 'active' else []
    raise ApiError('invalid_lifecycle_goal', f'goal must be one of {list(GOALS)}')


class LifecycleService:
    """Thread-safe lifecycle client used by the API and the node list."""

    def __init__(self, runtime: RosRuntime, timeout_sec: float = QUERY_TIMEOUT_SEC,
                 change_timeout_sec: float = CHANGE_TIMEOUT_SEC,
                 clock: Callable[[], float] = time.monotonic):
        self._caller = ServiceCaller(runtime, LIFECYCLE_ERRORS, timeout_sec)
        self._change_timeout = change_timeout_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL,
                                        thread_name_prefix='lifecycle')

    def state(self, node: str, timeout_sec: Optional[float] = None) -> Dict[str, Any]:
        check_node_name(node)
        result = self._caller.call(node, 'get_state', GetState, GetState.Request(),
                                   timeout_sec)
        state = {'id': int(result.current_state.id), 'label': result.current_state.label}
        self._remember(node, state['label'])
        return state

    def transitions(self, node: str) -> List[Dict[str, Any]]:
        result = self._caller.call(node, 'get_available_transitions', GetAvailableTransitions,
                                   GetAvailableTransitions.Request())
        seen, items = set(), []
        for desc in result.available_transitions:
            label = desc.transition.label
            if label in ALLOWED_TRANSITIONS and label not in seen:
                seen.add(label)
                items.append({'id': int(desc.transition.id), 'label': label,
                              'goal': desc.goal_state.label})
        return items

    def info(self, node: str) -> Dict[str, Any]:
        return {'node': node, 'state': self.state(node), 'transitions': self.transitions(node)}

    def change(self, node: str, label: str) -> Dict[str, Any]:
        """Run one allowed transition by label; returns the new :meth:`info`."""
        check_node_name(node)
        if label not in ALLOWED_TRANSITIONS:
            raise ApiError('invalid_lifecycle_transition',
                           f'transition must be one of {list(ALLOWED_TRANSITIONS)}')
        available = {t['label']: t['id'] for t in self.transitions(node)}
        if label not in available:
            state = self.state(node)['label']
            raise ApiError('lifecycle_transition_unavailable',
                           f'{label} is not possible while {node} is {state}', 409)
        request = ChangeState.Request(transition=Transition(id=available[label], label=label))
        result = self._caller.call(node, 'change_state', ChangeState, request,
                                   self._change_timeout)
        if not result.success:
            raise ApiError('lifecycle_transition_failed', f'{node} refused {label}', 409)
        LOG.info('lifecycle %s: %s', node, label)
        return self.info(node)

    def reach(self, node: str, goal: str) -> Dict[str, Any]:
        """Run the transitions to ``goal`` (bulk ON / OFF); a no-op when already there."""
        steps = plan_goal(self.state(node)['label'], goal)
        info = None
        for label in steps:
            info = self.change(node, label)
        return {**(info or self.info(node)), 'steps': steps}

    # ---- cached states for the node list ----------------------------------
    def _remember(self, node: str, label: Optional[str]) -> None:
        with self._lock:
            self._cache[node] = (self._clock(), label)

    def _cached(self, node: str) -> Tuple[bool, Optional[str]]:
        with self._lock:
            entry = self._cache.get(node)
        if entry and self._clock() - entry[0] < STATE_CACHE_SEC:
            return True, entry[1]
        return False, None

    def _poll(self, node: str) -> Optional[str]:
        try:
            return self.state(node, STATE_POLL_TIMEOUT_SEC)['label']
        except ApiError as exc:
            LOG.debug('lifecycle state of %s unavailable: %s', node, exc)
            self._remember(node, None)
            return None

    def states(self, nodes: Iterable[str]) -> Dict[str, Optional[str]]:
        """``{node: state label or None}``, querying in parallel (cached briefly)."""
        result: Dict[str, Optional[str]] = {}
        pending = []
        for node in nodes:
            hit, label = self._cached(node)
            if hit:
                result[node] = label
            else:
                pending.append(node)
        for node, label in zip(pending, self._pool.map(self._poll, pending)):
            result[node] = label
        return result

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._caller.close()
