"""Field paths and ``where`` conditions over received messages (no ``eval``, no ``getattr``).

Messages are converted once (on receive) to plain data with large arrays capped
(:func:`plain_capped`); field paths like ``detections.0.bbox.center.position.x``
are then walked with :class:`..msg_view.MsgView` (a dictionary lookup / bounded
list index on that plain data only).
"""

import array
import json
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..expr_base import ExprError
from ..msg_view import MsgView, wrap

MAX_ARRAY = 256       # arrays longer than this keep only their length and a head
HEAD_ITEMS = 16
MAX_TEXT = 10000      # strings longer than this are cut (regex / contains look at the start)
MISSING = object()


def _is_seq(value: Any) -> bool:
    return isinstance(value, (list, tuple, array.array, bytes, bytearray)) \
        or (hasattr(value, 'tolist') and hasattr(value, '__len__'))


def _items(value: Any) -> List[Any]:
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if hasattr(value, 'tolist'):
        return list(value.tolist())
    return list(value)


def plain_capped(msg: Any, max_array: int = MAX_ARRAY) -> Any:
    """ROS message -> dicts / lists / scalars. Arrays longer than ``max_array`` become
    ``{'_truncated': True, 'length': n, 'head': [...]}`` (``len_*`` still see the length)."""
    if hasattr(msg, 'get_fields_and_field_types'):
        return {name: plain_capped(getattr(msg, name), max_array)
                for name in msg.get_fields_and_field_types()}
    if isinstance(msg, Mapping):
        return {str(k): plain_capped(v, max_array) for k, v in msg.items()}
    if _is_seq(msg):
        size = len(msg)
        if size > max_array:
            head = msg[:HEAD_ITEMS]
            return {'_truncated': True, 'length': size,
                    'head': [plain_capped(v, max_array) for v in _items(head)]}
        return [plain_capped(v, max_array) for v in _items(msg)]
    if isinstance(msg, str) and len(msg) > MAX_TEXT:
        return msg[:MAX_TEXT]
    if hasattr(msg, 'item') and not isinstance(msg, (int, float, bool, str)):
        return msg.item()  # numpy scalar
    return msg


