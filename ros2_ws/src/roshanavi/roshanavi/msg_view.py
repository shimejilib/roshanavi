"""Read-only view of a received message for transform expressions (docs/design/input-and-media.md).

The safe evaluator never calls ``getattr`` on user-chosen names. Instead, a
received message is first converted to plain data (dicts / lists / scalars,
via ``rosidl_runtime_py.message_to_ordereddict``) and wrapped in a
:class:`MsgView`. ``msg.a.b`` and ``msg.data[3]`` in an expression become
``view.field('a')`` / ``view.item(3)``: a dictionary lookup and a bounded list
index on *that plain data only*. There is no path from a view to a Python
object's attributes (``__class__``, ``__dict__`` ...), and the view itself is
immutable.
"""

import array
import json
import re
from typing import Any, Iterator, List, Mapping, Sequence, Union

from .expr_base import MAX_INDEX, MAX_STR_LEN, ExprError, type_label

FIELD_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_Data = Union[Mapping[str, Any], Sequence[Any]]


def _is_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple, array.array, bytes, bytearray)) \
        or (hasattr(value, 'tolist') and hasattr(value, '__len__'))


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if hasattr(value, 'tolist'):
        return list(value.tolist())
    return list(value)


def wrap(value: Any) -> Any:
    """Scalars stay as they are; mappings and sequences become views."""
    if isinstance(value, MsgView):
        return value
    if isinstance(value, Mapping):
        return MsgView(value)
    if _is_sequence(value):
        return MsgView(_as_list(value))
    return value


def to_plain(value: Any) -> Any:
    """Views (also nested inside lists / dicts) back to plain dicts and lists."""
    if isinstance(value, MsgView):
        return value.plain()
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    return value


class MsgView:
    """An immutable message (or nested field / array) as seen by expressions."""

    __slots__ = ('_data',)

    def __init__(self, data: _Data):
        if not isinstance(data, (Mapping, list)):
            raise TypeError('MsgView wraps a mapping or a list')
        object.__setattr__(self, '_data', data)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError('MsgView is read-only')

    def __delattr__(self, name: str) -> None:
        raise AttributeError('MsgView is read-only')

    @classmethod
    def from_message(cls, msg: Any) -> 'MsgView':
        from rosidl_runtime_py import message_to_ordereddict  # ROS import only when used
        return cls(message_to_ordereddict(msg))

    @property
    def is_list(self) -> bool:
        return isinstance(self._data, list)

    def field(self, name: str) -> Any:
        """``view.name`` in an expression: a plain dictionary lookup."""
        if self.is_list:
            raise ExprError(f'.{name}: this is an array; use an index like [0]',
                            'not_struct', {'field': name})
        if not FIELD_RE.match(name) or name not in self._data:
            fields = ', '.join(sorted(k for k in self._data if FIELD_RE.match(str(k))))
            raise ExprError(f'no field {name!r} (fields: {fields})', 'no_field',
                            {'field': name, 'fields': fields})
        return wrap(self._data[name])

    def item(self, index: Any) -> Any:
        """``view[index]`` in an expression: integer index into an array only."""
        if not self.is_list:
            raise ExprError('[...] works on arrays only; use .name for fields', 'not_array')
        if isinstance(index, bool) or not isinstance(index, int):
            raise ExprError(f'an array index must be an integer, got {type_label(index)}',
                            'bad_index', {'got': type_label(index)})
        if abs(index) > MAX_INDEX:
            raise ExprError(f'index larger than {MAX_INDEX}', 'bad_index',
                            {'got': 'too large'})
        size = len(self._data)
        if not -size <= index < size:
            raise ExprError(f'index {index} is out of range (the array has {size} items)',
                            'index_range', {'index': index, 'size': size})
        return wrap(self._data[index])

    def plain(self) -> Any:
        return to_plain(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        return len(self._data) > 0

    def __iter__(self) -> Iterator[Any]:
        raise TypeError('message views are not iterable in expressions')

    def __eq__(self, other: Any) -> bool:
        other_plain = other.plain() if isinstance(other, MsgView) else other
        return self.plain() == other_plain

    def __hash__(self) -> int:
        raise TypeError('message views are not hashable')

    def __str__(self) -> str:
        text = json.dumps(self.plain(), ensure_ascii=False, default=str)
        if len(text) > MAX_STR_LEN:
            raise ExprError(f'string longer than {MAX_STR_LEN}', 'too_long',
                            {'limit': MAX_STR_LEN})
        return text

    __repr__ = __str__
