"""One pydantic API for pydantic 1.10 (Jazzy / Kilted apt) and 2.x (Lyrical apt).

Every module imports its pydantic names from here instead of from ``pydantic``.
The models are written once, in this module's vocabulary:

- ``constr(regex=...)``, ``Field(max_items=..., min_items=...)``: the v1 spelling; mapped to
  ``pattern`` / ``max_length`` / ``min_length`` on v2. Patterns always use Python's ``re``
  (v1 semantics: ``$`` also matches before a trailing newline), never pydantic-core's Rust
  engine.
- ``validator(field, pre=...)`` / ``root_validator(skip_on_failure=True)``: v1-style
  decorators; on v2 they become ``field_validator`` / ``model_validator(mode='after')``.
  A root validator still receives and returns the ``values`` dict.
- Base classes ``CompatModel`` (extra keys ignored), ``StrictModel`` (extra keys rejected),
  ``StrictAliasModel`` (rejected, and fields fill by name or alias) instead of
  ``class Config``.
- Instance / class methods use the v2 names (``model_dump``, ``model_validate``,
  ``model_copy``); on v1 ``CompatModel`` provides them.
- ``validation_errors(exc)``: the errors of a ``ValidationError`` (or FastAPI's
  ``RequestValidationError``) in the v1 shape (``loc`` / ``msg`` / ``type`` / ``ctx``), so
  our error envelopes and messages are the same on both versions.
- ``checked_type(fn)``: a type validated by ``fn(value) -> value`` (raise ``ValueError``),
  usable inside ``List[...]`` (v1's ``each_item`` validators have no v2 equivalent).
"""

import ast
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import pydantic
from pydantic import (BaseModel, StrictBool, StrictFloat, StrictInt, StrictStr,  # noqa: F401
                      ValidationError, confloat, conint)

PYDANTIC_V2 = int(pydantic.VERSION.split('.')[0]) >= 2

__all__ = ['PYDANTIC_V2', 'BaseModel', 'CompatModel', 'StrictModel', 'StrictAliasModel',
           'Field', 'StrictBool', 'StrictFloat', 'StrictInt', 'StrictStr', 'ValidationError',
           'checked_type', 'confloat', 'conint', 'constr', 'root_validator', 'validation_errors',
           'validator']


# ---- field types ------------------------------------------------------------------------

def constr(*, regex: Optional[str] = None, **kwargs: Any) -> Any:
    """``pydantic.constr`` with v1's ``regex=`` keyword on both versions."""
    if regex is None:
        return pydantic.constr(**kwargs)
    if PYDANTIC_V2:
        # A compiled pattern makes pydantic-core use Python's re (search); our patterns are
        # all anchored with ^, so search == v1's re.match.
        return pydantic.constr(pattern=re.compile(regex), **kwargs)
    return pydantic.constr(regex=regex, **kwargs)


def Field(*args: Any, max_items: Optional[int] = None,  # noqa: N802 (pydantic's name)
          min_items: Optional[int] = None, **kwargs: Any) -> Any:
    """``pydantic.Field`` with v1's ``max_items`` / ``min_items`` on both versions."""
    if PYDANTIC_V2:
        if max_items is not None:
            kwargs['max_length'] = max_items
        if min_items is not None:
            kwargs['min_length'] = min_items
    else:
        if max_items is not None:
            kwargs['max_items'] = max_items
        if min_items is not None:
            kwargs['min_items'] = min_items
    return pydantic.Field(*args, **kwargs)


def checked_type(fn: Callable[[Any], Any], name: str = 'Checked') -> Any:
    """A field type whose only validation is ``fn(value)`` (raises ``ValueError``)."""

    def v1_validators(cls: type) -> Any:
        yield fn

    def v2_schema(cls: type, _source: Any, _handler: Any) -> Any:
        from pydantic_core import core_schema
        return core_schema.no_info_plain_validator_function(fn)

    return type(name, (str,), {'__get_validators__': classmethod(v1_validators),
                               '__get_pydantic_core_schema__': classmethod(v2_schema)})


# ---- validators -------------------------------------------------------------------------

def validator(*fields: str, pre: bool = False, allow_reuse: bool = False) -> Any:
    """v1 ``@validator(field, pre=...)``; the function takes ``(cls, value)`` or ``(value)``."""
    if PYDANTIC_V2:
        return pydantic.field_validator(*fields, mode='before' if pre else 'after')
    return pydantic.validator(*fields, pre=pre, allow_reuse=allow_reuse)


