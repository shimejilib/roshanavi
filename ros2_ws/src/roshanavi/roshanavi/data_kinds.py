"""データの種類 (data kinds): the one mapping between beginner-facing kinds and ROS types.

Input nodes, transform nodes, function nodes and the お試し送信 tab let the user pick
a *kind* (文字列, 数値, 画像 ...); the ROS message type is decided here
(docs/design/nodes.md). Function nodes also convert messages to plain Python values and back
with :func:`to_python` / :func:`from_python` (image / audio go through the media
adapters, so there is one conversion per type).

| kind      | ROS type (first installed one)                                   | Python value |
|-----------|------------------------------------------------------------------|--------------|
| string    | std_msgs/msg/String                                              | ``str`` |
| float     | std_msgs/msg/Float64                                             | ``float`` |
| int       | std_msgs/msg/Int64                                               | ``int`` |
| bool      | std_msgs/msg/Bool                                                | ``bool`` |
| numbers   | std_msgs/msg/Float64MultiArray                                   | ``list`` of float |
| json      | std_msgs/msg/String (JSON text)                                  | ``dict`` / ``list`` / ... |
| image     | sensor_msgs/msg/Image                                            | numpy H x W x 3 (rgb8) / H x W (mono8) |
| audio     | audio_common_msgs/msg/AudioDataStamped, else std_msgs/msg/Int16MultiArray | numpy int16 (samples[, channels]) |
| bytes     | std_msgs/msg/UInt8MultiArray                                     | ``bytes`` |
| message   | any type (詳細設定モード)                                           | the message as a plain ``dict`` |

Compatible types (an existing topic of ``std_msgs/msg/Float32`` ...) are shown
and converted as the matching kind but keep their own type.
"""

import array
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

MESSAGE_KIND = 'message'
DEFAULT_SAMPLE_RATE = 16000


