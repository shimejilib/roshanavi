"""``__init__`` arguments of a class node as ROS parameters (docs/design/nodes.md).

An argument becomes a parameter when its type is one of the data kinds that a ROS parameter can
carry (the kinds of ``data_kinds``): 文字列 ``str`` -> STRING, 数値 ``float`` -> DOUBLE,
整数 ``int`` -> INTEGER, ON/OFF ``bool`` -> BOOL, 数値の並び ``list`` of numbers ->
DOUBLE_ARRAY, JSON ``dict`` / other ``list`` -> STRING holding the JSON text. The kind comes from
the type hint (the same hint table as the function nodes' ``modules.suggest_kind``), or, without
a hint, from the type of the default value. Arguments of other kinds (images, bytes ...) cannot
be parameters: they keep their Python default (and a required one is an error that says so).

The static listing (``class_modules``, AST only) and the node (real ``inspect.signature``) share
:func:`kind_for`.
"""

import inspect
import json
from dataclasses import dataclass
from typing import Any, List, Optional

from .modules import suggest_kind

PARAM_KINDS = ('string', 'float', 'int', 'bool', 'numbers', 'json')
NUMERIC_ELEMENTS = ('int', 'float')


class _Unset:
    def __repr__(self) -> str:
        return 'UNSET'


UNSET: Any = _Unset()   # no value: the argument is left out and Python's default applies


def annotation_text(annotation: Any) -> Optional[str]:
    """A type hint as text (``int``, ``List[float]``); None when there is none."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return None
    if isinstance(annotation, str):
        return annotation
    if getattr(annotation, '__origin__', None) is not None:
        return str(annotation).replace('typing.', '')
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace('typing.', '')


def _element_hint(text: str) -> Optional[str]:
    if '[' not in text or not text.endswith(']'):
        return None
    return text[text.index('[') + 1:-1].strip().split('[', 1)[0].strip().rsplit('.', 1)[-1]


def _default_kind(default: Any) -> Optional[str]:
    if isinstance(default, bool):
        return 'bool'
    if isinstance(default, int):
        return 'int'
    if isinstance(default, float):
        return 'float'
    if isinstance(default, str):
        return 'string'
    if isinstance(default, (list, tuple)):
        return 'numbers' if all(_is_number(x) for x in default) else 'json'
    if isinstance(default, dict):
        return 'json'
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _without_none(text: str) -> str:
    """``str | None`` / ``None | str`` / ``Union[str, None]`` -> ``str`` (Python 3.14 spells
    ``Optional[str]`` as ``str | None``); anything else unchanged."""
    if text.startswith('Optional[') and text.endswith(']'):
        return _without_none(text[len('Optional['):-1].strip())
    for none in (' | None', ' | NoneType'):
        if text.endswith(none):
            text = text[:-len(none)]
    for none in ('None | ', 'NoneType | '):
        if text.startswith(none):
            text = text[len(none):]
    inner = text[len('Union['):-1] if text.startswith('Union[') and text.endswith(']') else text
    if '[' in inner:
        return text   # a generic inside: leave it to suggest_kind
    parts = [p.strip() for p in inner.replace(',', '|').split('|')]
    kept = [p for p in parts if p not in ('None', 'NoneType', '')]
    return kept[0] if len(kept) == 1 and len(parts) > 1 else text


def kind_for(annotation: Optional[str], default: Any = UNSET) -> Optional[str]:
    """The data kind of an ``__init__`` argument that a parameter can carry, else None."""
    text = _without_none((annotation or '').strip().strip('\'"'))
    if text:
        kind = suggest_kind(text)
        if kind == 'numbers' and _element_hint(text) not in (None, *NUMERIC_ELEMENTS):
            kind = 'json'    # list[str] and the like: JSON text
        if kind in PARAM_KINDS:
            return kind
        if kind is not None or default is UNSET or default is None:
            return None      # image / bytes ...: not a parameter
    return _default_kind(default) if default is not UNSET else None


@dataclass(frozen=True)
class InitParam:
    name: str
    kind: Optional[str]         # None: cannot be a parameter
    annotation: Optional[str]
    has_default: bool
    default: Any = UNSET        # the Python default (UNSET when there is none)

    @property
    def required(self) -> bool:
        return not self.has_default

    def describe(self) -> str:
        hint = f': {self.annotation}' if self.annotation else ''
        tail = f' = {self.default!r}' if self.has_default else ''
        return f'{self.name}{hint}{tail}'


def init_params(signature: Optional[inspect.Signature]) -> List[InitParam]:
    """The keyword-capable arguments of a class (``inspect.signature(cls)``: no ``self``)."""
    if signature is None:
        return []
    params = []
    for param in signature.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD, param.POSITIONAL_ONLY):
            continue
        has_default = param.default is not param.empty
        default = param.default if has_default else UNSET
        text = annotation_text(param.annotation)
        params.append(InitParam(param.name, kind_for(text, default), text, has_default, default))
    return params


# ---- values: Python <-> ROS parameter -----------------------------------------------------------

def to_python(kind: str, value: Any, name: str = 'value') -> Any:
    """A spec / ROS value as the Python value ``__init__`` gets (ValueError: plain message)."""
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError(f'{name} は true / false にしてください ({_what(value)} でした)')
        return value
    if kind == 'int':
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{name} は整数にしてください ({_what(value)} でした)')
        return value
    if kind == 'float':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{name} は数値にしてください ({_what(value)} でした)')
        return float(value)
    if kind == 'string':
        if not isinstance(value, str):
            raise ValueError(f'{name} は文字列にしてください ({_what(value)} でした)')
        return value
    if kind == 'numbers':
        if isinstance(value, (list, tuple)) and all(_is_number(x) for x in value):
            return [float(x) for x in value]
        raise ValueError(f'{name} は数値の並びにしてください ({_what(value)} でした)')
    if kind == 'json':
        if not isinstance(value, str):
            raise ValueError(f'{name} は JSON の文字列にしてください ({_what(value)} でした)')
        try:
            return json.loads(value)
        except ValueError as exc:
            raise ValueError(f'{name} が JSON として読めません: {exc}') from exc
    raise ValueError(f'{name}: 対応していない種類 {kind!r}')


def to_ros(kind: str, value: Any) -> Any:
    """The value to declare a ROS parameter with."""
    if kind == 'json':
        return json.dumps(value, ensure_ascii=False)
    if kind == 'numbers':
        return [float(x) for x in value]
    return value


def from_default(kind: str, value: Any) -> Any:
    """The Python default of an argument as the value its parameter starts with."""
    if kind == 'json':
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'JSON にできない値です: {exc}') from exc
        return value
    return to_python(kind, list(value) if isinstance(value, tuple) else value)


def spec_value(kind: str, value: Any, name: str) -> Any:
    """A value from the node's ``params`` (YAML / JSON): JSON arguments are written as text, but a
    mapping / list in the file is accepted too."""
    if kind == 'json' and not isinstance(value, str):
        return value
    return to_python(kind, value, name)


def _what(value: Any) -> str:
    return type(value).__name__ if not isinstance(value, str) else f'文字列 {value!r}'

