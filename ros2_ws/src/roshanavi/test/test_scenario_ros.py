"""Scenarios against real nodes: examples pass, broken variants fail with explanations,
setup teardown, pre-subscription, project targets, CLI exit codes and JUnit."""

import copy
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import psutil
import pytest
import yaml
from std_msgs.msg import String

from conftest import WS_ROOT
from roshanavi.ros_runtime import RosRuntime
from roshanavi.scenario import parse_data
from roshanavi.scenario.api import run_scenario
from roshanavi.scenario.result import ERROR, FAILED, PASSED, SKIPPED

EXAMPLES = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')
SCENARIOS = os.path.join(EXAMPLES, 'scenarios')


@pytest.fixture(scope='module')
def runtime():
    rt = RosRuntime('roshanavi_scenario_test')
    rt.start()
    yield rt
    rt.stop()


def raw(name):
    with open(os.path.join(SCENARIOS, name), encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def run(data, runtime, data_dir, **kw):
    scenario = data if not isinstance(data, dict) else parse_data(data)
    return run_scenario(scenario, runtime=runtime, data_dir=str(data_dir), workspace=WS_ROOT, **kw)


def children():
    return [p for p in psutil.Process().children(recursive=True) if p.is_running()
            and p.status() != psutil.STATUS_ZOMBIE]


def assert_passed(result):
    assert result.status == PASSED, '\n'.join(result.failures()) + '\n' + result.message
    assert children() == []  # setup processes are gone


@pytest.fixture(scope='module')
def samples(tmp_path_factory):
    from roshanavi import sample_media
    data = tmp_path_factory.mktemp('scenario_data')
    sample_media.ensure_samples(str(data))
    assert os.path.isfile(os.path.join(data, 'samples', 'blobs.mp4'))
    return data


# ---- examples pass ---------------------------------------------------------------------------

def test_state_machine_example_and_broken_variants(runtime, data_dir):
    assert_passed(run(raw('state_machine.yaml'), runtime, data_dir))
    broken = raw('state_machine.yaml')
    broken['steps'][3]['expect']['where'][0]['value'] = 'RUNNING'
    result = run(broken, runtime, data_dir)
    step = result.steps[3]
    assert result.status == FAILED and step.status == FAILED
    assert '実際は "IDLE"' in step.message and '条件に合ったのは 0 件' in step.message
    assert result.steps[4].status == SKIPPED and children() == []


def test_guard_violation_mid_step(runtime, data_dir):
    data = raw('state_machine.yaml')
    data['steps'] = [{'send': {'topic': '/scenario/sm/cmd', 'kind': 'string', 'value': 'fault'}},
                     {'wait': 3.0}, {'send': {'topic': '/scenario/sm/cmd', 'data': {'data': 'x'}}}]
    result = run(data, runtime, data_dir)
    assert result.status == FAILED
    assert result.guards[0].status == FAILED and '"ERROR"' in result.guards[0].message
    wait = result.steps[1]
    assert wait.status == FAILED and 'ガード 1 が破れた' in wait.message
    assert wait.duration_sec < 2.0  # stopped in the middle of the 3 s wait
    assert result.steps[2].status == SKIPPED and children() == []


def test_chatter_smoke_and_no_publisher_hint(runtime, data_dir):
    assert_passed(run(raw('chatter_smoke.yaml'), runtime, data_dir))
    broken = raw('chatter_smoke.yaml')
    broken['steps'] = [{'expect': {'topic': '/scenario/smoke/chater', 'within': 1.0,
                                   'type': 'std_msgs/msg/String'}}]
    result = run(broken, runtime, data_dir)
    step = result.steps[0]
    assert step.status == FAILED and '1 件も届きませんでした' in step.message
    codes = {h['code']: h['message'] for h in step.hints}
    assert '/scenario/smoke/chatter' in codes['no_publisher']  # similar published name


def test_function_node_example(runtime, data_dir):
    assert_passed(run(raw('function_shout.yaml'), runtime, data_dir))


def test_class_node_example_and_a_variant_without_the_reset(runtime, data_dir):
    result = run(raw('class_moving_average.yaml'), runtime, data_dir)
    assert_passed(result)
    assert result.steps[5].kind == 'call'
    broken = raw('class_moving_average.yaml')
    broken['steps'][5] = {'wait': 0.2}       # no reset: the old 20 and 30 are still in the window
    result = run(broken, runtime, data_dir)
    assert result.status == FAILED and result.steps[7].status == FAILED
    assert children() == []


def test_perception_examples(runtime, samples):
    result = run(raw('perception.yaml'), runtime, samples)
    assert_passed(result)
    latency = result.steps[3]
    assert latency.details['pairs'] >= 30 and not latency.approx
    order = run(raw('perception_order.yaml'), runtime, samples)
    assert_passed(order)
    assert order.steps[3].approx and '近似' in order.steps[3].message


def test_perception_stamp_mode_fails_without_keep_stamp(runtime, samples):
    data = raw('perception_order.yaml')
    data['steps'][3]['latency']['match'] = 'header.stamp'
    result = run(data, runtime, samples)
    step = result.steps[3]
    assert step.status == FAILED and 'match: order' in step.message


# ---- runner behaviour --------------------------------------------------------------------------

def test_pre_subscription_catches_an_immediate_response(runtime, data_dir, helper):
    pub = helper.node.create_publisher(String, '/scn_test/pong', 10)
    helper.node.create_subscription(String, '/scn_test/ping',
                                    lambda m: pub.publish(String(data=m.data.upper())), 10)
    data = {'name': 'ping', 'steps': [
        {'send': {'topic': '/scn_test/ping', 'kind': 'string', 'value': 'a'}},
        {'expect': {'topic': '/scn_test/pong', 'within': 0.3,
                    'where': [{'field': 'data', 'op': 'eq', 'value': 'A'}]}}] * 5}
    result = run(data, runtime, data_dir)
    assert result.status == PASSED, result.failures()


def test_unknown_type_hint_and_type_required(runtime, data_dir):
    result = run({'name': 'u', 'steps': [{'expect': {'topic': '/scn_test/nobody', 'within': 0.3}}]},
                 runtime, data_dir)
    assert result.steps[0].status == FAILED
    assert 'type_unknown' in [h['code'] for h in result.steps[0].hints]
    result = run({'name': 'u', 'steps': [{'send': {'topic': '/scn_test/nowhere',
                                                   'data': {'data': 1}}}]}, runtime, data_dir)
    assert result.steps[0].status == ERROR and 'type' in result.steps[0].message


def test_setup_failure_leaves_no_process(runtime, data_dir):
    data = {'name': 's', 'setup': [
        {'run': {'package': 'demo_nodes_cpp', 'executable': 'talker', 'name': 'scn_t1'}},
        {'run': {'package': 'demo_nodes_cpp', 'executable': 'listener', 'name': 'scn_l1'},
         'wait_for_node': '/never_there', 'wait_timeout': 1.0}],
        'steps': [{'wait': 0.1}]}
    result = run(data, runtime, data_dir)
    assert result.status == FAILED and result.setup[0].status == PASSED
    assert result.setup[1].status == FAILED and '/never_there' in result.setup[1].message
    assert result.steps[0].status == SKIPPED
    assert children() == []
    bad = run({'name': 's', 'setup': [{'run': {'package': 'no_such_pkg', 'executable': 'x'}}],
               'steps': [{'wait': 0.1}]}, runtime, data_dir)
    assert bad.setup[0].status == FAILED and 'パッケージが見つかりません' in bad.setup[0].message
    crashed = run({'name': 's', 'setup': [{'run': {'package': 'demo_nodes_cpp',
                                                   'executable': 'talker', 'name': 'scn_t2',
                                                   'args': ['--definitely-bad-flag']}}],
                   'steps': [{'wait': 0.1}]}, runtime, data_dir)
    assert crashed.setup[0].status in (FAILED, PASSED)
    assert children() == []


def test_project_targets_are_restored(runtime, data_dir, tmp_path):
    project = tmp_path / 'roshanavi.yaml'
    project.write_text(yaml.safe_dump({'version': 1, 'dummies': [{
        'id': 'beat', 'name': 'scn_beat', 'topic': '/scn_test/beat', 'type': 'std_msgs/msg/String',
        'mode': 'periodic', 'payload': {'data': 'beat ${i}'}, 'rate_hz': 10}]}))
    data = {'name': 't', 'steps': [
        {'start': {'target': 'beat'}},
        {'expect': {'topic': '/scn_test/beat', 'within': 10.0, 'type': 'std_msgs/msg/String',
                    'where': [{'field': 'data', 'op': 'regex', 'value': '^beat \\d+$'}]}},
        {'stop': 'beat'},
        {'wait': 0.5},
        {'never': {'topic': '/scn_test/beat', 'for': 0.5}},
        {'start': {'target': 'beat', 'id': 'beat2'}},
        {'expect': {'topic': '/scn_test/beat', 'within': 10.0}},
        {'stop': {'target': 'beat'}},
        {'wait': 0.5},
        {'never': {'topic': '/scn_test/beat', 'for': 1.0}}]}
    result = run(data, runtime, data_dir, project=str(project))
    assert_passed(result)
    missing = run({'name': 't', 'steps': [{'start': {'target': 'nope'}}]}, runtime, data_dir,
                  project=str(project))
    assert missing.steps[0].status == ERROR and 'nope' in missing.steps[0].message


def test_cancel_stops_and_tears_down(runtime, data_dir):
    import threading
    cancel = threading.Event()
    timer = threading.Timer(1.5, cancel.set)
    timer.start()
    data = {'name': 'c', 'setup': [{'run': {'package': 'demo_nodes_cpp', 'executable': 'talker',
                                            'name': 'scn_cancel'}}],
            'steps': [{'wait': 30.0}]}
    result = run(data, runtime, data_dir, cancel=cancel)
    timer.cancel()
    assert result.status == 'cancelled' and result.duration_sec < 15
    assert children() == []


# ---- CLI ----------------------------------------------------------------------------------------

def cli(*args, cwd=None):
    return subprocess.run(['ros2', 'run', 'roshanavi', 'scenario', 'run', *args],
                          capture_output=True, text=True, timeout=120, cwd=cwd)


def test_cli_exit_codes_and_junit(tmp_path):
    good = tmp_path / 'good'
    good.mkdir()
    data = copy.deepcopy(raw('state_machine.yaml'))
    (good / 'sm.yaml').write_text(yaml.safe_dump(data, allow_unicode=True))
    junit = tmp_path / 'out' / 'junit.xml'
    done = cli(str(good), '--junit', str(junit), '--json', str(tmp_path / 'r.json'),
               '--workspace', WS_ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '1/1 シナリオが成功しました' in done.stdout
    root = ET.parse(junit).getroot()
    assert root.get('tests') == '7' and root.get('failures') == '0'  # setup + 5 steps + guard
    bad = tmp_path / 'bad'
    bad.mkdir()
    data['steps'][1]['expect']['where'][0]['value'] = 'FLYING'
    (bad / 'a.yaml').write_text(yaml.safe_dump(data, allow_unicode=True))
    (bad / 'b.yaml').write_text('name: b\nsteps:\n  - wiat: 1\n')
    done = cli(str(bad), '--junit', str(junit), '--workspace', WS_ROOT)
    assert done.returncode == 1
    assert '実際は "RUNNING"' in done.stdout and '3 行目' in done.stdout
    root = ET.parse(junit).getroot()
    assert len(root.findall('testsuite')) == 2 and int(root.get('failures')) >= 1
    assert int(root.get('errors')) >= 1
    assert cli(str(tmp_path / 'missing.yaml')).returncode == 2


def test_launch_pytest_example():
    pytest.importorskip('launch_pytest')
    done = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q',
                           os.path.join(EXAMPLES, 'launch_pytest',
                                        'test_state_machine_launch.py')],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
