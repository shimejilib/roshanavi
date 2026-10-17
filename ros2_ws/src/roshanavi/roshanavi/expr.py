"""Safe expression evaluation for injection payloads and transform nodes.

Web input is NEVER passed to ``eval``/``exec``/``compile``-to-code. Expressions
are parsed with ``ast.parse(mode="eval")`` and interpreted by a small recursive
evaluator that only accepts a whitelist of node types:

- numeric / string / bool literals
- binary ``+ - * / // % **``, unary ``+ - not``, ``and``/``or``
- comparisons (``== != < <= > >=``, chained)
- conditional expression ``a if cond else b``
- calls to whitelisted functions (:mod:`.expr_funcs`) with positional arguments only
- names: variables (``i``, ``t``, ``now``) and constants (``pi``, ``e``)

Message fields (transform nodes, P5): an expression compiled with
``message_names=("msg", ...)`` may also read fields of those input messages,
``msg.linear.x`` and ``msg.data[0]``. Attribute access and subscripts are only
accepted when the chain starts at one of those names (checked statically), and
at run time the base must be a :class:`.msg_view.MsgView` (a read-only view of
plain message data; field access is a dictionary lookup, never ``getattr``).
Field names starting with ``_`` and slices are rejected. Attribute access on
anything else, comprehensions, lambdas and keyword arguments are rejected.

Resource caps protect against DoS: source length, AST nesting depth, exponent
size, integer bit length, string length and array index size.

Payload templates: any string inside a payload dict containing ``${...}`` is an
expression. If the whole string is a single ``${...}`` the evaluated value is
used as-is (keeping its type; a message view becomes plain data); otherwise
each ``${...}`` is replaced by ``str(value)``.
"""

import ast
import math
import operator
import random
import re
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional

from .expr_base import (MAX_DEPTH, MAX_INT_BITS, MAX_POW_EXPONENT, MAX_SOURCE_LEN,  # noqa: F401
                        MAX_STR_LEN, ExprError, check_value, num, type_label)
from .expr_funcs import FUNCTION_NAMES, build_functions
from .msg_view import FIELD_RE, MsgView, to_plain

VARIABLE_NAMES = ('i', 't', 'now')
CONSTANTS = {'pi': math.pi, 'e': math.e}
RESERVED_NAMES = frozenset((*VARIABLE_NAMES, *CONSTANTS, *FUNCTION_NAMES))

_PLACEHOLDER = re.compile(r'\$\{([^{}]*)\}')

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CMPOPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


def _too_large(what: str, limit: int) -> ExprError:
    return ExprError(f'{what} larger than {limit}', 'too_large', {'limit': limit})


def _precheck_binop(op: ast.operator, left: Any, right: Any) -> None:
    """Reject operations whose result would be too large *before* computing."""
    if isinstance(op, ast.Pow):
        if isinstance(right, (int, float)) and abs(right) > MAX_POW_EXPONENT:
            raise _too_large('exponent', MAX_POW_EXPONENT)
        if isinstance(left, int) and isinstance(right, int) and right > 0 \
                and left.bit_length() * right > MAX_INT_BITS:
            raise _too_large('integer (bits)', MAX_INT_BITS)
    if isinstance(op, ast.Mod) and isinstance(left, str):
        raise ExprError('string %-formatting is not allowed', 'not_allowed', {'what': '%'})
    if isinstance(op, ast.Mult):
        for s, n in ((left, right), (right, left)):
            if isinstance(s, str) and isinstance(n, int) and len(s) * n > MAX_STR_LEN:
                raise ExprError(f'string longer than {MAX_STR_LEN}', 'too_long',
                                {'limit': MAX_STR_LEN})
        if isinstance(left, int) and isinstance(right, int) \
                and left.bit_length() + right.bit_length() > MAX_INT_BITS:
            raise _too_large('integer (bits)', MAX_INT_BITS)


def validate_message_names(names: Iterable[str]) -> FrozenSet[str]:
    """Names for input messages must be identifiers that hide nothing built in."""
    result = frozenset(names)
    for name in result:
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', name):
            raise ExprError(f'invalid message name {name!r} (use a-z, 0-9, _)', 'bad_alias',
                            {'name': str(name)})
        if name in RESERVED_NAMES:
            raise ExprError(f'message name {name!r} is reserved', 'bad_alias', {'name': name})
    return result