class KindError(ValueError):
    """Unknown kind, or a value that does not fit the kind (``code`` for the API)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DataKind:
    id: str
    types: Tuple[str, ...]   # preferred first; the first installed one is used
    python: str              # the Python value a function receives / returns


KINDS: Tuple[DataKind, ...] = (
    DataKind('string', ('std_msgs/msg/String',), 'str'),
    DataKind('float', ('std_msgs/msg/Float64',), 'float'),
    DataKind('int', ('std_msgs/msg/Int64',), 'int'),
    DataKind('bool', ('std_msgs/msg/Bool',), 'bool'),
    DataKind('numbers', ('std_msgs/msg/Float64MultiArray',), 'list[float]'),
    DataKind('json', ('std_msgs/msg/String',), 'dict / list'),
    DataKind('image', ('sensor_msgs/msg/Image',), 'numpy.ndarray (H x W x 3 rgb / H x W mono)'),
    DataKind('audio', ('audio_common_msgs/msg/AudioDataStamped', 'std_msgs/msg/Int16MultiArray'),
             'numpy.ndarray int16'),
    DataKind('bytes', ('std_msgs/msg/UInt8MultiArray',), 'bytes'),
)
KIND_IDS: Tuple[str, ...] = tuple(k.id for k in KINDS)
ALL_KIND_IDS: Tuple[str, ...] = (*KIND_IDS, MESSAGE_KIND)
_BY_ID = {k.id: k for k in KINDS}

# Existing topics of these types are shown / converted as the kind (the type is kept).
_COMPAT: Dict[str, str] = {
    'std_msgs/msg/String': 'string',
    'std_msgs/msg/Float64': 'float', 'std_msgs/msg/Float32': 'float',
    **{f'std_msgs/msg/{n}': 'int' for n in ('Int64', 'Int32', 'Int16', 'Int8', 'UInt64',
                                             'UInt32', 'UInt16')},
    'std_msgs/msg/Bool': 'bool',
    **{f'std_msgs/msg/{n}MultiArray': 'numbers' for n in ('Float64', 'Float32', 'Int64', 'Int32',
                                                         'Int16', 'Int8', 'UInt64', 'UInt32',
                                                         'UInt16')},
    'std_msgs/msg/UInt8MultiArray': 'bytes',
    'std_msgs/msg/ByteMultiArray': 'bytes',
    'sensor_msgs/msg/Image': 'image',
    'audio_common_msgs/msg/AudioDataStamped': 'audio',
    'audio_common_msgs/msg/AudioData': 'audio',
    # Same one-field ``data`` layout as std_msgs. Lyrical's demo_nodes (talker / listener on
    # /chatter) use example_interfaces/msg/String instead of std_msgs/msg/String.
    'example_interfaces/msg/String': 'string',
    'example_interfaces/msg/Float64': 'float', 'example_interfaces/msg/Float32': 'float',
    **{f'example_interfaces/msg/{n}': 'int' for n in ('Int64', 'Int32', 'Int16', 'Int8',
                                                      'UInt64', 'UInt32', 'UInt16')},
    'example_interfaces/msg/Bool': 'bool',
}

# 詳細設定モード: "よく使う型" first, in this order (docs/design/nodes.md).
COMMON_TYPES: Tuple[str, ...] = (
    'std_msgs/msg/String', 'std_msgs/msg/Bool', 'std_msgs/msg/Int32', 'std_msgs/msg/Int64',
    'std_msgs/msg/Float32', 'std_msgs/msg/Float64', 'std_msgs/msg/Header', 'std_msgs/msg/Empty',
    'std_msgs/msg/Float64MultiArray', 'std_msgs/msg/UInt8MultiArray',
    'geometry_msgs/msg/Twist', 'geometry_msgs/msg/Pose', 'geometry_msgs/msg/PoseStamped',
    'sensor_msgs/msg/Image', 'sensor_msgs/msg/LaserScan', 'sensor_msgs/msg/PointCloud2',
    'sensor_msgs/msg/Imu', 'sensor_msgs/msg/JointState',
)


def _normalize(type_name: str) -> str:
    parts = str(type_name).split('/')
    return f'{parts[0]}/msg/{parts[-1]}' if len(parts) >= 2 else str(type_name)


def get(kind_id: str) -> DataKind:
    kind = _BY_ID.get(kind_id)
    if kind is None:
        raise KindError('unknown_kind', f'unknown data kind {kind_id!r} (one of '
                        f'{", ".join(ALL_KIND_IDS)})')
    return kind


def _installed(type_name: str) -> bool:
    from . import msgutil
    try:
        msgutil.resolve_type(type_name)
    except msgutil.MsgUtilError:
        return False
    return True


def ros_type(kind_id: str, installed: Callable[[str], bool] = _installed) -> str:
    """The ROS type used for ``kind_id``: the first of its types that is installed."""
    kind = get(kind_id)
    for name in kind.types:
        if installed(name):
            return name
    return kind.types[-1]


def kind_of_type(type_name: str) -> Optional[str]:
    """The kind an existing topic of ``type_name`` is shown / converted as (None: 専用の型).

    ``std_msgs/msg/String`` is ``string`` (a JSON topic cannot be told apart by type).
    """
    return _COMPAT.get(_normalize(type_name))


def fits(kind_id: str, type_name: str) -> bool:
    """True when ``type_name`` can carry ``kind_id`` (``message`` fits every type)."""
    if kind_id == MESSAGE_KIND:
        return True
    normalized = _normalize(type_name)
    kind = _BY_ID.get(kind_id)
    return kind_of_type(normalized) == kind_id or (kind is not None and normalized in kind.types)


def accepts(kind_id: str, type_name: str) -> bool:
    """True when an *input* port of ``kind_id`` can subscribe to ``type_name``: it fits, or the
    type's kind converts to the port's kind (an integer topic into a 数値 (小数) input, wiring)."""
    if fits(kind_id, type_name):
        return True
    sender = kind_of_type(type_name)
    return sender is not None and (sender, kind_id) in CONVERSIONS


def resolve(kind_id: Optional[str], type_name: Optional[str] = None,
            installed: Callable[[str], bool] = _installed,
            receiving: bool = False) -> Tuple[str, str]:
    """``(kind, type)`` for a port: an explicit type wins (it must fit the kind; an input port
    (``receiving``) may also take a type that converts to its kind, :func:`accepts`)."""
    if kind_id in (None, '', MESSAGE_KIND):
        if not type_name:
            raise KindError('type_required', 'kind "message" needs a ROS message type')
        return MESSAGE_KIND, _normalize(type_name)
    get(kind_id)
    if not type_name:
        return kind_id, ros_type(kind_id, installed)
    normalized = _normalize(type_name)
    if not (accepts if receiving else fits)(kind_id, normalized):
        raise KindError('kind_type_mismatch', f'type {normalized} is not a {kind_id!r} type')
    return kind_id, normalized


# ---- wiring compatibility (map wiring, docs/design/wiring.md) ------------------------------------
# A wire from a sender of kind A (a topic, an output port) into a receiver of kind B (an input
# port, a topic) that is allowed with a conversion; the value is the note code the UI explains.
# The web UI has the same rules (web/src/wiring/compat.ts); both are tested against
# test/data/wire_compat_cases.json.
CONVERSIONS: Dict[Tuple[str, str], str] = {
    ('int', 'float'): 'int_to_float',        # 3 -> 3.0: nothing is lost
    ('string', 'json'): 'string_to_json',    # same ROS type; text that is not JSON is dropped
    ('json', 'string'): 'json_to_string',    # the JSON text as it is
}
# Refused pairs with their own reason (everything else that differs is ``kind_mismatch``).
REFUSALS: Dict[Tuple[str, str], str] = {
    ('float', 'int'): 'float_to_int',        # the decimals would be lost
}


def wire_compat(sender_kind: Optional[str], sender_type: Optional[str],
                receiver_kind: Optional[str], receiver_type: Optional[str]) -> Tuple[str, str]:
    """Can a sender (kind / type, either may be unknown) be wired into a receiver?

    Returns ``('same', '')``, ``('convert', <note>)`` or ``('refuse', <reason>)``. A side
    without a kind is described by its type (``kind_of_type``; None = 専用の型). 専用の型 on
    either side only matches the same ROS type. Nothing known on one side (a topic that does
    not exist yet) is always ``same``: the receiver decides the type.
    """
    s_kind = sender_kind or (kind_of_type(sender_type) if sender_type else None)
    r_kind = receiver_kind or (kind_of_type(receiver_type) if receiver_type else None)
    if (s_kind is None and not sender_type) or (r_kind is None and not receiver_type):
        return 'same', ''
    if MESSAGE_KIND in (s_kind, r_kind) or s_kind is None or r_kind is None:
        if sender_type and receiver_type and _normalize(sender_type) == _normalize(receiver_type):
            return 'same', ''
        return 'refuse', 'type_mismatch'
    if s_kind == r_kind:
        return 'same', ''
    if (s_kind, r_kind) in CONVERSIONS:
        return 'convert', CONVERSIONS[(s_kind, r_kind)]
    return 'refuse', REFUSALS.get((s_kind, r_kind), 'kind_mismatch')


def catalog(installed: Callable[[str], bool] = _installed) -> Dict[str, Any]:
    """``GET /api/data-kinds``: kinds with their resolved type and the type -> kind table."""
    kinds = []
    for kind in KINDS:
        chosen = ros_type(kind.id, installed)
        kinds.append({'id': kind.id, 'type': chosen, 'available': installed(chosen),
                      'python': kind.python})
    return {'kinds': kinds, 'type_kinds': dict(sorted(_COMPAT.items())),
            'common_types': list(COMMON_TYPES),
            'conversions': [{'from': a, 'to': b, 'note': note}
                            for (a, b), note in CONVERSIONS.items()]}


def type_groups(types: Sequence[str], workspace_packages: Sequence[str]) -> List[Dict[str, Any]]:
    """詳細設定モード order: common types -> workspace types -> others by package.

    Never one flat alphabetical list: beginners find the usual types first and
    their own packages' types next.
    """
    present = {_normalize(t) for t in types}
    common = [t for t in COMMON_TYPES if t in present]
    ws = set(workspace_packages)
    rest = sorted(present - set(common))
    groups: List[Dict[str, Any]] = [{'id': 'common', 'types': common}]
    groups.append({'id': 'workspace', 'types': [t for t in rest if t.split('/')[0] in ws]})
    by_pkg: Dict[str, List[str]] = {}
    for name in rest:
        pkg = name.split('/')[0]
        if pkg not in ws:
            by_pkg.setdefault(pkg, []).append(name)
    groups += [{'id': 'package', 'package': pkg, 'types': names}
               for pkg, names in sorted(by_pkg.items())]
    return groups


# ---- message <-> Python value (function nodes) -----------------------------------------
def _media(type_name: str) -> Any:
    from .media import adapters
    return adapters.get(type_name)


def _type_label(value: Any) -> str:
    cls = type(value)
    return cls.__name__ if cls.__module__ == 'builtins' else f'{cls.__module__}.{cls.__name__}'


def _need(kind_id: str, expected: str, value: Any) -> KindError:
    return KindError('invalid_value', f'the output kind {kind_id!r} needs {expected}, but the '
                     f'function returned {_type_label(value)}')


def to_python(kind_id: str, msg: Any, type_name: str = '') -> Any:
    """A received message as the Python value of ``kind_id`` (function arguments)."""
    if kind_id == MESSAGE_KIND:
        from . import msgutil
        return msgutil.to_plain(msg)
    if kind_id == 'string':
        return str(msg.data)
    if kind_id == 'json':
        try:
            return json.loads(msg.data)
        except ValueError as exc:
            raise KindError('invalid_json', f'the received text is not JSON: {exc}') from exc
    if kind_id == 'float':
        return float(msg.data)
    if kind_id == 'int':
        return int(msg.data)
    if kind_id == 'bool':
        return bool(msg.data)
    if kind_id == 'numbers':
        return [float(x) for x in msg.data]
    if kind_id == 'bytes':
        return bytes(msg.data)
    if kind_id == 'image':
        return _image_to_array(msg)
    if kind_id == 'audio':
        return _audio_to_array(msg, type_name)
    get(kind_id)
    raise KindError('unknown_kind', f'no conversion for kind {kind_id!r}')


def _is_bool(value: Any) -> bool:
    import numpy as np
    return isinstance(value, (bool, np.bool_))


def _as_float(kind_id: str, value: Any) -> float:
    import numpy as np
    if _is_bool(value) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise _need(kind_id, 'a number (int / float)', value)
    return float(value)


def _as_int(kind_id: str, value: Any) -> int:
    import numpy as np
    if _is_bool(value):
        raise _need(kind_id, 'an int', value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)) and math.isfinite(value) and float(value).is_integer():
        return int(value)
    raise _need(kind_id, 'an int', value)


def _sequence(kind_id: str, value: Any, expected: str) -> List[Any]:
    import numpy as np
    if isinstance(value, np.ndarray):
        if value.ndim != 1:
            raise _need(kind_id, f'{expected} (a 1-D array, got shape {value.shape})', value)
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    raise _need(kind_id, expected, value)


def payload(kind_id: str, value: Any, type_name: str) -> Dict[str, Any]:
    """Field values for :func:`msgutil.build` (all kinds except image / audio / message)."""
    if kind_id == 'string':
        if not isinstance(value, str):
            raise _need(kind_id, 'a str', value)
        return {'data': value}
    if kind_id == 'json':
        try:
            return {'data': json.dumps(value, ensure_ascii=False)}
        except (TypeError, ValueError) as exc:
            raise _need(kind_id, 'a JSON-serializable value (dict / list / str / number)',
                        value) from exc
    if kind_id == 'float':
        return {'data': _as_float(kind_id, value)}
    if kind_id == 'int':
        return {'data': _as_int(kind_id, value)}
    if kind_id == 'bool':
        if not _is_bool(value):
            raise _need(kind_id, 'a bool (True / False)', value)
        return {'data': bool(value)}
    if kind_id == 'numbers':
        items = _sequence(kind_id, value, 'a list of numbers')
        if 'Float' in type_name:
            return {'data': [_as_float(kind_id, x) for x in items]}
        return {'data': [_as_int(kind_id, x) for x in items]}
    if kind_id == 'bytes':
        if isinstance(value, (bytes, bytearray, memoryview)):
            return {'data': array.array('B', bytes(value))}
        items = _sequence(kind_id, value, 'bytes')
        if not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255
                   for x in items):
            raise _need(kind_id, 'bytes (or a list of ints 0-255)', value)
        return {'data': array.array('B', items)}
    raise KindError('unknown_kind', f'no payload conversion for kind {kind_id!r}')


def from_python(kind_id: str, value: Any, type_name: str, stamp: Any = None) -> Any:
    """A function's return value as a message of ``type_name`` (raises KindError)."""
    from . import msgutil
    if kind_id == MESSAGE_KIND:
        if not isinstance(value, Mapping):
            raise _need(kind_id, f'a dict with the fields of {type_name}', value)
        try:
            return msgutil.build(type_name, value, stamp=stamp)
        except msgutil.MsgUtilError as exc:
            raise KindError('invalid_value', str(exc)) from exc
    if kind_id == 'image':
        return _array_to_image(value, type_name, stamp)
    if kind_id == 'audio':
        return _array_to_audio(value, type_name, stamp)
    try:
        return msgutil.build(type_name, payload(kind_id, value, type_name))
    except msgutil.MsgUtilError as exc:
        raise KindError('invalid_value', str(exc)) from exc


