"""Scenario schema, field paths, where-ops and judging (no ROS graph needed)."""

import glob
import os
import xml.etree.ElementTree as ET

import pytest

from roshanavi.scenario import fields
from roshanavi.scenario.checks import (Record, make_check, make_guard, pair_by_order,
                                       pair_by_stamp, percentile)
from roshanavi.scenario.hints import hints
from roshanavi.scenario.junit import to_junit
from roshanavi.scenario.result import FAILED, PASSED, new_result
from roshanavi.scenario.schema import (Condition, ScenarioSchemaError, dump, parse_data,
                                       parse_text)
from roshanavi.graph import Endpoint, RawGraph
from roshanavi.stats import window_rate

EXAMPLES = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')


def scenario(steps, **extra):
    return parse_data({'name': 't', 'steps': steps, **extra})


def schema_errors(text):
    with pytest.raises(ScenarioSchemaError) as info:
        parse_text(text, 'x.yaml')
    return info.value.errors


# ---- schema --------------------------------------------------------------------------------

def test_examples_parse_and_round_trip():
    files = sorted(glob.glob(os.path.join(EXAMPLES, 'scenarios', '*.yaml')))
    assert len(files) >= 5
    for path in files:
        with open(path, encoding='utf-8') as fh:
            parsed = parse_text(fh.read(), os.path.basename(path))
        again = parse_text(dump(parsed))
        assert again.steps == parsed.steps and again.setup == parsed.setup
        assert again.guards == parsed.guards


def test_unknown_key_has_path_and_line():
    errors = schema_errors('name: a\nsteps:\n  - send: {topic: /a, data: {data: x}}\n'
                           '  - expect:\n      topic: /b\n      within: 1.0\n      withn: 2\n')
    assert errors == [{'path': 'steps.1.expect.withn', 'line': 7,
                       'message': '使えないキーです (書き間違いがないか確認してください)'}]


def test_unknown_step_kind_and_top_level_key():
    errors = schema_errors('name: a\ncolour: red\nsteps:\n  - expekt: {topic: /a}\n')
    assert errors[0]['path'] == 'colour' and errors[0]['line'] == 2


def test_unknown_step_kind_lists_kinds():
    errors = schema_errors('name: a\nsteps:\n  - expekt: {topic: /a}\n')
    assert errors[0]['line'] == 3 and 'expect' in errors[0]['message']


def test_yaml_syntax_error_line():
    errors = schema_errors('name: a\nsteps:\n  - send: {topic: /a\n  - wait: 1\n')
    assert errors[0]['line'] is not None and 'YAML' in errors[0]['message']


def test_missing_required_and_bad_values():
    errors = schema_errors('name: a\nsteps:\n  - expect: {topic: chatter}\n  - wait: -1\n')
    paths = {e['path']: e for e in errors}
    assert 'steps.0.expect.topic' in paths and '絶対名' in paths['steps.0.expect.topic']['message']
    assert paths['steps.0.expect.within']['message'] == '必須の項目がありません'
    assert paths['steps.1.wait.seconds']['line'] == 4


def test_version_and_stop_reference():
    errors = schema_errors('version: 2\nname: a\nsteps:\n  - stop: cam\n')
    assert any(e['path'] == 'version' for e in errors)
    errors = schema_errors('name: a\nsteps:\n  - stop: cam\n')
    assert 'start / play' in errors[0]['message'] and errors[0]['line'] == 3
    sc = parse_text('name: a\nsteps:\n  - stop: {target: text_shout}\n')  # no start needed
    assert sc.steps[0].spec.target == 'text_shout'
    assert parse_text(dump(sc)).steps == sc.steps
    errors = schema_errors('name: a\nsteps:\n  - stop: {}\n')
    assert errors[0]['path'] == 'steps.0.stop'


