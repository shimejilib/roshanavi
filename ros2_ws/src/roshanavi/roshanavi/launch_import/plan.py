"""Turn an evaluation result into an import preview (pure apart from ``validate``).

Each launch ``Node`` becomes a proposed ``kind: run`` target: scalar parameters
go into ``params``, the rest into ``file_params`` (written as a parameter file
under the data dir when imported), remappings into ``remaps``. Every proposal
is checked the same way the launcher checks a target (package / executable
exist, names, argv rules); one that fails is listed with the reason and is not
importable. The child's JSON is treated as untrusted shape-wise (pydantic).
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from ..launcher.errors import LauncherError
from ..launcher.service import id_from_name
from ..pydantic_compat import CompatModel, Field, ValidationError
from .params_merge import merge_sources, split_params

Validator = Callable[[Dict[str, Any]], Optional[Tuple[str, str]]]


class _Loose(CompatModel):
    pass


class ChildNode(_Loose):
    package: str
    executable: str
    name: Optional[str] = None
    namespace: Optional[str] = None
    remaps: List[Tuple[str, str]] = Field(default_factory=list)
    args: List[str] = Field(default_factory=list)
    param_sources: List[Dict[str, Any]] = Field(default_factory=list)
    lifecycle: bool = False
    file: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class ChildEntity(_Loose):
    kind: str
    code: str
    detail: str = ''
    file: Optional[str] = None
    message: Optional[str] = None
    composable_nodes: Optional[List[str]] = None


class ChildResult(_Loose):
    file: str
    arguments: List[Dict[str, Any]] = Field(default_factory=list)
    missing_args: List[str] = Field(default_factory=list)
    nodes: List[ChildNode] = Field(default_factory=list, max_items=500)
    blocked: List[ChildEntity] = Field(default_factory=list, max_items=1000)
    skipped: List[ChildEntity] = Field(default_factory=list, max_items=1000)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


def parse_result(payload: Mapping[str, Any]) -> ChildResult:
    try:
        return ChildResult.model_validate(payload)
    except ValidationError as exc:
        raise LauncherError('launch_eval_failed', f'unexpected evaluation result: {exc}',
                            422) from exc


def fq_name(name: Optional[str], namespace: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return f"{(namespace or '').rstrip('/')}/{name}"


def _same_node(spec: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    other = target.get('spec') or {}
    keys = ('package', 'executable', 'name', 'namespace')
    return target.get('kind') == 'run' and all(spec.get(k) == other.get(k) for k in keys)


def plan_node(index: int, node: ChildNode, taken: List[str], origin: str,
              existing: Iterable[Mapping[str, Any]], validate: Validator) -> Dict[str, Any]:
    fq = fq_name(node.name, node.namespace)
    merged, files, problems = merge_sources(node.param_sources, fq)
    scalars, rest = split_params(merged)
    target_id = id_from_name(node.name or node.executable, taken)
    taken.append(target_id)
    spec = {'id': target_id, 'kind': 'run', 'package': node.package,
            'executable': node.executable, 'name': node.name, 'namespace': node.namespace,
            'params': scalars, 'remaps': dict(node.remaps), 'args': list(node.args),
            'imported_from': origin}
    spec = {k: v for k, v in spec.items() if v not in (None, {}, [])}
    problem = validate(spec)
    warnings = [{'code': code, 'detail': ''} for code in node.warnings] + problems
    if not node.name:
        warnings.append({'code': 'node_name_unknown', 'detail': ''})
    duplicate = next((t['id'] for t in existing if _same_node(spec, t)), None)
    return {'index': index, 'fq_name': fq, 'lifecycle': node.lifecycle, 'file': node.file,
            'spec': spec, 'file_params': rest, 'param_files': files, 'warnings': warnings,
            'importable': problem is None, 'problem': problem and
            {'code': problem[0], 'message': problem[1]}, 'duplicate_of': duplicate}


def build_plan(result: ChildResult, origin: str, existing: List[Mapping[str, Any]],
               validate: Validator) -> Dict[str, Any]:
    taken = [t['id'] for t in existing]
    nodes = [plan_node(i, node, taken, origin, existing, validate)
             for i, node in enumerate(result.nodes)]
    return {'file': result.file, 'arguments': result.arguments,
            'missing_args': result.missing_args, 'nodes': nodes,
            'blocked': [e.model_dump(exclude_none=True) for e in result.blocked],
            'skipped': [e.model_dump(exclude_none=True) for e in result.skipped],
            'warnings': result.warnings}
