"""Scenario steps ``resources`` / ``mem_growth``: schema and judging with fed samples (pure)."""

import pytest

from roshanavi.resources.leak import MIB
from roshanavi.resources.node_probe import NodeSample, find_by_cmdline, segments
from roshanavi.resources.procs import ProcRow
from roshanavi.scenario.checks import make_check
from roshanavi.scenario.schema import ScenarioSchemaError, dump, parse_data, parse_text


def scenario(steps):
    return parse_data({'name': 't', 'steps': steps})


def errors_of(steps):
    with pytest.raises(ScenarioSchemaError) as info:
        scenario(steps)
    return {e['path']: e['message'] for e in info.value.errors}


# ---- schema -----------------------------------------------------------------------------------

def test_resources_defaults_relative_node_and_round_trip():
    sc = scenario([{'resources': {'node': 'detector', 'cpu_max': 80}},
                   {'mem_growth': {'node': '/ns/detector', 'max_mb_per_min': 1, 'for': 30}}])
    res, growth = sc.steps[0].spec, sc.steps[1].spec
    assert res.node == '/detector' and res.for_ == 5.0 and res.mem_max_mb is None
    assert growth.node == '/ns/detector' and growth.for_ == 30
    assert sc.topics() == []  # nothing to pre-subscribe
    again = parse_text(dump(sc))
    assert again.steps == sc.steps
    assert "for: 5.0" in dump(sc)  # the default window is written out


def test_step_summaries():
    from roshanavi.scenario.result import new_result
    sc = scenario([{'resources': {'node': '/d', 'cpu_max': 40, 'mem_max_mb': 300}},
                   {'resources': {'node': '/d', 'mem_max_mb': 300, 'for': 2}},
                   {'mem_growth': {'node': '/d', 'max_mb_per_min': 1, 'for': 30}}])
    summaries = [s.summary for s in new_result(sc).steps]
    assert summaries == ['/d の負荷が CPU 平均 ≤ 40%、メモリ ≤ 300 MB (5 秒)',
                         '/d の負荷が メモリ ≤ 300 MB (2 秒)',
                         '/d のメモリの増え方が 1 MB/分以下 (30 秒)']


def test_resources_needs_a_limit_and_a_valid_node():
    errors = errors_of([{'resources': {'node': '/a'}}])
    assert 'cpu_max か mem_max_mb' in errors['steps.0.resources']
    errors = errors_of([{'resources': {'node': '/a b', 'cpu_max': 5}}])
    assert 'ノード名' in errors['steps.0.resources.node']
    errors = errors_of([{'resources': {'node': '/a', 'cpu_max': -1}}])
    assert 'steps.0.resources.cpu_max' in errors


def test_mem_growth_needs_for_of_at_least_ten_seconds():
    errors = errors_of([{'mem_growth': {'node': '/a', 'max_mb_per_min': 1}}])
    assert errors['steps.0.mem_growth.for'] == '必須の項目がありません'
    errors = errors_of([{'mem_growth': {'node': '/a', 'max_mb_per_min': 1, 'for': 5}}])
    assert '10 秒以上' in errors['steps.0.mem_growth.for']


def test_unknown_key_in_resources_step():
    errors = errors_of([{'resources': {'node': '/a', 'cpu_max': 5, 'gpu_max': 1}}])
    assert 'steps.0.resources.gpu_max' in errors


# ---- judging ----------------------------------------------------------------------------------

def spec_of(step):
    entry = scenario([step]).steps[0]
    return entry.kind, entry.spec


def run_check(step, samples, t0=0.0, confidence='exact'):
    kind, spec = spec_of(step)
    check = make_check(kind, spec, t0)
    for t, cpu_s, rss_mb, *pid in samples:
        sample = NodeSample(t, tuple(pid) or (42,), cpu_s, int(rss_mb * MIB), confidence)
        check.feed_sample(sample, t)
    assert check.poll(t0 + spec.for_ - 0.01) is None  # never before the window ends
    return check.poll(t0 + spec.for_ + 0.01)


def steady(seconds, cpu_pct, rss_mb, step=0.5):
    n = int(seconds / step) + 1
    return [(i * step, i * step * cpu_pct / 100.0, rss_mb) for i in range(n)]


def test_resources_passes_with_average_cpu_and_peak_memory():
    verdict = run_check({'resources': {'node': '/n', 'cpu_max': 50, 'mem_max_mb': 200,
                                       'for': 4}}, steady(4, 20.0, 120))
    assert verdict.passed, verdict.message
    assert verdict.details['cpu_avg_pct'] == pytest.approx(20.0)
    assert verdict.details['mem_max_mb'] == pytest.approx(120.0)
    assert 'CPU は平均 20.0%' in verdict.message and '推定' not in verdict.message


