"""Launch takeover, pure part: desired targets, the diff against the registry, the report.

Per-node mode (``node``): every decomposable Node becomes a ``kind: run`` target; the rest
of the file (ExecuteProcess, containers, timers, event handlers, Nodes that did not pass the
launcher's checks) becomes one launch target running ``takeover_rest.launch.py``, which
includes the original file and skips the Nodes roshanavi runs itself. Whole mode
(``whole``): the launch file is one ``kind: launch`` target, as ``ros2 launch`` runs it.

The report lists, in codes the UI turns into plain Japanese, what per-node running keeps
(``carried``: respawn -> auto restart, environment variables) and what it loses (``lost``:
event handlers, required nodes, timer ordering, launch-time conditions, containers ...).
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..launcher.service import id_from_name
from . import skip as skip_list

Desired = Dict[str, Any]
MAX_SKIP_LEN = 4000
# launch file entities (blocked in the evaluation) -> what is lost when nodes run separately
EVENT_CODES = ('event_handler', 'emit_event', 'lifecycle_transition', 'opaque_coroutine')
CONTAINER_CODES = ('composable_container', 'load_composable_nodes')
NODE_LOST_WARNINGS = ('env_replaced', 'env_unset_not_carried', 'prefix_ignored',
                      'ros_arguments_ignored')
COMPARED_RUN = ('params', 'remaps', 'args', 'env')


def stem(launch_file: str) -> str:
    return launch_file.split('.')[0]


def key_of(spec: Mapping[str, Any]) -> Tuple[str, ...]:
    """Identity of a takeover target: a decomposed node, the remainder, or the whole file."""
    if spec.get('kind') == 'run':
        return ('run', *skip_list.node_key(spec))
    if spec.get('package') == skip_list.REST_PACKAGE \
            and spec.get('launch_file') == skip_list.REST_LAUNCH_FILE:
        return ('rest',)
    return ('whole', str(spec.get('package')), str(spec.get('launch_file')))


def is_mine(mine: Sequence[str], *names: Optional[str]) -> bool:
    wanted = {m.strip().lstrip('/') for m in mine if m.strip()}
    return any(n and (n.lstrip('/') in wanted) for n in names)


def _arg_items(args: Mapping[str, str]) -> List[str]:
    return [f'{k}:={v}' for k, v in sorted(args.items())]


def _whole(package: str, launch_file: str, args: Mapping[str, str], origin: str) -> Desired:
    spec = {'kind': 'launch', 'package': package, 'launch_file': launch_file,
            'args': _arg_items(args), 'imported_from': origin, 'takeover': True}
    return {'spec': spec, 'file_params': {}, 'label': launch_file, 'kind': 'whole',
            'node': None, 'id_hint': stem(launch_file)}


def _rest(package: str, launch_file: str, args: Mapping[str, str], origin: str,
          nodes: Iterable[Desired]) -> Optional[Desired]:
    skip = skip_list.encode(skip_list.node_key(d['spec']) for d in nodes)
    if len(skip) > MAX_SKIP_LEN:
        return None
    own = [f'{skip_list.ARG_PACKAGE}:={package}', f'{skip_list.ARG_LAUNCH_FILE}:={launch_file}',
           f'{skip_list.ARG_SKIP}:={skip}']
    user = [a for a in _arg_items(args) if not a.startswith('roshanavi_')]
    spec = {'kind': 'launch', 'package': skip_list.REST_PACKAGE,
            'launch_file': skip_list.REST_LAUNCH_FILE, 'args': own + user,
            'imported_from': origin, 'takeover': True}
    return {'spec': spec, 'file_params': {}, 'label': launch_file, 'kind': 'rest',
            'node': None, 'id_hint': f'{stem(launch_file)}-rest'}


def _node(node: Mapping[str, Any]) -> Desired:
    spec = {**node['spec'], 'takeover': True}
    spec.pop('id', None)
    return {'spec': spec, 'file_params': dict(node.get('file_params') or {}),
            'label': node.get('fq_name') or spec['executable'], 'kind': 'node',
            'node': node.get('fq_name'), 'id_hint': spec.get('name') or spec['executable']}


def desired_targets(plan: Mapping[str, Any], package: str, launch_file: str,
                    args: Mapping[str, str], mode: str) -> Tuple[List[Desired], List[str]]:
    """(desired targets without ids, notes). Notes: why per-node fell back to whole."""
    origin = f'{package}/{launch_file}'
    if mode == 'whole':
        return [_whole(package, launch_file, args, origin)], []
    nodes = [_node(n) for n in plan.get('nodes', []) if n.get('importable')]
    if not nodes:
        return [_whole(package, launch_file, args, origin)], ['nothing_decomposed']
    needs_rest = bool(plan.get('blocked')) or any(not n.get('importable')
                                                   for n in plan.get('nodes', []))
    if not needs_rest:
        return nodes, []
    rest = _rest(package, launch_file, args, origin, nodes)
    if rest is None:
        return [_whole(package, launch_file, args, origin)], ['too_many_nodes']
    return [*nodes, rest], []


def assign(desired: List[Desired], existing: Sequence[Mapping[str, Any]],
           taken: Iterable[str], mine: Sequence[str]) -> List[Desired]:
    """Give each desired target an id (the existing one when it matches) and a role."""
    by_key = {key_of(t['spec']): t for t in existing}
    wanted = {key_of(d['spec']) for d in desired}
    used = set(taken) | {t['id'] for key, t in by_key.items() if key in wanted}
    result = []
    for item in desired:
        old = by_key.get(key_of(item['spec']))
        spec = dict(item['spec'])
        names = (spec.get('name'), item.get('node'), item['id_hint'])
        if old is not None:
            spec['id'] = old['id']
            spec['role'] = 'mine' if is_mine(mine, *names, old['id']) else \
                old['spec'].get('role', 'dependency')
            spec['auto_restart'] = old['spec'].get('auto_restart', False) or \
                spec.get('auto_restart', False)
        else:
            spec['id'] = id_from_name(item['id_hint'], used)
            wanted = is_mine(mine, *names, spec['id']) or (item['kind'] == 'whole' and
                                                          bool(mine))
            spec['role'] = 'mine' if wanted else 'dependency'
        used.add(spec['id'])
        result.append({**item, 'spec': spec, 'existing': old is not None})
    return result


def diff(desired: Sequence[Desired], existing: Sequence[Mapping[str, Any]],
         file_params_of: Callable[[Mapping[str, Any]], Optional[Dict[str, Any]]]
         ) -> Dict[str, List[Dict[str, Any]]]:
    """added / removed / changed / unchanged, comparing only what the launch file defines."""
    by_key = {key_of(t['spec']): t for t in existing}
    wanted = {key_of(d['spec']) for d in desired}
    result: Dict[str, List[Dict[str, Any]]] = {'added': [], 'removed': [], 'changed': [],
                                               'unchanged': []}
    for item in desired:
        old = by_key.get(key_of(item['spec']))
        entry = {'id': item['spec']['id'], 'label': item['label'], 'kind': item['kind']}
        if old is None:
            result['added'].append(entry)
            continue
        fields = changed_fields(item, old['spec'], file_params_of(old['spec']))
        result['changed' if fields else 'unchanged'].append({**entry, 'fields': fields}
                                                            if fields else entry)
    for key, old in by_key.items():
        if key not in wanted:
            result['removed'].append({'id': old['id'], 'label': _label(old['spec']),
                                      'kind': key[0] if key[0] != 'run' else 'node'})
    return result


def _label(spec: Mapping[str, Any]) -> str:
    if spec.get('kind') == 'run':
        name, ns = spec.get('name'), spec.get('namespace')
        return f"{(ns or '').rstrip('/')}/{name}" if name else str(spec.get('executable'))
    return str(spec.get('launch_file'))


def changed_fields(item: Desired, old: Mapping[str, Any],
                   old_file_params: Optional[Dict[str, Any]]) -> List[str]:
    new = item['spec']
    if new.get('kind') != 'run':
        return ['args'] if list(new.get('args') or []) != list(old.get('args') or []) else []
    fields = [f for f in COMPARED_RUN if (new.get(f) or None) != (old.get(f) or None)]
    if (item['file_params'] or {}) != (old_file_params or {}):
        fields.append('file_params')
    return fields


def is_empty(changes: Mapping[str, List[Any]]) -> bool:
    return not (changes['added'] or changes['removed'] or changes['changed'])


def _codes(items: Iterable[Mapping[str, Any]]) -> List[str]:
    return [str(i.get('code')) for i in items]


def report(plan: Mapping[str, Any], desired: Sequence[Desired], mode: str,
           notes: Sequence[str]) -> Dict[str, Any]:
    """What per-node running carries over and what it loses (codes + details)."""
    separate = [d for d in desired if d['kind'] == 'node']
    rest = [d for d in desired if d['kind'] == 'rest']
    carried: List[Dict[str, Any]] = []
    lost: List[Dict[str, Any]] = []
    in_rest = [{'code': b.get('code'), 'detail': b.get('detail', '')}
               for b in plan.get('blocked', [])] if rest else []
    if separate:
        by_code: Dict[str, List[str]] = {}
        details: Dict[str, List[str]] = {}
        nodes = {n.get('fq_name') or n['spec'].get('executable'): n
                 for n in plan.get('nodes', []) if n.get('importable')}
        for label, node in nodes.items():
            for item in node.get('carried', []):
                by_code.setdefault(f"carried:{item['code']}", []).append(label)
                if item.get('detail'):
                    details.setdefault(f"carried:{item['code']}", []).append(item['detail'])
            for item in [*node.get('lost', []),
                         *[w for w in node.get('warnings', []) if w['code'] in
                           NODE_LOST_WARNINGS]]:
                by_code.setdefault(f"lost:{item['code']}", []).append(label)
                if item.get('detail'):
                    details.setdefault(f"lost:{item['code']}", []).append(item['detail'])
        for key, labels in by_code.items():
            side, code = key.split(':', 1)
            parts = {p for d in details.get(key, []) for p in d.split(', ') if p}
            entry = {'code': code, 'nodes': sorted(set(labels)), 'detail': ', '.join(sorted(parts))}
            (carried if side == 'carried' else lost).append(entry)
        blocked = _codes(plan.get('blocked', []))
        if any(c in EVENT_CODES for c in blocked):
            lost.append({'code': 'events', 'nodes': [], 'detail': ''})
        if 'timer' in blocked:
            lost.append({'code': 'timer_order', 'nodes': [], 'detail': ''})
        if any(c in CONTAINER_CODES for c in blocked):
            lost.append({'code': 'container', 'nodes': [], 'detail': ''})
        if any(w.get('code') == 'conditions_evaluated' for w in plan.get('warnings', [])):
            lost.append({'code': 'conditions_fixed', 'nodes': [], 'detail': ''})
    lost.sort(key=lambda e: e['code'])
    carried.sort(key=lambda e: e['code'])
    return {'mode': mode, 'notes': list(notes), 'carried': carried, 'lost': lost,
            'rest': in_rest, 'separate': len(separate),
            'suggest_whole': mode == 'node' and bool(separate) and bool(lost)}