def root_validator(*, skip_on_failure: bool) -> Any:
    """v1 ``@root_validator(skip_on_failure=True)``: ``fn(cls, values) -> values``."""
    if not skip_on_failure:
        raise TypeError('only skip_on_failure=True root validators are supported')
    if not PYDANTIC_V2:
        return pydantic.root_validator(skip_on_failure=True, allow_reuse=True)

    def decorate(fn: Callable[[type, Dict[str, Any]], Dict[str, Any]]) -> Any:
        def after(self: Any) -> Any:
            fields = type(self).model_fields
            values = {name: getattr(self, name) for name in fields}
            result = fn(type(self), dict(values))
            for name, value in result.items():
                if name in fields and value is not values[name]:
                    object.__setattr__(self, name, value)  # same as v1: no re-validation
            return self

        after.__name__ = after.__qualname__ = fn.__name__
        return pydantic.model_validator(mode='after')(after)

    return decorate


# ---- base models ------------------------------------------------------------------------

if PYDANTIC_V2:
    from pydantic import ConfigDict

    class CompatModel(BaseModel):
        """Unknown keys ignored (pydantic's default)."""

        # v1 turned numbers into strings for str fields (``name: 123`` in a YAML file).
        model_config = ConfigDict(coerce_numbers_to_str=True, regex_engine='python-re')

    class StrictModel(CompatModel):
        """Unknown keys are an error."""

        model_config = ConfigDict(extra='forbid')

    class StrictAliasModel(StrictModel):
        """Unknown keys are an error; fields fill by name or by alias."""

        model_config = ConfigDict(populate_by_name=True)

else:
    class CompatModel(BaseModel):  # type: ignore[no-redef]
        """Unknown keys ignored (pydantic's default). Provides the v2 method names."""

        def model_dump(self, **kwargs: Any) -> Dict[str, Any]:
            return self.dict(**kwargs)

        @classmethod
        def model_validate(cls, obj: Any) -> Any:
            return cls.parse_obj(obj)

        def model_copy(self, *, update: Optional[Dict[str, Any]] = None,
                       deep: bool = False) -> Any:
            return self.copy(update=update, deep=deep)

    class StrictModel(CompatModel):  # type: ignore[no-redef]
        """Unknown keys are an error."""

        class Config:
            extra = 'forbid'

    class StrictAliasModel(StrictModel):  # type: ignore[no-redef]
        """Unknown keys are an error; fields fill by name or by alias."""

        class Config:
            allow_population_by_field_name = True


# ---- errors in the v1 shape -------------------------------------------------------------

_V1 = {  # v2 type -> (v1 type, v1 message template, v2 ctx key of the limit)
    'missing': ('value_error.missing', 'field required', None),
    'extra_forbidden': ('value_error.extra', 'extra fields not permitted', None),
    'greater_than': ('value_error.number.not_gt', 'ensure this value is greater than {}',
                     'gt'),
    'greater_than_equal': ('value_error.number.not_ge',
                           'ensure this value is greater than or equal to {}', 'ge'),
    'less_than': ('value_error.number.not_lt', 'ensure this value is less than {}', 'lt'),
    'less_than_equal': ('value_error.number.not_le',
                        'ensure this value is less than or equal to {}', 'le'),
    'int_type': ('type_error.integer', 'value is not a valid integer', None),
    'int_parsing': ('type_error.integer', 'value is not a valid integer', None),
    'int_from_float': ('type_error.integer', 'value is not a valid integer', None),
    'float_type': ('type_error.float', 'value is not a valid float', None),
    'float_parsing': ('type_error.float', 'value is not a valid float', None),
    'string_type': ('type_error.str', 'str type expected', None),
    'bool_type': ('type_error.bool', 'value could not be parsed to a boolean', None),
    'bool_parsing': ('type_error.bool', 'value could not be parsed to a boolean', None),
    'string_too_short': ('value_error.any_str.min_length',
                         'ensure this value has at least {} characters', 'min_length'),
    'string_too_long': ('value_error.any_str.max_length',
                        'ensure this value has at most {} characters', 'max_length'),
    'too_short': ('value_error.list.min_items', 'ensure this value has at least {} items',
                  'min_length'),
    'too_long': ('value_error.list.max_items', 'ensure this value has at most {} items',
                 'max_length'),
    'dict_type': ('type_error.dict', 'value is not a valid dict', None),
    'model_type': ('type_error.dict', 'value is not a valid dict', None),
    'model_attributes_type': ('type_error.dict', 'value is not a valid dict', None),
    'list_type': ('type_error.list', 'value is not a valid list', None),
}
_TYPE_CHECKS = ('int_type', 'float_type', 'string_type', 'bool_type', 'dict_type', 'list_type',
                'model_type', 'model_attributes_type')
