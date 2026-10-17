"""Node list aggregation (pure): graph nodes ∪ registered targets, grouping, control."""

from roshanavi.node_list import build_node_list, lifecycle_node_ids


def target(tid, kind='run', status='running', nodes=(), role='mine', **spec):
    return {'id': tid, 'kind': kind, 'role': role, 'status': status, 'pid': 10,
            'problem': None, 'spec': {'id': tid, **spec},
            'nodes': [{'node': n, 'confidence': 'exact', 'pid': 100 + i}
                      for i, n in enumerate(nodes)]}


def gnode(nid, role='other', target_id=None, **extra):
    node = {'id': nid, 'name': nid.rsplit('/', 1)[-1], 'namespace': '/', 'role': role}
    if target_id:
        node.update(target_id=target_id, confidence='exact')
    node.update(extra)
    return node


def rows_by_key(result):
    return {r['key']: r for r in result['rows']}


def test_union_of_running_nodes_and_stopped_targets():
    targets = [target('talker', nodes=['/talker'], package='demo_nodes_cpp', executable='talker'),
               target('listener', status='stopped', role='dependency',
                      package='demo_nodes_cpp', executable='listener', name='listener')]
    nodes = [gnode('/talker', 'mine', 'talker'), gnode('/external_talker')]
    rows = rows_by_key(build_node_list(nodes, targets))
    assert set(rows) == {'/talker', '/external_talker', 'target:listener'}
    owned = rows['/talker']
    assert owned['control'] == 'target' and owned['pid'] == 100 and owned['running']
    assert owned['origin'] == {'kind': 'run', 'package': 'demo_nodes_cpp',
                               'executable': 'talker'}
    stopped = rows['target:listener']
    assert stopped['status'] == 'stopped' and not stopped['running']
    assert stopped['name'] == 'listener' and stopped['node'] is None
    external = rows['/external_talker']
    assert external['control'] == 'none' and external['reason'] == 'external'
    assert external['origin'] == {'kind': 'external'} and external['target_id'] is None


def test_rows_sorted_owned_first_then_external():
    targets = [target('b', nodes=['/b'])]
    nodes = [gnode('/a_external'), gnode('/b', 'mine', 'b')]
    keys = [r['key'] for r in build_node_list(nodes, targets)['rows']]
    assert keys == ['/b', '/a_external']


def test_launch_and_multi_node_process_are_grouped():
    targets = [target('pair', kind='launch', nodes=['/talker', '/listener'],
                      package='demo_nodes_cpp', launch_file='talker_listener_launch.py'),
               target('container', nodes=['/c1', '/c2', '/container'],
                      package='rclcpp_components', executable='component_container'),
               target('single', nodes=['/single'])]
    nodes = [gnode(n, 'dependency', t) for t, ns in (
        ('pair', ['/talker', '/listener']), ('container', ['/c1', '/c2', '/container']),
        ('single', ['/single'])) for n in ns]
    result = build_node_list(nodes, targets)
    groups = {g['id']: g for g in result['groups']}
    assert groups['pair']['kind'] == 'launch'
    assert groups['pair']['label'] == 'talker_listener_launch.py'
    assert groups['pair']['nodes'] == ['/listener', '/talker']
    assert groups['container']['kind'] == 'process'
    assert 'single' not in groups
    rows = rows_by_key(result)
    assert rows['/talker']['group'] == 'pair' and rows['/c1']['group'] == 'container'
    assert rows['/single']['group'] is None


def test_stopped_launch_target_keeps_its_group():
    result = build_node_list([], [target('pair', kind='launch', status='stopped',
                                         launch_file='x.launch.py', package='p')])
    assert result['groups'][0]['nodes'] == [] and result['rows'][0]['group'] == 'pair'
    assert result['rows'][0]['name'] == 'x.launch.py'


def test_lifecycle_nodes_are_controllable_even_when_external():
    nodes = [gnode('/lc_talker', lifecycle=True), gnode('/plain')]
    result = build_node_list(nodes, [], {'/lc_talker': 'inactive'})
    rows = rows_by_key(result)
    assert rows['/lc_talker']['control'] == 'lifecycle'
    assert rows['/lc_talker']['lifecycle'] == {'state': 'inactive'}
    assert rows['/plain']['lifecycle'] is None and rows['/plain']['control'] == 'none'
    assert lifecycle_node_ids(nodes) == ['/lc_talker']


def test_inject_jobs_and_invalid_targets():
    nodes = [gnode('dummy:abc', 'dummy', job_id='abc')]
    targets = [target('broken', status='invalid', package='gone', executable='x')]
    targets[0]['problem'] = 'package gone not found'
    rows = build_node_list(nodes, targets)['rows']
    assert [r['key'] for r in rows] == ['target:broken']
    assert rows[0]['control'] == 'none' and rows[0]['reason'] == 'invalid'
    assert rows[0]['problem'] == 'package gone not found'


def test_dummy_and_imported_origin():
    dummy = target('cam', kind='dummy', role='dummy', status='stopped', name='dummy_cam',
                   topic='/cam')
    imported = target('t', nodes=['/r1/talker'], package='demo_nodes_cpp',
                      executable='talker', imported_from='my_pkg/robot.launch.py')
    rows = rows_by_key(build_node_list([gnode('/r1/talker', 'mine', 't')], [dummy, imported]))
    assert rows['target:cam']['origin'] == {'kind': 'dummy', 'package': 'roshanavi',
                                            'executable': 'dummy', 'topic': '/cam'}
    assert rows['/r1/talker']['origin']['imported_from'] == 'my_pkg/robot.launch.py'
