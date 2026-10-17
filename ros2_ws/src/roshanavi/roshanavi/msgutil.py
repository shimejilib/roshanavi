"""Message type helpers: resolve / template / build / display.

All functions raise :class:`MsgUtilError` with a machine readable ``code`` and a
message that includes the offending field path where applicable.
"""

import array
import logging
import math
import re
import time
from typing import Any, Dict, List, Mapping, Optional

from builtin_interfaces.msg import Time
from rosidl_runtime_py import get_message_interfaces, message_to_ordereddict, set_message_fields
from rosidl_runtime_py.utilities import get_message

LOG = logging.getLogger(__name__)

DEFAULT_MAX_ARRAY = 32
DEFAULT_MAX_STR = 1024

_TYPE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*/(msg/)?[A-Za-z][A-Za-z0-9_]*$')


class MsgUtilError(ValueError):
    """Error with a short ``code`` (unknown_type / invalid_field / invalid_value)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_type_name(type_name: str) -> str:
    """Accept ``pkg/Name`` or ``pkg/msg/Name`` and return ``pkg/msg/Name``."""
    if not isinstance(type_name, str) or not _TYPE_RE.match(type_name):
        raise MsgUtilError('unknown_type', f'invalid message type name: {type_name!r}')
    pkg, *_, name = type_name.split('/')
    return f'{pkg}/msg/{name}'


def resolve_type(type_name: str) -> type:
    """Return the Python message class for ``type_name``."""
    normalized = normalize_type_name(type_name)
    try:
        return get_message(normalized)
    except (AttributeError, ModuleNotFoundError, ValueError) as exc:
        raise MsgUtilError('unknown_type',
                           f'cannot resolve message type {normalized}: {exc}') from exc


def list_types() -> List[str]:
    """All message types installed in the current environment, sorted."""
    result = []
    for pkg, names in get_message_interfaces().items():
        result.extend(f'{pkg}/{n}' for n in names if n.startswith('msg/'))
    return sorted(result)


def template(type_name: str) -> Dict[str, Any]:
    """Default-valued instance of ``type_name`` as a JSON-friendly dict."""
    cls = resolve_type(type_name)
    return _jsonable(message_to_ordereddict(cls()), None, None)


def wall_time_msg() -> Time:
    ns = time.time_ns()
    return Time(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)


def build(type_name: str, values: Optional[Mapping[str, Any]],
          stamp: Optional[Time] = None) -> Any:
    """Create a message of ``type_name`` populated from ``values``.

    ``header: "auto"`` and Time fields set to ``"now"`` are filled with
    ``stamp`` (default: current wall-clock time).
    """
    cls = resolve_type(type_name)
    msg = cls()
    if values is None:
        return msg
    if not isinstance(values, Mapping):
        raise MsgUtilError('invalid_value',
                           f'payload must be a mapping, got {type(values).__name__}')
    setters: List[Any] = []
    _fill(msg, values, '', setters)
    if setters:
        now = stamp if stamp is not None else wall_time_msg()
        for setter in setters:
            setter(now)
    return msg


def _fill(msg: Any, values: Mapping[str, Any], prefix: str, setters: List[Any]) -> None:
    fields = msg.get_fields_and_field_types()
    for key, value in values.items():
        path = f'{prefix}{key}'
        if key not in fields:
            raise MsgUtilError(
                'invalid_field',
                f'{path}: no such field in {type(msg).__name__} (fields: {", ".join(fields)})')
        current = getattr(msg, key)
        if isinstance(value, Mapping) and hasattr(current, 'get_fields_and_field_types'):
            _fill(current, value, f'{path}.', setters)
            continue
        try:
            setters.extend(set_message_fields(msg, {key: value}, expand_header_auto=True,
                                              expand_time_now=True))
        except (AttributeError, TypeError, ValueError, AssertionError, OverflowError) as exc:
            raise MsgUtilError(
                'invalid_value',
                f'{path}: cannot assign {value!r} to field of type {fields[key]}: {exc}') from exc


def to_display(msg: Any, max_array: int = DEFAULT_MAX_ARRAY,
               max_str: int = DEFAULT_MAX_STR) -> Dict[str, Any]:
    """Message -> JSON-safe dict with long arrays/strings truncated.

    Arrays longer than ``max_array`` become
    ``{"_truncated": true, "length": N, "head": [...first max_array...]}``.
    """
    return _jsonable(message_to_ordereddict(msg), max_array, max_str)


def to_plain(msg: Any) -> Dict[str, Any]:
    """Message -> plain dict (nothing truncated): function nodes in 詳細設定モード."""
    return _jsonable(message_to_ordereddict(msg), None, None)


def _jsonable(value: Any, max_array: Optional[int], max_str: Optional[int]) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v, max_array, max_str) for k, v in value.items()}
    if isinstance(value, (bytes, bytearray)):
        value = list(value)
    elif isinstance(value, array.array) or hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        if max_array is not None and len(value) > max_array:
            head = [_jsonable(v, max_array, max_str) for v in value[:max_array]]
            return {'_truncated': True, 'length': len(value), 'head': head}
        return [_jsonable(v, max_array, max_str) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # JSON has no NaN/Infinity
    if isinstance(value, str) and max_str is not None and len(value) > max_str:
        return value[:max_str] + f'...(+{len(value) - max_str} chars)'
    return value