def test_step_scalar_forms_and_defaults():
    sc = scenario([{'start': {'topic': '/scan', 'rate_hz': 5, 'kind': 'float', 'value': 1.0}},
                   {'wait': 0.5}, {'stop': '/scan'},
                   {'latency': {'input': '/a', 'output': '/b', 'p95_ms': 50}}])
    assert sc.steps[0].spec.id == '/scan' and sc.steps[1].spec.seconds == 0.5
    assert sc.steps[3].spec.for_ == 5.0 and sc.steps[3].spec.match == 'header.stamp'
    assert sc.topics() == ['/a', '/b']


def test_condition_operands_are_checked():
    with pytest.raises(ValueError):
        Condition(field='data', op='gt', value='x')
    with pytest.raises(ValueError):
        Condition(field='data', op='range')
    with pytest.raises(ValueError):
        Condition(field='data', op='regex', value='(')
    with pytest.raises(ValueError):
        Condition(field='data.__class__', op='exists')
    with pytest.raises(ValueError):
        Condition(field='data', op='eq', value=1, tol=0.1)


def test_setup_items():
    sc = parse_data({'name': 's', 'steps': [{'wait': 0.1}], 'setup': [
        {'cmd': ['ros2', 'run', 'demo_nodes_cpp', 'talker'], 'wait_for_node': '/talker'},
        {'function': {'module': 'roshanavi_examples.logic', 'function': 'shout',
                      'inputs': [{'topic': '/a', 'kind': 'string'}],
                      'output': {'topic': '/b', 'kind': 'string'}}}]})
    assert sc.setup[0].item.wait_for_node == ['/talker']
    assert sc.setup[1].node_spec.id == 'scn-function-1'
    assert sc.setup[1].node_spec.name == 'scenario_function_1'
    with pytest.raises(ScenarioSchemaError) as info:
        parse_data({'name': 's', 'steps': [{'wait': 1}], 'setup': [{'run': {'package': 'p'}}]})
    assert info.value.errors[0]['path'] == 'setup.0.run.executable'
    with pytest.raises(ScenarioSchemaError):
        parse_data({'name': 's', 'steps': [{'wait': 1}],
                    'setup': [{'run': {'package': 'p', 'executable': 'e'}, 'target': 'x'}]})


def test_cmd_must_be_ros2_run_or_launch():
    from roshanavi.scenario.procs import SetupError, spec_from_cmd
    spec = spec_from_cmd(0, ['ros2', 'run', 'pkg', 'exe', 'a', '--ros-args', '-r',
                             '__node:=n', '-p', 'rate:=2', '-r', 'chatter:=/x'])
    assert (spec.name, spec.params, spec.remaps, spec.args) == ('n', {'rate': 2},
                                                                {'chatter': '/x'}, ['a'])
    launch = spec_from_cmd(1, ['ros2', 'launch', 'pkg', 'x.launch.py', 'k:=v'])
    assert launch.kind == 'launch' and launch.args == ['k:=v']
    for bad in (['bash', '-c', 'rm -rf /', 'x'], ['ros2', 'topic', 'pub', '/x'],
                ['ros2', 'run', 'p', 'e', '--ros-args', '--params-file', '/etc/passwd']):
        with pytest.raises(SetupError):
            spec_from_cmd(2, bad)


# ---- fields / where ops ------------------------------------------------------------------------

MSG = {'header': {'stamp': {'sec': 1, 'nanosec': 500}, 'frame_id': 'cam'},
       'detections': [{'bbox': {'center': {'position': {'x': 1.5}}}, 'id': 'a'},
                      {'bbox': {'center': {'position': {'x': 2.0}}}, 'id': 'b'}],
       'data': 'Hello World: 12', 'level': 3, 'ok': True, 'value': 0.1 + 0.2,
       'big': {'_truncated': True, 'length': 1000, 'head': [7, 8]}}


def cond(**kw):
    return Condition(**kw)