def test_resources_fails_on_cpu_and_reports_why():
    verdict = run_check({'resources': {'node': '/busy', 'cpu_max': 50, 'for': 4}},
                        steady(4, 89.0, 60))
    assert not verdict.passed and 'CPU が上限を超えました' in verdict.message
    assert verdict.details['cpu_avg_pct'] == pytest.approx(89.0)


def test_resources_one_spike_does_not_fail_the_average_but_is_reported():
    samples = steady(4, 10.0, 60)
    t, cpu, rss = samples[4]
    samples = [*samples[:4], (t, cpu + 0.4, rss),  # +0.4 s CPU in one 0.5 s step = 80 %+
               *[(a, b + 0.4, c) for a, b, c in samples[5:]]]
    verdict = run_check({'resources': {'node': '/n', 'cpu_max': 30, 'for': 4}}, samples)
    assert verdict.passed and verdict.details['cpu_peak_pct'] > 80


def test_resources_memory_peak_fails():
    samples = [*steady(4, 1.0, 100)[:-1], (4.0, 0.04, 700)]
    verdict = run_check({'resources': {'node': '/n', 'mem_max_mb': 500, 'for': 4}}, samples)
    assert not verdict.passed and 'メモリが上限を超えました' in verdict.message


def test_resources_node_not_found():
    verdict = run_check({'resources': {'node': '/gone', 'cpu_max': 5, 'for': 2}}, [])
    assert not verdict.passed and '見つかりませんでした' in verdict.message


def test_resources_heuristic_match_is_marked():
    verdict = run_check({'resources': {'node': '/n', 'cpu_max': 50, 'for': 2}},
                        steady(2, 5.0, 10), confidence='heuristic')
    assert verdict.passed and '推定' in verdict.message


def test_resources_restart_counts_cpu_per_process():
    first = [(0.0, 100.0, 50, 1), (1.0, 100.2, 50, 1)]  # 20 % on pid 1
    second = [(1.5, 0.0, 50, 2), (3.0, 0.3, 50, 2)]  # 20 % on pid 2 (counter starts over)
    verdict = run_check({'resources': {'node': '/n', 'cpu_max': 50, 'for': 3}}, first + second)
    assert verdict.passed and verdict.details['cpu_avg_pct'] == pytest.approx(20.0)


def test_mem_growth_flat_passes_and_growing_fails():
    flat = [(t, 0.0, 100 + (0.3 if i % 2 else -0.3)) for i, t in enumerate(range(0, 21))]
    verdict = run_check({'mem_growth': {'node': '/n', 'max_mb_per_min': 1, 'for': 20}}, flat)
    assert verdict.passed and abs(verdict.details['slope_mb_per_min']) < 1
    growing = [(t, 0.0, 100 + t * 0.1) for t in range(0, 21)]  # 6 MB/min
    verdict = run_check({'mem_growth': {'node': '/n', 'max_mb_per_min': 1, 'for': 20}}, growing)
    assert not verdict.passed and verdict.details['slope_mb_per_min'] == pytest.approx(6.0)
    assert 'メモリリークの疑い' in verdict.message


def test_mem_growth_restart_mid_window_cannot_be_judged():
    samples = [(t, 0.0, 100.0, 1) for t in range(0, 15)] + [(t, 0.0, 50.0, 2)
                                                             for t in range(15, 21)]
    verdict = run_check({'mem_growth': {'node': '/n', 'max_mb_per_min': 1, 'for': 20}}, samples)
    assert not verdict.passed and '再起動' in verdict.message


def test_segments_split_on_pid_change():
    s = [NodeSample(t, (p,), 0.0, 0, 'exact') for t, p in ((0, 1), (1, 1), (2, 2), (3, 2))]
    assert [len(seg) for seg in segments(s)] == [2, 2]


def test_find_by_cmdline_prefers_the_program_then_unique_exe():
    def row(pid, ppid, name, cmdline):
        return ProcRow(pid, ppid, name, tuple(cmdline), 1.0, 0.0, 0)
    rows = {r.pid: r for r in (
        row(10, 1, 'ros2', ['/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'run', 'p', 'e',
                            '--ros-args', '-r', '__node:=det']),
        row(11, 10, 'e', ['/x/e', '--ros-args', '-r', '__node:=det']),
        row(20, 1, 'talker', ['/opt/ros/jazzy/lib/demo_nodes_cpp/talker']))}
    assert find_by_cmdline(rows, '/det') == 11
    assert find_by_cmdline(rows, '/talker') == 20
    assert find_by_cmdline(rows, '/nobody') is None
