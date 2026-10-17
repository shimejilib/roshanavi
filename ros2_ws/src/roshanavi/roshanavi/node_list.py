"""Node list (ノード一覧) aggregation: graph nodes ∪ registered targets (pure, DESIGN §6.6).

One row per running ROS node, plus one row for every launcher target or
persistent dummy that has no node on the graph right now (stopped, crashed, or
started but not discovered yet). Rows owned by a target that runs several nodes
(a launch file, a composable container) share a group, so the UI can show
that they stop together. Inject jobs (virtual ``dummy:<job>`` nodes) are left
out: they are not ROS nodes and live in the お試し送信 tab.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

ROLE_OTHER = 'other'


def _origin(target: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if target is None:
        return {'kind': 'external'}
    spec = target.get('spec') or {}
    origin = {'kind': target.get('kind', 'run'), 'package': spec.get('package'),
              'executable': spec.get('executable'), 'launch_file': spec.get('launch_file'),
              'imported_from': spec.get('imported_from')}
    if target.get('kind') == 'dummy':
        origin.update(package='roshanavi', executable='dummy', topic=spec.get('topic'))
    if target.get('kind') == 'transform':
        output = spec.get('output') or {}
        origin.update(package='roshanavi', executable='transform', topic=output.get('topic'))
    return {k: v for k, v in origin.items() if v is not None}


def _target_label(target: Mapping[str, Any]) -> str:
    spec = target.get('spec') or {}
    return spec.get('name') or spec.get('executable') or spec.get('launch_file') or target['id']


def _group_of(target: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """A group when the target is a launch file or one process hosts several nodes."""
    nodes = sorted(n['node'] for n in target.get('nodes') or [])
    if target.get('kind') != 'launch' and len(nodes) < 2:
        return None
    kind = 'launch' if target.get('kind') == 'launch' else 'process'
    label = (target.get('spec') or {}).get('launch_file') if kind == 'launch' else None
    return {'id': target['id'], 'kind': kind, 'label': label or target['id'],
            'target_id': target['id'], 'nodes': nodes, 'status': target.get('status')}


def _lifecycle(node: Mapping[str, Any], states: Mapping[str, Optional[str]]) -> Optional[Dict]:
    if not node.get('lifecycle'):
        return None
    return {'state': states.get(node['id'])}


def _control(target: Optional[Mapping[str, Any]], lifecycle: Optional[Dict]) -> Dict[str, Any]:
    if target is not None:
        if target.get('status') == 'invalid':
            return {'control': 'none', 'reason': 'invalid'}
        return {'control': 'target', 'reason': None}
    if lifecycle is not None:
        return {'control': 'lifecycle', 'reason': None}
    return {'control': 'none', 'reason': 'external'}


def _node_row(node: Mapping[str, Any], target: Optional[Mapping[str, Any]],
              mapped: Optional[Mapping[str, Any]], group: Optional[str],
              states: Mapping[str, Optional[str]]) -> Dict[str, Any]:
    lifecycle = _lifecycle(node, states)
    return {'key': node['id'], 'node': node['id'], 'name': node['id'],
            'role': node.get('role', ROLE_OTHER),
            'status': target.get('status', 'running') if target else 'running',
            'running': True, 'origin': _origin(target),
            'pid': (mapped or {}).get('pid'), 'confidence': node.get('confidence'),
            'target_id': target['id'] if target else None, 'group': group,
            'lifecycle': lifecycle, **_control(target, lifecycle)}


def _stopped_row(target: Mapping[str, Any], group: Optional[str]) -> Dict[str, Any]:
    return {'key': f"target:{target['id']}", 'node': None, 'name': _target_label(target),
            'role': target.get('role', 'dependency'), 'status': target.get('status', 'stopped'),
            'running': False, 'exit_code': target.get('exit_code'),
            'origin': _origin(target), 'pid': target.get('pid'),
            'confidence': None, 'target_id': target['id'], 'group': group,
            'lifecycle': None, 'problem': target.get('problem'), **_control(target, None)}


def _sort_key(row: Mapping[str, Any]) -> tuple:
    external = row['target_id'] is None
    return (external, row.get('group') or row.get('target_id') or '', row['name'])


def build_node_list(graph_nodes: Iterable[Mapping[str, Any]],
                    targets: Iterable[Mapping[str, Any]],
                    lifecycle_states: Optional[Mapping[str, Optional[str]]] = None
                    ) -> Dict[str, Any]:
    """``{rows, groups}`` for ``GET /api/node-list``."""
    states = lifecycle_states or {}
    by_id = {t['id']: t for t in targets}
    groups = {tid: g for tid, g in ((tid, _group_of(t)) for tid, t in by_id.items()) if g}
    mapped = {n['node']: n for t in by_id.values() for n in t.get('nodes') or []}
    rows, seen_targets = [], set()
    for node in graph_nodes:
        if node.get('job_id'):
            continue
        target = by_id.get(node.get('target_id') or '')
        if target is not None:
            seen_targets.add(target['id'])
        group = target['id'] if target is not None and target['id'] in groups else None
        rows.append(_node_row(node, target, mapped.get(node['id']), group, states))
    for tid, target in by_id.items():
        if tid not in seen_targets:
            rows.append(_stopped_row(target, tid if tid in groups else None))
    rows.sort(key=_sort_key)
    return {'rows': rows, 'groups': sorted(groups.values(), key=lambda g: g['id'])}


def lifecycle_node_ids(graph_nodes: Iterable[Mapping[str, Any]]) -> List[str]:
    return sorted(n['id'] for n in graph_nodes if n.get('lifecycle') and not n.get('job_id'))
