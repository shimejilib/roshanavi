"""Static listing of the classes of a workspace module for class nodes (no import, ``ast`` only).

The server never imports user code (docs/design/security.md). For the "create a class node"
dialog it reads, with :mod:`ast`, each top-level public class: the ``__init__`` arguments (type
hint, default, and the data kind that decides whether it can be a ROS parameter), the public
methods (signature, return hint, whether it can be an *action*: no required argument) and which
of the hooks roshanavi calls (``close`` / ``shutdown`` / ``get_state`` / ``set_state`` /
``on_param_change``) the class defines.
"""

import ast
import os
from typing import Any, Dict, List, Optional

from ..launcher.errors import LauncherError
from ..launcher.schema import HOOK_METHODS
from .class_params import UNSET, kind_for
from . import modules
from .modules import MAX_SOURCE_BYTES, _annotation, suggest_kind

SKIPPED_DECORATORS = ('staticmethod', 'classmethod', 'property', 'cached_property',
                      'abstractmethod')


def _decorators(fn: ast.FunctionDef) -> List[str]:
    names = []
    for deco in fn.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        names.append(target.attr if isinstance(target, ast.Attribute)
                     else getattr(target, 'id', ''))
    return names


def _literal(node: Optional[ast.AST]) -> Any:
    if node is None:
        return UNSET
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return UNSET


def _json_safe(value: Any) -> Any:
    """The default as JSON (tuples are lists); not representable -> None."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: _json_safe(v) for k, v in value.items()}
    return None


def _args_after_self(fn: ast.FunctionDef) -> List[Dict[str, Any]]:
    args = fn.args
    positional = [*args.posonlyargs, *args.args][1:]    # drop self
    defaults = [None] * (len(args.posonlyargs) + len(args.args) - len(args.defaults)) \
        + list(args.defaults)
    defaults = defaults[1:]
    rows = [(arg, default) for arg, default in zip(positional, defaults)]
    rows += list(zip(args.kwonlyargs, args.kw_defaults))
    out = []
    for arg, default in rows:
        out.append({'arg': arg, 'default': default})
    return out


def _method_info(fn: ast.FunctionDef) -> Dict[str, Any]:
    rows = _args_after_self(fn)
    params = []
    for row in rows:
        annotation = _annotation(row['arg'].annotation)
        params.append({'name': row['arg'].arg, 'annotation': annotation,
                       'kind': suggest_kind(annotation), 'optional': row['default'] is not None})
    returns = _annotation(fn.returns)
    required = sum(1 for p in params if not p['optional'])
    shown = ast.unparse(fn.args)
    shown = shown.split(',', 1)[1].lstrip() if ',' in shown else ''
    return {'name': fn.name, 'line': fn.lineno,
            'signature': f'{fn.name}({shown})' + (f' -> {returns}' if returns else ''),
            'params': params, 'required': required, 'varargs': fn.args.vararg is not None,
            'returns': returns, 'returns_kind': suggest_kind(returns),
            # no required argument: it can be called by a button / topic / scenario step
            'action_candidate': required == 0,
            'doc': (ast.get_docstring(fn) or '').strip().split('\n\n')[0][:500]}


def _init_params(init: Optional[ast.FunctionDef]) -> List[Dict[str, Any]]:
    if init is None:
        return []
    out = []
    for row in _args_after_self(init):
        arg, node = row['arg'], row['default']
        annotation = _annotation(arg.annotation)
        default = _literal(node)
        has_default = node is not None
        out.append({'name': arg.arg, 'annotation': annotation, 'has_default': has_default,
                    'default': _json_safe(default) if default is not UNSET else None,
                    'default_text': ast.unparse(node) if node is not None else None,
                    'kind': kind_for(annotation, default if has_default else UNSET)})
    return out


def _class_info(node: ast.ClassDef) -> Dict[str, Any]:
    init = next((n for n in node.body if isinstance(n, ast.FunctionDef)
                 and n.name == '__init__'), None)
    methods = []
    hooks: Dict[str, bool] = {name: False for name in HOOK_METHODS}
    for member in node.body:
        if not isinstance(member, ast.FunctionDef) or member.name.startswith('_'):
            continue
        if set(_decorators(member)) & set(SKIPPED_DECORATORS):
            continue
        if member.name in hooks:
            hooks[member.name] = True
            continue
        methods.append(_method_info(member))
    params = _init_params(init)
    return {'name': node.name, 'line': node.lineno,
            'signature': f'{node.name}(' + (', '.join(
                _param_text(p) for p in params)) + ')',
            'init_params': params, 'methods': methods, 'hooks': hooks,
            'doc': (ast.get_docstring(node) or '').strip().split('\n\n')[0][:500]}


def _param_text(param: Dict[str, Any]) -> str:
    text = param['name'] + (f': {param["annotation"]}' if param['annotation'] else '')
    return text + (f' = {param["default_text"]}' if param['has_default'] else '')


def list_classes(path: str) -> List[Dict[str, Any]]:
    """Top-level public classes of a source file, parsed with :mod:`ast` only."""
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            raise LauncherError('module_too_large', f'{path} is larger than 1 MB')
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), filename=path)
    except SyntaxError as exc:
        raise LauncherError('module_syntax_error', f'{os.path.basename(path)}:{exc.lineno}: '
                            f'{exc.msg}') from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LauncherError('module_unreadable', f'cannot read {path}: {exc}') from exc
    return [_class_info(n) for n in tree.body
            if isinstance(n, ast.ClassDef) and not n.name.startswith('_')]


def describe_module(workspace: str, module: str) -> Dict[str, Any]:
    """``modules.describe_module`` plus the module's ``classes``."""
    info = modules.describe_module(workspace, module)
    info['classes'] = list_classes(modules.resolve_module(workspace, module).file)
    return info