# Union member tags pydantic-core adds to ``loc`` (v1 reports the union's own location).
_SCALAR_TAG_RE = re.compile(r'^(bool|int|float|str|bytes|none|constrained-[a-z]+|'
                            r'[a-z][a-z-]*\[.*\])$')


def _limit(value: Any) -> Any:
    # v2 stores float bounds as floats (gt=0 -> 0.0); v1 printed what the model declared.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _model_names() -> set:
    names, todo = set(), [BaseModel]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub.__name__ not in names:
                names.add(sub.__name__)
                todo.append(sub)
    return names


def _clean_loc(loc: Tuple[Any, ...], models: set) -> Tuple[Any, ...]:
    out = [p for i, p in enumerate(loc) if i == 0 or not isinstance(p, str) or p not in models]
    while len(out) > 1 and isinstance(out[-1], str) and _SCALAR_TAG_RE.match(out[-1]):
        out.pop()
    return tuple(out)


def _literal_values(expected: str) -> Tuple[Any, ...]:
    """``"'eq', 'ne' or 'lt'"`` -> ``('eq', 'ne', 'lt')``."""
    parts: List[str] = []
    buf, quote, i = '', None, 0
    while i < len(expected):
        ch = expected[i]
        if quote:
            buf += ch
            if ch == '\\' and i + 1 < len(expected):
                buf += expected[i + 1]
                i += 1
            elif ch == quote:
                quote = None
        elif ch in '\'"':
            quote, buf = ch, buf + ch
        elif expected.startswith(', ', i) or expected.startswith(' or ', i):
            parts.append(buf)
            buf = ''
            i += 2 if expected.startswith(', ', i) else 4
            continue
        else:
            buf += ch
        i += 1
    parts.append(buf)
    values = []
    for part in parts:
        try:
            values.append(ast.literal_eval(part.strip()))
        except (ValueError, SyntaxError):
            values.append(part.strip())
    return tuple(values)


def _exc_type(exc: BaseException) -> str:
    # pydantic v1's naming for errors raised inside validators
    if isinstance(exc, AssertionError):
        return 'assertion_error'
    base = 'type_error' if isinstance(exc, TypeError) else 'value_error'
    if type(exc) in (TypeError, ValueError):
        return base
    code = getattr(exc, 'code', None) or type(exc).__name__.replace('Error', '').lower()
    return f'{base}.{code}'


def _to_v1(err: Dict[str, Any], models: set) -> Dict[str, Any]:
    kind, ctx = err.get('type', ''), err.get('ctx') or {}
    out: Dict[str, Any] = {'loc': _clean_loc(tuple(err.get('loc', ())), models)}
    if kind in _TYPE_CHECKS and err.get('input', ...) is None:
        out.update(type='type_error.none.not_allowed', msg='none is not an allowed value')
    elif kind in _V1:
        v1_type, template, key = _V1[kind]
        out.update(type=v1_type, msg=template)
        if key is not None and key in ctx:
            limit = _limit(ctx[key])
            out.update(msg=template.format(limit), ctx={'limit_value': limit})
    elif kind == 'string_pattern_mismatch':
        pattern = ctx.get('pattern', '')
        out.update(type='value_error.str.regex', msg=f'string does not match regex "{pattern}"',
                   ctx={'pattern': pattern})
    elif kind == 'literal_error':
        permitted = _literal_values(str(ctx.get('expected', '')))
        out.update(type='value_error.const',
                   msg='unexpected value; permitted: ' + ', '.join(map(repr, permitted)),
                   ctx={'given': err.get('input'), 'permitted': permitted})
    elif kind in ('value_error', 'assertion_error') and isinstance(ctx.get('error'),
                                                                    BaseException):
        out.update(type=_exc_type(ctx['error']), msg=str(ctx['error']))
    elif kind == 'json_invalid':
        out.update(type='value_error.jsondecode', msg=str(ctx.get('error', err.get('msg'))))
    else:
        out.update(type=kind, msg=err.get('msg', ''))
        if ctx:
            out['ctx'] = dict(ctx)
    return out


def validation_errors(exc: Any) -> List[Dict[str, Any]]:
    """``exc.errors()`` in pydantic v1's shape and wording, on either version."""
    errors = list(exc.errors())
    if not PYDANTIC_V2:
        return errors
    models = _model_names()
    return [_to_v1(err, models) for err in errors]
