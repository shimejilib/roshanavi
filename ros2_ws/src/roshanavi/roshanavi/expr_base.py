"""Shared pieces of the safe expression evaluator: the error type and DoS caps.

Kept separate so :mod:`.expr`, :mod:`.expr_funcs` and :mod:`.msg_view` can all
use them without import cycles.
"""

from typing import Any, Dict, Optional

MAX_SOURCE_LEN = 1000
MAX_DEPTH = 40
MAX_POW_EXPONENT = 1000
MAX_INT_BITS = 4096
MAX_STR_LEN = 10000
MAX_INDEX = 1_000_000  # array index in a message field (``msg.data[3]``)


class ExprError(ValueError):
    """Raised for rejected or failing expressions.

    ``code`` is a short machine-readable reason the web UI turns into plain
    Japanese (``syntax``, ``unknown_name``, ``not_allowed``, ``no_field`` ...);
    ``params`` carries the values to show (field name, limit, ...).
    """

    def __init__(self, message: str, code: str = 'invalid',
                 params: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.params = dict(params or {})


def num(x: Any) -> Any:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ExprError(f'expected a number, got {type_label(x)}', 'not_number',
                        {'got': type_label(x)})
    return x


def type_label(x: Any) -> str:
    """Type name for error messages (message views are called "message")."""
    name = type(x).__name__
    return 'message' if name == 'MsgView' else name


def check_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STR_LEN:
        raise ExprError(f'string longer than {MAX_STR_LEN}', 'too_long', {'limit': MAX_STR_LEN})
    if isinstance(value, int) and not isinstance(value, bool) \
            and value.bit_length() > MAX_INT_BITS:
        raise ExprError(f'integer larger than {MAX_INT_BITS} bits', 'too_large',
                        {'limit': MAX_INT_BITS})
    return value