@pytest.mark.parametrize('kw,expected', [
    ({'field': 'level', 'op': 'eq', 'value': 3}, True),
    ({'field': 'level', 'op': 'eq', 'value': 3.0}, True),
    ({'field': 'ok', 'op': 'eq', 'value': 1}, False),          # bool is not a number
    ({'field': 'ok', 'op': 'eq', 'value': True}, True),
    ({'field': 'level', 'op': 'ne', 'value': 2}, True),
    ({'field': 'level', 'op': 'lt', 'value': 3}, False),
    ({'field': 'level', 'op': 'le', 'value': 3}, True),
    ({'field': 'level', 'op': 'gt', 'value': 2}, True),
    ({'field': 'level', 'op': 'ge', 'value': 4}, False),
    ({'field': 'level', 'op': 'range', 'min': 1, 'max': 3}, True),
    ({'field': 'level', 'op': 'range', 'min': 4}, False),
    ({'field': 'value', 'op': 'approx', 'value': 0.3}, True),
    ({'field': 'value', 'op': 'approx', 'value': 0.31, 'tol': 0.001}, False),
    ({'field': 'data', 'op': 'regex', 'value': r'^Hello World: \d+$'}, True),
    ({'field': 'data', 'op': 'contains', 'value': 'World'}, True),
    ({'field': 'detections.1.id', 'op': 'contains', 'value': 'x'}, False),
    ({'field': 'header.frame_id', 'op': 'exists'}, True),
    ({'field': 'header.nope', 'op': 'exists'}, False),
    ({'field': 'detections', 'op': 'len_eq', 'value': 2}, True),
    ({'field': 'detections', 'op': 'len_range', 'min': 3}, False),
    ({'field': 'big', 'op': 'len_eq', 'value': 1000}, True),
    ({'field': 'big.1', 'op': 'eq', 'value': 8}, True),
    ({'field': 'detections.0.bbox.center.position.x', 'op': 'approx', 'value': 1.5}, True),
    ({'field': 'data', 'op': 'gt', 'value': 1}, False),        # a string is not a number
])
def test_ops(kw, expected):
    assert fields.check(cond(**kw), MSG)[0] is expected


def test_field_errors_are_plain():
    ok, _, reason = fields.check(cond(field='header.stam', op='exists'), MSG)
    assert not ok and 'stam というフィールドはありません' in reason and 'stamp' in reason
    ok, _, reason = fields.check(cond(field='detections.5.id', op='exists'), MSG)
    assert '範囲外' in reason and '2 個' in reason
    ok, _, reason = fields.check(cond(field='big.9', op='exists'), MSG)
    assert '先頭 2 個' in reason
    ok, _, reason = fields.check(cond(field='level.x', op='exists'), MSG)
    assert 'その先' in reason
    assert fields.check(cond(field='data', op='eq', value='x'), MSG)[2] == '実際は "Hello World: 12"'


def test_plain_capped_keeps_length_of_big_arrays():
    import array
    data = fields.plain_capped({'data': array.array('B', bytes(1000)), 'small': [1, 2]})
    assert data['data']['_truncated'] and data['data']['length'] == 1000
    assert len(data['data']['head']) == fields.HEAD_ITEMS and data['small'] == [1, 2]
    assert fields.stamp_ns(MSG) == 1_000_000_500


# ---- checks -----------------------------------------------------------------------------------

def rec(t, plain):
    return Record(t, t, plain)


def entry(steps):
    return scenario(steps).steps[0]


def test_expect_pass_and_failure_message():
    e = entry([{'expect': {'topic': '/s', 'within': 1.0,
                           'where': [{'field': 'data', 'op': 'eq', 'value': 'RUNNING'}]}}])
    check = make_check('expect', e.spec, 10.0)
    check.feed('/s', rec(9.0, {'data': 'RUNNING'}))  # before the window: ignored
    check.feed('/s', rec(10.2, {'data': 'IDLE'}))
    assert check.poll(10.5) is None
    verdict = check.poll(11.0)
    assert not verdict.passed
    assert '1.0' not in verdict.message and '1 秒以内' in verdict.message
    assert '条件に合ったのは 0 件' in verdict.message and '"IDLE"' in verdict.message
    assert 'data = "RUNNING" → 実際は "IDLE"' in verdict.message
    assert verdict.details['received'] == 1
    check.feed('/s', rec(10.8, {'data': 'RUNNING'}))
    assert check.poll(11.0).passed


