"""Adapter registry keyed by ROS message type.

Built-in adapters are registered only when their message package is
installed (``audio_common_msgs`` is optional). Third-party adapters are
discovered through the ``roshanavi.adapters`` entry-point group; an entry point
may resolve to a :class:`MediaAdapter` subclass, an instance, or a callable
returning one or a list of them::

    # setup.py of your package
    entry_points={'roshanavi.adapters': ['my_cam = my_pkg.roshanavi_adapter:MyAdapter']}
"""

import logging
import threading
from importlib import metadata
from typing import Any, Dict, Iterable, List, Optional

from ... import msgutil
from ..errors import MediaError
from .audio import (AudioDataAdapter, AudioDataStampedAdapter, Float32ArrayAdapter,
                    Int16ArrayAdapter, UInt8ArrayAdapter)
from .base import MediaAdapter
from .image import CompressedImageAdapter, ImageAdapter

LOG = logging.getLogger(__name__)

ENTRY_POINT_GROUP = 'roshanavi.adapters'
BUILTIN = (ImageAdapter, CompressedImageAdapter, AudioDataAdapter, AudioDataStampedAdapter,
           Int16ArrayAdapter, UInt8ArrayAdapter, Float32ArrayAdapter)

_lock = threading.Lock()
_registry: Dict[str, MediaAdapter] = {}
_loaded = False


def register(adapter: MediaAdapter) -> bool:
    """Add an adapter if its message type can be imported. Returns True when added."""
    if not isinstance(adapter, MediaAdapter) or not adapter.type_name:
        LOG.warning('ignoring invalid media adapter %r', adapter)
        return False
    try:
        msgutil.resolve_type(adapter.type_name)
    except msgutil.MsgUtilError as exc:
        LOG.info('media adapter for %s disabled: %s', adapter.type_name, exc)
        return False
    with _lock:
        _registry[msgutil.normalize_type_name(adapter.type_name)] = adapter
    return True


def _instances(obj: Any) -> Iterable[Any]:
    if isinstance(obj, type) and issubclass(obj, MediaAdapter):
        return [obj()]
    if isinstance(obj, MediaAdapter):
        return [obj]
    if callable(obj):
        made = obj()
        return made if isinstance(made, (list, tuple)) else [made]
    return [obj]


def load_plugins(entry_points: Optional[Iterable[Any]] = None) -> List[str]:
    """Register adapters from the entry-point group; returns the added type names."""
    if entry_points is None:
        try:
            entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
        except Exception as exc:  # broken metadata must not take the server down
            LOG.warning('cannot list %s entry points: %s', ENTRY_POINT_GROUP, exc)
            return []
    added = []
    for ep in entry_points:
        try:
            for adapter in _instances(ep.load()):
                if register(adapter):
                    added.append(adapter.type_name)
        except Exception:
            LOG.exception('media adapter plugin %s failed to load', getattr(ep, 'name', ep))
    return added


def _ensure_loaded() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
    for cls in BUILTIN:
        register(cls())
    plugins = load_plugins()
    if plugins:
        LOG.info('media adapter plugins: %s', ', '.join(plugins))


def supported() -> List[Dict[str, str]]:
    _ensure_loaded()
    with _lock:
        return [{'type': name, 'kind': a.kind} for name, a in sorted(_registry.items())]


def get(type_name: str) -> MediaAdapter:
    """The adapter for ``type_name`` or a plain-language MediaError."""
    _ensure_loaded()
    try:
        key = msgutil.normalize_type_name(type_name)
    except msgutil.MsgUtilError as exc:
        raise MediaError('media_type_unsupported', str(exc)) from exc
    with _lock:
        adapter = _registry.get(key)
    if adapter is None:
        names = ', '.join(t['type'] for t in supported())
        raise MediaError('media_type_unsupported',
                         f'{key} cannot be made from media files or the browser. Supported: '
                         f'{names}. For other types, record or prepare a bag and use bag mode.')
    return adapter
