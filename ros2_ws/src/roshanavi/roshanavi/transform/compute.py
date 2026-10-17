"""What a transform node computes for one set of input messages (pure; no rclpy).

A :class:`Computer` compiles the spec's ``condition`` and ``mapping`` once,
with the input aliases (``msg``, ``msg1`` ...) as the only names whose fields
may be read (docs/design/input-and-media.md). ``compute`` returns whether the message passes the
condition and the output as plain data, ready for ``msgutil.build``.

Errors are collected per output field (``FieldError``), so the editor's live
preview can show each one next to the field it belongs to.
"""

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..expr import ExprError, Expression, compile_string, render_string
from ..expr_funcs import build_functions
from ..launcher.schema import TransformSpec
from ..msg_view import MsgView, to_plain

CONDITION_PATH = '(condition)'


@dataclass(frozen=True)
class FieldError:
    path: str
    code: str
    message: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {'path': self.path, 'code': self.code, 'message': self.message,
                'params': {k: v for k, v in self.params.items() if k != 'path'}}


@dataclass(frozen=True)
class Outcome:
    passed: bool
    output: Optional[Any] = None  # plain dict for map mode (None when not passed / failed)
    errors: List[FieldError] = field(default_factory=list)


def _error(path: str, exc: ExprError) -> FieldError:
    return FieldError(path, exc.code, str(exc), exc.params)


def aliases(spec: TransformSpec) -> List[str]:
    return [inp.alias or 'msg' for inp in spec.inputs]


class Computer:
    """Compiled condition + mapping of a ``mode: map`` transform."""

    def __init__(self, spec: TransformSpec, rng: Optional[random.Random] = None,
                 clock_ns: Callable[[], int] = time.time_ns):
        self.names = aliases(spec)
        self.compile_errors: List[FieldError] = []
        self._functions = build_functions(rng or random.Random(), clock_ns)
        self._condition: Optional[Expression] = None
        if spec.condition and spec.condition.strip():
            try:
                self._condition = Expression(spec.condition, self.names)
            except ExprError as exc:
                self.compile_errors.append(_error(CONDITION_PATH, exc))
        self._copy_input = spec.mapping is None
        self._mapping = None if spec.mapping is None else self._compile(spec.mapping, '')

    def _compile(self, node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {k: self._compile(v, f'{path}.{k}' if path else str(k)) for k, v in node.items()}
        if isinstance(node, list):
            return [self._compile(v, f'{path}.{i}' if path else str(i)) for i, v in enumerate(node)]
        if isinstance(node, str) and '${' in node:
            try:
                return _Compiled(path, compile_string(node, self.names))
            except ExprError as exc:
                self.compile_errors.append(_error(path, exc))
                return None
        return node

    @property
    def ok(self) -> bool:
        return not self.compile_errors

    def compute(self, views: Mapping[str, MsgView],
                variables: Optional[Mapping[str, Any]] = None) -> Outcome:
        if self.compile_errors:
            return Outcome(False, errors=list(self.compile_errors))
        env = {**(variables or {}), **views}
        if self._condition is not None:
            try:
                if not self._condition.evaluate(env, functions=self._functions):
                    return Outcome(False)
            except ExprError as exc:
                return Outcome(False, errors=[_error(CONDITION_PATH, exc)])
        if self._copy_input:
            return Outcome(True, output=views[self.names[0]].plain())
        errors: List[FieldError] = []
        output = self._render(self._mapping, env, errors)
        if errors:
            return Outcome(False, errors=errors)
        return Outcome(True, output=output)

    def _render(self, node: Any, env: Mapping[str, Any], errors: List[FieldError]) -> Any:
        if isinstance(node, dict):
            return {k: self._render(v, env, errors) for k, v in node.items()}
        if isinstance(node, list):
            return [self._render(v, env, errors) for v in node]
        if isinstance(node, _Compiled):
            try:
                return render_string(node.template, env, self._functions)
            except ExprError as exc:
                errors.append(_error(node.path, exc))
                return None
        return to_plain(node)


@dataclass(frozen=True)
class _Compiled:
    path: str
    template: Any