def test_expect_nothing_received():
    e = entry([{'expect': {'topic': '/s', 'within': 0.5}}])
    verdict = make_check('expect', e.spec, 0.0).poll(0.6)
    assert not verdict.passed and '1 件も届きませんでした' in verdict.message


def test_always_and_never():
    always = make_check('always', entry([{'always': {
        'topic': '/s', 'for': 1.0, 'where': [{'field': 'v', 'op': 'lt', 'value': 5}]}}]).spec, 0.0)
    always.feed('/s', rec(0.1, {'v': 1}))
    assert always.poll(0.5) is None
    always.feed('/s', rec(0.6, {'v': 9}))
    verdict = always.poll(0.6)
    assert not verdict.passed and '0.6 秒後' in verdict.message and 'v < 5 → 実際は 9' in verdict.message
    empty = make_check('always', entry([{'always': {'topic': '/s', 'for': 1.0}}]).spec, 0.0)
    assert '1 件も届きませんでした' in empty.poll(1.0).message
    never = make_check('never', entry([{'never': {'topic': '/s', 'for': 1.0}}]).spec, 0.0)
    assert never.poll(1.0).passed
    never.feed('/s', rec(0.3, {'v': 1}))
    assert not never.poll(1.0).passed


def test_guard_violation_and_finish():
    sc = parse_data({'name': 'g', 'steps': [{'wait': 1}], 'guards': [
        {'never': {'topic': '/state', 'where': [{'field': 'data', 'op': 'eq', 'value': 'ERROR'}]}},
        {'always': {'topic': '/state', 'where': [{'field': 'data', 'op': 'ne', 'value': ''}]}}]})
    never = make_guard('never', sc.guards[0].spec, 0.0)
    always = make_guard('always', sc.guards[1].spec, 0.0)
    for t, value in ((1.0, 'IDLE'), (2.0, 'RUNNING')):
        never.feed('/state', rec(t, {'data': value}))
        always.feed('/state', rec(t, {'data': value}))
    assert never.poll(100.0) is None and always.poll(100.0) is None  # guards never time out
    assert never.finish(100.0).passed and always.finish(100.0).passed
    never.feed('/state', rec(3.0, {'data': 'ERROR'}))
    verdict = never.poll(3.1)
    assert not verdict.passed and '来てはいけない' in verdict.message


def test_rate_reuses_window_rate():
    spec = entry([{'rate': {'topic': '/s', 'for': 3.0, 'min_hz': 9, 'max_hz': 11}}]).spec
    check = make_check('rate', spec, 100.0)
    times = [100.0 + i * 0.1 for i in range(30)]
    for t in times:
        check.feed('/s', rec(t, {}))
    verdict = check.poll(103.0)
    assert verdict.passed and verdict.details['hz'] == window_rate(times, 103.0, 3.0, 3.0)[0]
    stopped = make_check('rate', spec, 0.0)
    for i in range(10):
        stopped.feed('/s', rec(i * 0.1, {}))
    verdict = stopped.poll(3.0)
    assert not verdict.passed and '止まりました' in verdict.message
    few = make_check('rate', spec, 0.0)
    few.feed('/s', rec(2.9, {}))
    assert '測れませんでした' in few.poll(3.0).message


def test_window_rate_retain_covers_long_steps():
    times = [i * 1.0 for i in range(21)]  # 1 Hz for 20 s
    assert window_rate(times, 20.0, 20.0, retain_sec=20.0)[0] == pytest.approx(1.0)
    assert window_rate(times, 20.0, 20.0)[0] == pytest.approx(1.0)  # default: last 10 s


def test_throughput():
    spec = entry([{'throughput': {'input': '/in', 'output': '/out', 'for': 1.0,
                                  'min_ratio': 0.9}}]).spec
    check = make_check('throughput', spec, 0.0)
    for i in range(10):
        check.feed('/in', rec(i * 0.1, {}))
        if i % 2 == 0:
            check.feed('/out', rec(i * 0.1 + 0.01, {}))
    verdict = check.poll(1.0)
    assert not verdict.passed and verdict.details['ratio'] == 0.5 and '取りこぼし' in verdict.message
    empty = make_check('throughput', spec, 0.0)
    assert '1 件も届かなかった' in empty.poll(1.0).message


