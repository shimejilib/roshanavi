"""launch_pytest + roshanavi のシナリオ: launch でノードを起動し、判定をシナリオに任せる例。

    python3 -m pytest examples/launch_pytest/test_state_machine_launch.py

launch_pytest がノードを起動・停止し、テスト関数の中で ``run_scenario`` を呼ぶ。
``run_scenario`` は自分の rclpy コンテキストを持つので、launch と同じプロセスで動かせる。
"""

import os

import launch
import launch_pytest
import launch_ros.actions
import pytest

from roshanavi.scenario import run_scenario

SCENARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state_machine_scenario.yaml')


@launch_pytest.fixture
def state_machine():
    return launch.LaunchDescription([
        launch_ros.actions.Node(
            package='roshanavi_examples', executable='state_machine', name='lp_state_machine',
            parameters=[{'publish_period_sec': 0.0}],
            remappings=[('cmd', '/lp/cmd'), ('state', '/lp/state')]),
        launch_pytest.actions.ReadyToTest(),
    ])


@pytest.mark.launch(fixture=state_machine)
def test_state_machine_scenario():
    result = run_scenario(SCENARIO)
    assert result.passed, '\n'.join(result.failures())