def _image_to_array(msg: Any) -> Any:
    from .media import imaging
    from .media.adapters.base import MediaSettings
    frame = _media('sensor_msgs/msg/Image').from_message(msg, MediaSettings())
    if frame.fmt == 'mono8':
        return imaging.to_rgb(frame)[:, :, 0].copy()
    return imaging.to_rgb(frame).copy()


def _array_to_image(value: Any, type_name: str, stamp: Any) -> Any:
    import numpy as np
    from .media.adapters.base import ImageFrame, MediaSettings
    if not isinstance(value, np.ndarray) or value.dtype != np.uint8:
        raise _need('image', 'a numpy uint8 array (H x W x 3 RGB or H x W gray)', value)
    if value.ndim == 2:
        fmt = 'mono8'
    elif value.ndim == 3 and value.shape[2] == 3:
        fmt = 'rgb8'
    else:
        raise _need('image', f'an H x W x 3 or H x W array (got shape {value.shape})', value)
    height, width = value.shape[:2]
    frame = ImageFrame(width, height, fmt, np.ascontiguousarray(value).tobytes())
    return _media(type_name).to_message(frame, stamp or _now(), MediaSettings(encoding=fmt))


def _audio_to_array(msg: Any, type_name: str) -> Any:
    import numpy as np
    from .media.adapters.base import MediaSettings
    chunk = _media(type_name).from_message(msg, MediaSettings())
    samples = np.frombuffer(chunk.data, dtype='<i2').astype(np.int16)
    return samples if chunk.channels == 1 else samples.reshape(-1, chunk.channels)


def _array_to_audio(value: Any, type_name: str, stamp: Any) -> Any:
    import numpy as np
    from .media.adapters.base import AudioChunk, MediaSettings
    if not isinstance(value, np.ndarray) or value.dtype != np.int16 or value.ndim not in (1, 2):
        raise _need('audio', 'a numpy int16 array (samples, or samples x channels)', value)
    channels = 1 if value.ndim == 1 else int(value.shape[1])
    chunk = AudioChunk(np.ascontiguousarray(value).astype('<i2').tobytes(), DEFAULT_SAMPLE_RATE,
                       channels)
    settings = MediaSettings(sample_rate=DEFAULT_SAMPLE_RATE, channels=channels)
    return _media(type_name).to_message(chunk, stamp or _now(), settings)


def _now() -> Any:
    from . import msgutil
    return msgutil.wall_time_msg()