class Expression:
    """A parsed, validated expression ready for repeated evaluation.

    ``message_names``: names of input messages whose fields may be read
    (transform nodes). Empty for injection payloads (no field access at all).
    """

    def __init__(self, source: str, message_names: Iterable[str] = ()):
        if not isinstance(source, str):
            raise ExprError('expression must be a string', 'syntax')
        if len(source) > MAX_SOURCE_LEN:
            raise ExprError(f'expression longer than {MAX_SOURCE_LEN} characters', 'too_long',
                            {'limit': MAX_SOURCE_LEN})
        self.message_names = validate_message_names(message_names)
        try:
            tree = ast.parse(source.strip(), mode='eval')
        except SyntaxError as exc:
            raise ExprError(f'syntax error: {exc.msg}', 'syntax', {'detail': exc.msg}) from exc
        except (RecursionError, MemoryError) as exc:
            raise ExprError('expression is too complex', 'too_deep', {'limit': MAX_DEPTH}) from exc
        self.source = source
        self._tree = tree.body
        _Validator(self.message_names).check(self._tree, 0)

    def evaluate(self, variables: Optional[Mapping[str, Any]] = None,
                 rng: Optional[random.Random] = None,
                 functions: Optional[Dict[str, Callable[..., Any]]] = None) -> Any:
        env: Dict[str, Any] = dict(CONSTANTS)
        for name in VARIABLE_NAMES:
            env[name] = 0
        env.update(variables or {})
        for name in self.message_names:
            if not isinstance(env.get(name), MsgView):
                raise ExprError(f'no message has been received as {name!r} yet', 'no_message',
                                {'name': name})
        table = functions if functions is not None else build_functions(rng or random.Random())
        try:
            return _Evaluator(env, table).eval(self._tree, 0)
        except ExprError:
            raise
        except RecursionError as exc:
            raise ExprError('expression is too complex', 'too_deep',
                            {'limit': MAX_DEPTH}) from exc
        except (ArithmeticError, ValueError, TypeError) as exc:
            raise ExprError(f'{type(exc).__name__}: {exc}', 'eval_failed',
                            {'detail': str(exc)}) from exc


def _not_allowed(what: str) -> ExprError:
    return ExprError(f'syntax not allowed: {what}', 'not_allowed', {'what': what})


class _Validator:
    """Static whitelist check so bad expressions fail at submit time."""

    def __init__(self, message_names: FrozenSet[str]):
        self._messages = message_names

    def check(self, node: ast.AST, depth: int) -> None:  # noqa: C901 - flat dispatch
        if depth > MAX_DEPTH:
            raise ExprError(f'expression nested deeper than {MAX_DEPTH}', 'too_deep',
                            {'limit': MAX_DEPTH})
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or isinstance(node.value, (int, float, str)):
                check_value(node.value)
                return
            raise ExprError(f'literal of type {type(node.value).__name__} not allowed',
                            'not_allowed', {'what': type(node.value).__name__})
        if isinstance(node, ast.Name):
            if node.id not in VARIABLE_NAMES and node.id not in CONSTANTS \
                    and node.id not in self._messages:
                raise ExprError(f'unknown name: {node.id}', 'unknown_name', {'name': node.id})
            return
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            self._check_field_access(node, depth)
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTION_NAMES:
                name = node.func.id if isinstance(node.func, ast.Name) else '?'
                raise ExprError('only whitelisted functions may be called', 'unknown_function',
                                {'name': name})
            if node.keywords:
                raise ExprError('keyword arguments are not allowed', 'not_allowed',
                                {'what': 'keyword'})
            children: List[ast.AST] = list(node.args)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            children = [node.left, node.right]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            children = [node.operand]
        elif isinstance(node, ast.BoolOp):
            children = list(node.values)
        elif isinstance(node, ast.Compare) and all(type(o) in _CMPOPS for o in node.ops):
            children = [node.left, *node.comparators]
        elif isinstance(node, ast.IfExp):
            children = [node.test, node.body, node.orelse]
        else:
            raise _not_allowed(type(node).__name__)
        for child in children:
            if isinstance(child, ast.Starred):
                raise _not_allowed('Starred')
            self.check(child, depth + 1)

    def _check_field_access(self, node: ast.AST, depth: int) -> None:
        """``msg.a.b[0]``: the chain must start at an input message name."""
        if not self._messages:
            raise _not_allowed(type(node).__name__)
        current = node
        while isinstance(current, (ast.Attribute, ast.Subscript)):
            depth += 1
            if depth > MAX_DEPTH:
                raise ExprError(f'expression nested deeper than {MAX_DEPTH}', 'too_deep',
                                {'limit': MAX_DEPTH})
            if not isinstance(current.ctx, ast.Load):
                raise _not_allowed('assignment')
            if isinstance(current, ast.Attribute):
                if not FIELD_RE.match(current.attr):
                    raise ExprError(f'field name {current.attr!r} is not allowed',
                                    'bad_field', {'field': current.attr})
            else:
                if isinstance(current.slice, (ast.Slice, ast.Tuple)):
                    raise _not_allowed('slice')
                literal = current.slice
                if isinstance(literal, ast.Constant) and (isinstance(literal.value, bool) or
                                                          not isinstance(literal.value, int)):
                    raise ExprError('an array index must be an integer (use .name for fields)',
                                    'bad_index', {'got': type(literal.value).__name__})
                self.check(current.slice, depth + 1)
            current = current.value
        if not isinstance(current, ast.Name) or current.id not in self._messages:
            names = ', '.join(sorted(self._messages))
            raise ExprError(f'fields can only be read from the input message ({names})',
                            'field_base', {'names': names})


