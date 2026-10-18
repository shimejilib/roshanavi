"""Delete several registry entries at once, with a short undo (node list 「削除」).

Only roshanavi's own registrations can be deleted (launcher targets, imported ones
included, input / transform / function / class nodes, persistent dummies): the entry is
removed from the project and its processes are stopped. Source code, packages, parameter
files and recordings are never touched, so 「元に戻す」 can register the same specs again
and start the ones that were running.
"""

import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Sequence, Tuple

from .errors import LauncherError
from .target import Spec, kind_of

UNDO_TTL_SEC = 15.0  # the UI offers 「元に戻す」 for 10 s; a little slack for slow requests
MAX_UNDO = 8
MAX_DELETE = 200


class Trash:
    def __init__(self, launcher: Any, ttl_sec: float = UNDO_TTL_SEC,
                 clock: Callable[[], float] = time.monotonic):
        self._launcher = launcher
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: 'OrderedDict[str, Tuple[float, List[Tuple[Spec, bool]]]]' = OrderedDict()

    def delete(self, ids: Sequence[str]) -> Dict[str, Any]:
        unique = list(dict.fromkeys(ids))
        if not unique or len(unique) > MAX_DELETE:
            raise LauncherError('invalid_request', f'give 1..{MAX_DELETE} ids to delete')
        manager = self._launcher.manager
        targets = [manager.target(target_id) for target_id in unique]  # 404 before any change
        kept: List[Tuple[Spec, bool]] = []
        removed: List[Dict[str, Any]] = []
        for target in targets:
            running = target.alive()
            self._launcher.remove(target.id)
            kept.append((target.spec, running))
            removed.append({'id': target.id, 'kind': kind_of(target.spec), 'was_running': running})
        undo_id = uuid.uuid4().hex
        with self._lock:
            self._expire()
            self._kept[undo_id] = (self._clock(), kept)
            while len(self._kept) > MAX_UNDO:
                self._kept.popitem(last=False)
        return {'removed': removed, 'undo_id': undo_id, 'undo_sec': self._ttl}

    def undo(self, undo_id: str) -> Dict[str, Any]:
        with self._lock:
            self._expire()
            entry = self._kept.pop(undo_id, None)
        if entry is None:
            raise LauncherError('undo_expired', 'it is too late to undo this deletion', 404)
        restored, started, errors = [], [], []
        manager = self._launcher.manager
        for spec, running in entry[1]:
            try:
                manager.add(spec, strict=False)  # as when a project loads: never lost
                restored.append(spec.id)
                if running:
                    manager.start(spec.id)
                    started.append(spec.id)
            except LauncherError as exc:
                errors.append({'id': spec.id, 'code': exc.code, 'message': str(exc)})
        self._launcher.autosave()
        return {'restored': restored, 'started': started, 'errors': errors}

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, (t, _) in self._kept.items() if now - t > self._ttl]:
            del self._kept[key]
