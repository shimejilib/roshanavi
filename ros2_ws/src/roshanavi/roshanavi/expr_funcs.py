"""Whitelisted functions of the safe expression evaluator (docs/design/input-and-media.md).

Every function checks its argument types and keeps results within the caps of
:mod:`.expr_base` (string length, integer size) *before* doing expensive work.
"""

import math
import random
import time
from typing import Any, Callable, Dict

from .expr_base import MAX_STR_LEN, ExprError, num, type_label
from .msg_view import MsgView


def _text(x: Any, fname: str) -> str:
    if not isinstance(x, str):
        raise ExprError(f'{fname}() needs a string, got {type_label(x)}', 'not_string',
                        {'function': fname, 'got': type_label(x)})
    return x


def _uniform(a: Any, b: Any, rng: random.Random) -> float:
    return rng.uniform(num(a), num(b))


def _randint(a: Any, b: Any, rng: random.Random) -> int:
    if not isinstance(a, int) or not isinstance(b, int):
        raise ExprError('randint() requires integers', 'bad_argument', {'function': 'randint'})
    if a > b:
        raise ExprError('randint(a, b) requires a <= b', 'bad_argument', {'function': 'randint'})
    return rng.randint(a, b)


def _to_str(x: Any) -> str:
    s = str(x)
    if len(s) > MAX_STR_LEN:
        raise ExprError(f'string longer than {MAX_STR_LEN}', 'too_long', {'limit': MAX_STR_LEN})
    return s


def _to_int(x: Any) -> int:
    if isinstance(x, MsgView):
        raise ExprError('int() needs a number or a string, got message', 'bad_argument',
                        {'function': 'int'})
    return int(x)


def _to_float(x: Any) -> float:
    if isinstance(x, MsgView):
        raise ExprError('float() needs a number or a string, got message', 'bad_argument',
                        {'function': 'float'})
    return float(x)


def _round(x: Any, ndigits: Any = None) -> Any:
    if ndigits is None:
        return round(num(x))
    if not isinstance(ndigits, int) or abs(ndigits) > 100:
        raise ExprError('round() ndigits must be an int in [-100, 100]', 'bad_argument',
                        {'function': 'round'})
    return round(num(x), ndigits)


def _replace(s: Any, old: Any, new: Any) -> str:
    s, old, new = _text(s, 'replace'), _text(old, 'replace'), _text(new, 'replace')
    count = len(s) + 1 if old == '' else s.count(old)
    if len(s) + count * (len(new) - len(old)) > MAX_STR_LEN:  # checked before building it
        raise ExprError(f'string longer than {MAX_STR_LEN}', 'too_long', {'limit': MAX_STR_LEN})
    return s.replace(old, new)


def _len(x: Any) -> int:
    if isinstance(x, (str, MsgView)):
        return len(x)
    raise ExprError(f'len() needs a string or an array, got {type_label(x)}', 'bad_argument',
                    {'function': 'len'})


def _clamp(x: Any, lo: Any, hi: Any) -> Any:
    x, lo, hi = num(x), num(lo), num(hi)
    if lo > hi:
        raise ExprError('clamp(x, lo, hi) requires lo <= hi', 'bad_argument',
                        {'function': 'clamp'})
    return min(max(x, lo), hi)


def _now_stamp(clock: Callable[[], int]) -> MsgView:
    ns = clock()
    return MsgView({'sec': ns // 1_000_000_000, 'nanosec': ns % 1_000_000_000})


def build_functions(rng: random.Random,
                    clock_ns: Callable[[], int] = time.time_ns) -> Dict[str, Callable[..., Any]]:
    return {
        'sin': lambda x: math.sin(num(x)),
        'cos': lambda x: math.cos(num(x)),
        'tan': lambda x: math.tan(num(x)),
        'abs': lambda x: abs(num(x)),
        'min': lambda *a: min(num(x) for x in a),
        'max': lambda *a: max(num(x) for x in a),
        'round': _round,
        'floor': lambda x: math.floor(num(x)),
        'ceil': lambda x: math.ceil(num(x)),
        'sqrt': lambda x: math.sqrt(num(x)),
        'random': rng.random,
        'uniform': lambda a, b: _uniform(a, b, rng),
        'randint': lambda a, b: _randint(a, b, rng),
        'str': _to_str,
        'int': _to_int,
        'float': _to_float,
        # P5 (transform nodes): strings, clamp and the current time as a header stamp.
        'upper': lambda s: _text(s, 'upper').upper(),
        'lower': lambda s: _text(s, 'lower').lower(),
        'strip': lambda s: _text(s, 'strip').strip(),
        'replace': _replace,
        'len': _len,
        'clamp': _clamp,
        'now_stamp': lambda: _now_stamp(clock_ns),
    }


FUNCTION_NAMES = tuple(build_functions(random.Random()).keys())
