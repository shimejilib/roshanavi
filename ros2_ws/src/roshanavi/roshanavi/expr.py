"""Safe expression evaluation for injection payloads.

Web input is NEVER passed to ``eval``/``exec``/``compile``-to-code. Expressions
are parsed with ``ast.parse(mode="eval")`` and interpreted by a small recursive
evaluator that only accepts a whitelist of node types:

- numeric / string / bool literals
- binary ``+ - * / // % **``, unary ``+ - not``, ``and``/``or``
- comparisons (``== != < <= > >=``, chained)
- conditional expression ``a if cond else b``
- calls to whitelisted functions with positional arguments only
- names: variables (``i``, ``t``, ``now``) and constants (``pi``, ``e``)

Attribute access, subscripts, comprehensions, lambdas, keyword arguments and
everything else are rejected. Resource caps protect against DoS: source length,
AST nesting depth, exponent size, integer bit length and string length.

Payload templates: any string inside a payload dict containing ``${...}`` is an
expression. If the whole string is a single ``${...}`` the evaluated value is
used as-is (keeping its type); otherwise each ``${...}`` is replaced by
``str(value)``.
"""

import ast
import math
import operator
import random
import re
from typing import Any, Callable, Dict, List, Mapping, Optional

MAX_SOURCE_LEN = 1000
MAX_DEPTH = 40
MAX_POW_EXPONENT = 1000
MAX_INT_BITS = 4096
MAX_STR_LEN = 10000

VARIABLE_NAMES = ('i', 't', 'now')
CONSTANTS = {'pi': math.pi, 'e': math.e}

_PLACEHOLDER = re.compile(r'\$\{([^{}]*)\}')


class ExprError(ValueError):
    """Raised for rejected or failing expressions."""


def _num(x: Any) -> Any:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ExprError(f'expected a number, got {type(x).__name__}')
    return x


def _uniform(a: Any, b: Any, rng: random.Random) -> float:
    return rng.uniform(_num(a), _num(b))


def _randint(a: Any, b: Any, rng: random.Random) -> int:
    if not isinstance(a, int) or not isinstance(b, int):
        raise ExprError('randint() requires integers')
    if a > b:
        raise ExprError('randint(a, b) requires a <= b')
    return rng.randint(a, b)


def _to_str(x: Any) -> str:
    s = str(x)
    if len(s) > MAX_STR_LEN:
        raise ExprError(f'string longer than {MAX_STR_LEN}')
    return s


def _round(x: Any, ndigits: Any = None) -> Any:
    if ndigits is None:
        return round(_num(x))
    if not isinstance(ndigits, int) or abs(ndigits) > 100:
        raise ExprError('round() ndigits must be an int in [-100, 100]')
    return round(_num(x), ndigits)


def _build_functions(rng: random.Random) -> Dict[str, Callable[..., Any]]:
    return {
        'sin': lambda x: math.sin(_num(x)),
        'cos': lambda x: math.cos(_num(x)),
        'tan': lambda x: math.tan(_num(x)),
        'abs': lambda x: abs(_num(x)),
        'min': lambda *a: min(_num(x) for x in a),
        'max': lambda *a: max(_num(x) for x in a),
        'round': _round,
        'floor': lambda x: math.floor(_num(x)),
        'ceil': lambda x: math.ceil(_num(x)),
        'sqrt': lambda x: math.sqrt(_num(x)),
        'random': rng.random,
        'uniform': lambda a, b: _uniform(a, b, rng),
        'randint': lambda a, b: _randint(a, b, rng),
        'str': _to_str,
        'int': int,
        'float': float,
    }


FUNCTION_NAMES = tuple(_build_functions(random.Random()).keys())

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CMPOPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


def _check_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STR_LEN:
        raise ExprError(f'string longer than {MAX_STR_LEN}')
    if isinstance(value, int) and not isinstance(value, bool) \
            and value.bit_length() > MAX_INT_BITS:
        raise ExprError(f'integer larger than {MAX_INT_BITS} bits')
    return value


def _precheck_binop(op: ast.operator, left: Any, right: Any) -> None:
    """Reject operations whose result would be too large *before* computing."""
    if isinstance(op, ast.Pow):
        if isinstance(right, (int, float)) and abs(right) > MAX_POW_EXPONENT:
            raise ExprError(f'exponent larger than {MAX_POW_EXPONENT}')
        if isinstance(left, int) and isinstance(right, int) and right > 0 \
                and left.bit_length() * right > MAX_INT_BITS:
            raise ExprError(f'integer larger than {MAX_INT_BITS} bits')
    if isinstance(op, ast.Mod) and isinstance(left, str):
        raise ExprError('string %-formatting is not allowed')
    if isinstance(op, ast.Mult):
        for s, n in ((left, right), (right, left)):
            if isinstance(s, str) and isinstance(n, int) and len(s) * n > MAX_STR_LEN:
                raise ExprError(f'string longer than {MAX_STR_LEN}')
        if isinstance(left, int) and isinstance(right, int) \
                and left.bit_length() + right.bit_length() > MAX_INT_BITS:
            raise ExprError(f'integer larger than {MAX_INT_BITS} bits')