class _Evaluator:
    def __init__(self, env: Dict[str, Any], functions: Dict[str, Callable[..., Any]]):
        self._env = env
        self._functions = functions

    def eval(self, node: ast.AST, depth: int) -> Any:  # noqa: C901 - flat dispatch
        if depth > MAX_DEPTH:
            raise ExprError(f'expression nested deeper than {MAX_DEPTH}', 'too_deep',
                            {'limit': MAX_DEPTH})
        d = depth + 1
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._env[node.id]
        if isinstance(node, ast.Attribute):
            return self._view(node.value, d).field(node.attr)
        if isinstance(node, ast.Subscript):
            base = self._view(node.value, d)
            return base.item(self.eval(node.slice, d))
        if isinstance(node, ast.BinOp):
            left, right = self.eval(node.left, d), self.eval(node.right, d)
            if isinstance(left, MsgView) or isinstance(right, MsgView):
                raise ExprError('cannot calculate with a whole message; pick a field',
                                'whole_message')
            _precheck_binop(node.op, left, right)
            return check_value(_BINOPS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            value = self.eval(node.operand, d)
            if isinstance(node.op, ast.Not):
                return not value
            return num(value) if isinstance(node.op, ast.UAdd) else -num(value)
        if isinstance(node, ast.BoolOp):
            return self._bool_op(node, d)
        if isinstance(node, ast.Compare):
            return self._compare(node, d)
        if isinstance(node, ast.IfExp):
            branch = node.body if self.eval(node.test, d) else node.orelse
            return self.eval(branch, d)
        if isinstance(node, ast.Call):
            args = [self.eval(a, d) for a in node.args]
            return check_value(self._functions[node.func.id](*args))
        raise _not_allowed(type(node).__name__)

    def _view(self, node: ast.AST, depth: int) -> MsgView:
        base = self.eval(node, depth)
        if not isinstance(base, MsgView):
            raise ExprError(f'cannot read a field of {type_label(base)}', 'not_struct',
                            {'got': type_label(base)})
        return base

    def _bool_op(self, node: ast.BoolOp, depth: int) -> Any:
        is_and = isinstance(node.op, ast.And)
        value: Any = None
        for child in node.values:
            value = self.eval(child, depth)
            if bool(value) != is_and:
                return value
        return value

    def _compare(self, node: ast.Compare, depth: int) -> bool:
        left = self.eval(node.left, depth)
        for op, comp in zip(node.ops, node.comparators):
            right = self.eval(comp, depth)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True


def evaluate(source: str, variables: Optional[Mapping[str, Any]] = None,
             rng: Optional[random.Random] = None) -> Any:
    """Parse and evaluate ``source`` in one step."""
    return Expression(source).evaluate(variables, rng)


class PayloadTemplate:
    """A payload (dict/list/scalars) whose ``${...}`` strings are pre-compiled."""

    def __init__(self, payload: Any, message_names: Iterable[str] = ()):
        self._names = validate_message_names(message_names)
        self._compiled = _compile_node(payload, '', self._names)

    def render(self, variables: Optional[Mapping[str, Any]] = None,
               rng: Optional[random.Random] = None,
               functions: Optional[Dict[str, Callable[..., Any]]] = None) -> Any:
        table = functions if functions is not None else build_functions(rng or random.Random())
        return _render_node(self._compiled, variables or {}, table)


class _StrTemplate:
    def __init__(self, parts: List[Any], whole: bool):
        self.parts = parts  # alternating str literals and Expression objects
        self.whole = whole


def _compile_node(node: Any, path: str, names: FrozenSet[str]) -> Any:
    if isinstance(node, dict):
        return {k: _compile_node(v, f'{path}.{k}' if path else str(k), names)
                for k, v in node.items()}
    if isinstance(node, list):
        return [_compile_node(v, f'{path}.{i}' if path else str(i), names)
                for i, v in enumerate(node)]
    if isinstance(node, str) and '${' in node:
        try:
            return compile_string(node, names)
        except ExprError as exc:
            raise ExprError(f'{path or "<root>"}: {exc}', exc.code,
                            {**exc.params, 'path': path}) from exc
    return node


def compile_string(text: str, names: Iterable[str] = ()) -> _StrTemplate:
    match = _PLACEHOLDER.fullmatch(text)
    if match:
        return _StrTemplate([Expression(match.group(1), names)], whole=True)
    parts: List[Any] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(text[pos:m.start()])
        parts.append(Expression(m.group(1), names))
        pos = m.end()
    parts.append(text[pos:])
    return _StrTemplate(parts, whole=False)


def render_string(node: _StrTemplate, variables: Mapping[str, Any],
                  functions: Dict[str, Callable[..., Any]]) -> Any:
    if node.whole:
        return to_plain(node.parts[0].evaluate(variables, functions=functions))
    out = ''.join(
        str(p.evaluate(variables, functions=functions)) if isinstance(p, Expression) else p
        for p in node.parts)
    return check_value(out)


def _render_node(node: Any, variables: Mapping[str, Any],
                 functions: Dict[str, Callable[..., Any]]) -> Any:
    if isinstance(node, dict):
        return {k: _render_node(v, variables, functions) for k, v in node.items()}
    if isinstance(node, list):
        return [_render_node(v, variables, functions) for v in node]
    if isinstance(node, _StrTemplate):
        return render_string(node, variables, functions)
    return node