def is_truncated(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get('_truncated') is True and 'length' in value


def split_path(path: str) -> List[Any]:
    return [int(p) if p.isdigit() else p for p in path.split('.')]


class FieldError(ValueError):
    """A path that does not resolve; ``message`` is plain Japanese."""


def get_field(plain: Any, path: str) -> Any:
    """Value at ``path`` (``a.b.0.c``) in plain message data, or raise :class:`FieldError`."""
    current: Any = wrap(plain)
    walked: List[str] = []
    for part in split_path(path):
        where = '.'.join(walked) or 'メッセージ'
        if isinstance(current, MsgView) and not current.is_list and is_truncated(current.plain()):
            data = current.plain()
            if isinstance(part, int) and part < len(data['head']):
                current = wrap(data['head'][part])
                walked.append(str(part))
                continue
            raise FieldError(f'{where} は {data["length"]} 個の大きな配列なので、先頭 {len(data["head"])} '
                             '個しか見られません')
        if not isinstance(current, MsgView):
            raise FieldError(f'{where} は値 ({short(current)}) なので、その先 .{part} はありません')
        try:
            current = current.item(part) if isinstance(part, int) else current.field(part)
        except ExprError as exc:
            if exc.code == 'no_field':
                fields = exc.params.get('fields', '')
                raise FieldError(f'{where} に {part} というフィールドはありません'
                                 + (f' (あるもの: {fields})' if fields else '')) from exc
            if exc.code == 'index_range':
                raise FieldError(f'{where} の [{part}] は範囲外です (要素は '
                                 f'{exc.params.get("size")} 個)') from exc
            if exc.code == 'not_array':
                raise FieldError(f'{where} は配列ではないので [{part}] は使えません') from exc
            if exc.code == 'not_struct':
                raise FieldError(f'{where} は配列なので、.{part} ではなく番号 (例: {where}.0) で'
                                 '指定してください') from exc
            raise FieldError(str(exc)) from exc
        walked.append(str(part))
    return current.plain() if isinstance(current, MsgView) else current


def short(value: Any, limit: int = 80) -> str:
    """Compact display of a value for explanations."""
    if is_truncated(value):
        return f'[{value["length"]} 個の配列]'
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    a, e = _number(actual), _number(expected)
    if a is not None and e is not None:
        return a == e
    return actual == expected


def _length(value: Any) -> Optional[int]:
    if is_truncated(value):
        return int(value['length'])
    if isinstance(value, (list, str)):
        return len(value)
    return None


def default_tol(value: float) -> float:
    return max(abs(value) * 1e-3, 1e-9)


OP_TEXT = {'eq': '= {value}', 'ne': '≠ {value}', 'lt': '< {value}', 'le': '≤ {value}',
           'gt': '> {value}', 'ge': '≥ {value}', 'range': '{min} 〜 {max}',
           'approx': '≈ {value} (±{tol})', 'regex': 'が正規表現 {value} に合う',
           'contains': 'に {value} を含む', 'exists': 'がある', 'len_eq': 'の長さ = {value}',
           'len_range': 'の長さ {min} 〜 {max}'}


def describe(cond: Any) -> str:
    """``data = "RUNNING"`` style text of one condition."""
    tol = cond.tol if cond.tol is not None else (default_tol(cond.value)
                                                  if _number(cond.value) is not None else '')
    text = OP_TEXT[cond.op].format(value=short(cond.value), min=short(cond.min) if cond.min
                                   is not None else '', max=short(cond.max) if cond.max is not None
                                   else '', tol=short(tol))
    sep = '' if cond.op in ('regex', 'contains', 'exists', 'len_eq', 'len_range') else ' '
    return f'{cond.field}{sep}{text}'


def check(cond: Any, plain: Any) -> Tuple[bool, Any, Optional[str]]:
    """``(ok, actual, reason)``. ``reason`` explains a failure in plain Japanese."""
    try:
        actual = get_field(plain, cond.field)
    except FieldError as exc:
        return False, MISSING, str(exc)
    op = cond.op
    if op == 'exists':
        return True, actual, None
    if op in ('eq', 'ne'):
        ok = _equal(actual, cond.value) == (op == 'eq')
        return ok, actual, None if ok else f'実際は {short(actual)}'
    if op in ('len_eq', 'len_range'):
        size = _length(actual)
        if size is None:
            return False, actual, f'{short(actual)} は配列でも文字列でもないので長さがありません'
        ok = size == cond.value if op == 'len_eq' else _within(size, cond.min, cond.max)
        return ok, size, None if ok else f'実際の長さは {size}'
    if op == 'regex':
        if not isinstance(actual, (str, int, float)) or isinstance(actual, bool):
            return False, actual, f'{short(actual)} は文字列ではありません'
        ok = re.search(cond.value, str(actual)[:MAX_TEXT]) is not None
        return ok, actual, None if ok else f'実際は {short(actual)}'
    if op == 'contains':
        if isinstance(actual, str):
            ok = isinstance(cond.value, str) and cond.value in actual
        elif isinstance(actual, list):
            ok = any(_equal(item, cond.value) for item in actual)
        else:
            return False, actual, f'{short(actual)} は文字列でも配列でもありません'
        return ok, actual, None if ok else f'実際は {short(actual)}'
    number = _number(actual)
    if number is None:
        return False, actual, f'{short(actual)} は数値ではありません'
    if isinstance(actual, float) and math.isnan(actual):
        return False, actual, '値が NaN (数ではない) です'
    if op == 'range':
        ok = _within(number, cond.min, cond.max)
    elif op == 'approx':
        tol = cond.tol if cond.tol is not None else default_tol(cond.value)
        ok = abs(number - cond.value) <= tol
    else:
        ok = {'lt': number < cond.value, 'le': number <= cond.value, 'gt': number > cond.value,
              'ge': number >= cond.value}[op]
    return ok, actual, None if ok else f'実際は {short(actual)}'


def _within(value: float, lo: Optional[float], hi: Optional[float]) -> bool:
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def match_all(conditions: Any, plain: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    """All conditions hold? Also returns the failed ones ``[{condition, reason}]``."""
    failed = []
    for cond in conditions:
        ok, _actual, reason = check(cond, plain)
        if not ok:
            failed.append({'condition': describe(cond), 'field': cond.field, 'reason': reason})
    return not failed, failed


def stamp_ns(plain: Any) -> Optional[int]:
    """``header.stamp`` of a message as integer nanoseconds (None without a header)."""
    try:
        stamp = plain['header']['stamp']
        return int(stamp['sec']) * 1_000_000_000 + int(stamp['nanosec'])
    except (KeyError, TypeError, ValueError):
        return None


def json_safe(value: Any) -> Any:
    """NaN / Infinity / bytes -> JSON-friendly values (results, API)."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    return value