class Expression:
    """A parsed, validated expression ready for repeated evaluation."""

    def __init__(self, source: str):
        if not isinstance(source, str):
            raise ExprError('expression must be a string')
        if len(source) > MAX_SOURCE_LEN:
            raise ExprError(f'expression longer than {MAX_SOURCE_LEN} characters')
        try:
            tree = ast.parse(source.strip(), mode='eval')
        except SyntaxError as exc:
            raise ExprError(f'syntax error: {exc.msg}') from exc
        self.source = source
        self._tree = tree.body
        _validate(self._tree, 0)

    def evaluate(self, variables: Optional[Mapping[str, Any]] = None,
                 rng: Optional[random.Random] = None) -> Any:
        env = dict(CONSTANTS)
        for name in VARIABLE_NAMES:
            env[name] = 0
        env.update(variables or {})
        functions = _build_functions(rng or random.Random())
        try:
            return _Evaluator(env, functions).eval(self._tree, 0)
        except ExprError:
            raise
        except (ArithmeticError, ValueError, TypeError) as exc:
            raise ExprError(f'{type(exc).__name__}: {exc}') from exc


def _validate(node: ast.AST, depth: int) -> None:
    """Static whitelist check so bad expressions fail at submit time."""
    if depth > MAX_DEPTH:
        raise ExprError(f'expression nested deeper than {MAX_DEPTH}')
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool)):
            raise ExprError(f'literal of type {type(node.value).__name__} not allowed')
        _check_value(node.value)
        return
    if isinstance(node, ast.Name):
        if node.id not in VARIABLE_NAMES and node.id not in CONSTANTS:
            raise ExprError(f'unknown name: {node.id}')
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTION_NAMES:
            raise ExprError('only whitelisted functions may be called')
        if node.keywords:
            raise ExprError('keyword arguments are not allowed')
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
        raise ExprError(f'syntax not allowed: {type(node).__name__}')
    for child in children:
        if isinstance(child, ast.Starred):
            raise ExprError('star arguments are not allowed')
        _validate(child, depth + 1)


class _Evaluator:
    def __init__(self, env: Dict[str, Any], functions: Dict[str, Callable[..., Any]]):
        self._env = env
        self._functions = functions

    def eval(self, node: ast.AST, depth: int) -> Any:  # noqa: C901 - flat dispatch
        if depth > MAX_DEPTH:
            raise ExprError(f'expression nested deeper than {MAX_DEPTH}')
        d = depth + 1
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._env[node.id]
        if isinstance(node, ast.BinOp):
            left, right = self.eval(node.left, d), self.eval(node.right, d)
            _precheck_binop(node.op, left, right)
            return _check_value(_BINOPS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            value = self.eval(node.operand, d)
            if isinstance(node.op, ast.Not):
                return not value
            return _num(value) if isinstance(node.op, ast.UAdd) else -_num(value)
        if isinstance(node, ast.BoolOp):
            return self._bool_op(node, d)
        if isinstance(node, ast.Compare):
            return self._compare(node, d)
        if isinstance(node, ast.IfExp):
            branch = node.body if self.eval(node.test, d) else node.orelse
            return self.eval(branch, d)
        if isinstance(node, ast.Call):
            args = [self.eval(a, d) for a in node.args]
            return _check_value(self._functions[node.func.id](*args))
        raise ExprError(f'syntax not allowed: {type(node).__name__}')

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

    def __init__(self, payload: Any):
        self._compiled = _compile_node(payload, '')

    def render(self, variables: Optional[Mapping[str, Any]] = None,
               rng: Optional[random.Random] = None) -> Any:
        return _render_node(self._compiled, variables or {}, rng or random.Random())


class _StrTemplate:
    def __init__(self, parts: List[Any], whole: bool):
        self.parts = parts  # alternating str literals and Expression objects
        self.whole = whole


def _compile_node(node: Any, path: str) -> Any:
    if isinstance(node, dict):
        return {k: _compile_node(v, f'{path}.{k}' if path else str(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_compile_node(v, f'{path}.{i}' if path else str(i)) for i, v in enumerate(node)]
    if isinstance(node, str) and '${' in node:
        try:
            return _compile_string(node)
        except ExprError as exc:
            raise ExprError(f'{path or "<root>"}: {exc}') from exc
    return node


def _compile_string(text: str) -> _StrTemplate:
    match = _PLACEHOLDER.fullmatch(text)
    if match:
        return _StrTemplate([Expression(match.group(1))], whole=True)
    parts: List[Any] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(text[pos:m.start()])
        parts.append(Expression(m.group(1)))
        pos = m.end()
    parts.append(text[pos:])
    return _StrTemplate(parts, whole=False)


def _render_node(node: Any, variables: Mapping[str, Any], rng: random.Random) -> Any:
    if isinstance(node, dict):
        return {k: _render_node(v, variables, rng) for k, v in node.items()}
    if isinstance(node, list):
        return [_render_node(v, variables, rng) for v in node]
    if isinstance(node, _StrTemplate):
        if node.whole:
            return node.parts[0].evaluate(variables, rng)
        out = ''.join(
            str(p.evaluate(variables, rng)) if isinstance(p, Expression) else p
            for p in node.parts)
        return _check_value(out)
    return node