def stamped(t, sec):
    return rec(t, {'header': {'stamp': {'sec': sec, 'nanosec': 0}}})


def test_latency_header_stamp_and_order():
    inputs = [stamped(i * 0.1, i) for i in range(10)]
    outputs = [stamped(i * 0.1 + 0.02, i) for i in range(10) if i != 4]
    latencies, unmatched = pair_by_stamp(inputs, outputs)
    assert len(latencies) == 9 and unmatched == 0
    assert all(abs(v - 0.02) < 1e-9 for v in latencies)
    # Order mode shifts after the dropped one: the approximation the docs warn about.
    order, _ = pair_by_order(inputs, outputs)
    assert len(order) == 9 and max(order) > 0.1
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert percentile([5.0], 50) == 5.0
    spec = entry([{'latency': {'input': '/in', 'output': '/out', 'for': 1.0, 'p95_ms': 10}}]).spec
    check = make_check('latency', spec, 0.0)
    for r in inputs:
        check.feed('/in', r)
    for r in outputs:
        check.feed('/out', r)
    verdict = check.poll(1.0)
    assert not verdict.passed and 'p95 20.0 ms > 上限 10 ms' in verdict.message
    order_spec = entry([{'latency': {'input': '/in', 'output': '/out', 'for': 1.0,
                                     'match': 'order', 'p95_ms': 500}}]).spec
    approx = make_check('latency', order_spec, 0.0)
    for r in inputs:
        approx.feed('/in', r)
    for r in outputs:
        approx.feed('/out', r)
    verdict = approx.poll(1.0)
    assert verdict.passed and verdict.approx and '近似' in verdict.message


def test_latency_stamp_mismatch_suggests_order():
    spec = entry([{'latency': {'input': '/in', 'output': '/out', 'for': 1.0, 'p95_ms': 10}}]).spec
    check = make_check('latency', spec, 0.0)
    for i in range(5):
        check.feed('/in', stamped(i * 0.1, i))
        check.feed('/out', stamped(i * 0.1 + 0.01, 1000 + i))
    verdict = check.poll(1.0)
    assert not verdict.passed and 'match: order' in verdict.message


# ---- hints / junit -----------------------------------------------------------------------------

def test_hints_no_publisher_similar_qos_type():
    reliable = {'reliability': 'reliable', 'durability': 'volatile'}
    best = {'reliability': 'best_effort', 'durability': 'volatile'}
    raw = RawGraph(nodes=[('a', '/'), ('b', '/')],
                   topics={'/detection': ['x/msg/A'], '/cmd': ['std_msgs/msg/String'],
                           '/scan': ['x/msg/A', 'x/msg/B']},
                   publishers={'/detection': [Endpoint('/a', best)], '/scan': [Endpoint('/a', best)],
                               '/cmd': [Endpoint('/roshanavi_scenario', reliable)]},
                   subscribers={'/scan': [Endpoint('/b', reliable)]})
    found = hints(raw, inputs=['/cmd'], outputs=['/detections', '/scan'])
    codes = [h['code'] for h in found]
    assert codes.count('no_publisher') == 1 and '/detection' in found[0]['message']
    assert 'no_subscriber' in codes and 'qos_incompatible' in codes and 'type_mismatch' in codes


def test_junit_is_valid_xml():
    sc = parse_data({'name': 'j<&>', 'steps': [{'wait': 0.1}, {'expect': {'topic': '/a',
                                                                          'within': 1}}]})
    result = new_result(sc, 'j.yaml')
    result.status = FAILED
    result.steps[0].status = PASSED
    result.steps[1].status, result.steps[1].message = FAILED, 'だめ \x01 "x"'
    root = ET.fromstring(to_junit([result]).encode())
    assert root.tag == 'testsuites' and root.get('tests') == '2' and root.get('failures') == '1'
    case = root.find('testsuite/testcase[2]/failure')
    assert case is not None and 'だめ' in case.get('message')
