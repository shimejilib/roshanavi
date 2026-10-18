"""Node <-> process mapping: pure logic (no processes, no ROS)."""

import os
import subprocess
import sys
import time

from roshanavi.process_map import (NodeProcessMapper, ProcInfo, TargetProcs, map_nodes,
                                   process_tree, ros_identity)

RUN_WRAPPER = ('/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'run', 'demo_nodes_cpp', 'talker',
               '--ros-args', '-r', '__node:=cam')


def proc(pid, ppid, depth, *cmd):
    return ProcInfo(pid=pid, ppid=ppid, depth=depth, cmdline=tuple(cmd))


def test_ros_identity_variants():
    assert ros_identity(['x', '--ros-args', '-r', '__node:=talker']) == '/talker'
    assert ros_identity(['x', '--ros-args', '-r', '__node:=t', '-r', '__ns:=/robot']) == '/robot/t'
    assert ros_identity(['x', '-r', 'talker:__node:=renamed', '-r', '__ns:=ns']) == '/ns/renamed'
    assert ros_identity(['x', '--ros-args', '-r', 'chatter:=/c']) is None
    assert ros_identity([]) is None


def test_exact_prefers_the_deepest_process():
    target = TargetProcs('t1', 100.0, (
        proc(10, 1, 0, *RUN_WRAPPER),
        proc(11, 10, 1, '/opt/ros/jazzy/lib/demo_nodes_cpp/talker', '--ros-args', '-r',
             '__node:=cam'),
    ))
    mapping = map_nodes(['/cam', '/other'], [target], first_seen={'/cam': 0, '/other': 101})
    assert mapping['/cam'].confidence == 'exact'
    assert mapping['/cam'].pid == 11
    assert mapping['/other'].confidence == 'heuristic'  # appeared right after the start


def test_heuristic_window_and_baseline():
    target = TargetProcs('t1', 100.0, (proc(10, 1, 0, 'talker'),))
    seen = {'/early': 50.0, '/talker': 101.0, '/late': 200.0, '/base': 101.0}
    mapping = map_nodes(seen, [target], seen, baseline={'/base'}, window_sec=20)
    assert set(mapping) == {'/talker'}
    assert mapping['/talker'].pid == 10


def test_heuristic_tie_break_by_executable_name():
    a = TargetProcs('a', 100.0, (proc(10, 1, 0, '/lib/pkg/talker'),))
    b = TargetProcs('b', 100.5, (proc(20, 1, 0, '/lib/pkg/listener'),))
    seen = {'/talker': 102.0, '/listener': 102.0, '/anon': 102.0}
    mapping = map_nodes(seen, [a, b], seen)
    assert mapping['/talker'].target_id == 'a'
    assert mapping['/listener'].target_id == 'b'
    assert mapping['/anon'].target_id == 'b'  # no name match: most recently started


def test_launch_service_node_maps_to_the_launch_process_not_to_a_container():
    # ros2 launch (pid 10) started a composable container (pid 11); the nodes inside live in 11,
    # but launch_ros_10 is the launch service's own node and lives in 10.
    target = TargetProcs('pipe', 100.0, (
        proc(10, 1, 0, '/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'launch', 'p', 'f.py'),
        proc(11, 10, 1, '/opt/ros/jazzy/lib/rclcpp_components/component_container'),
    ))
    seen = {'/launch_ros_10': 101.0, '/relay_1': 101.0, '/launch_ros_999': 101.0}
    mapping = map_nodes(seen, [target], seen)
    assert mapping['/launch_ros_10'].pid == 10
    assert mapping['/relay_1'].pid == 11  # a node of the container
    assert mapping['/launch_ros_999'].pid == 11  # somebody else's pid: no special case


def test_dead_targets_do_not_claim():
    dead = TargetProcs('t1', 100.0, ())
    assert map_nodes(['/n'], [dead], {'/n': 101.0}) == {}


def test_mapper_is_sticky_and_baseline_learns_idle_nodes():
    now = {'t': 0.0}
    mapper = NodeProcessMapper(window_sec=5, clock=lambda: now['t'],
                               tree=lambda pid: (proc(pid, 1, 0, 'x'),))
    assert mapper.update(['/pre'], []) == {}          # idle: /pre becomes baseline
    now['t'] = 10.0
    mapper.update(['/pre'], [('t1', 10.0, 42)])
    now['t'] = 11.0
    mapping = mapper.update(['/pre', '/mine'], [('t1', 10.0, 42)])
    assert set(mapping) == {'/mine'}
    now['t'] = 100.0                                  # far outside the window: still mapped
    assert set(mapper.update(['/pre', '/mine'], [('t1', 10.0, 42)])) == {'/mine'}
    assert mapper.update(['/pre', '/mine'], []) == {}  # target gone -> unmapped


def test_process_tree_of_real_processes():
    child = subprocess.Popen([sys.executable, '-c',
                              'import subprocess,sys,time;'
                              'p=subprocess.Popen([sys.executable,"-c","import time;'
                              'time.sleep(30)","__node:=deep"]);time.sleep(30)'])
    try:
        deadline = time.monotonic() + 5
        tree = process_tree(child.pid)
        while len(tree) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
            tree = process_tree(child.pid)
        assert tree[0].pid == child.pid and tree[0].depth == 0
        assert tree[1].depth == 1 and ros_identity(tree[1].cmdline) == '/deep'
    finally:
        for p in process_tree(child.pid)[::-1]:
            os.kill(p.pid, 9)
        child.wait()
