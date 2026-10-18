"""The rest of a taken-over launch file (docs/design/integration.md, per-node mode).

Started by roshanavi as one launch target: it includes ``roshanavi_launch_file`` of
``roshanavi_package`` (found the same way ``ros2 launch`` finds it) with every other
launch argument, and skips the Nodes listed in ``roshanavi_skip`` because roshanavi
runs those as targets of their own. Everything else -- ExecuteProcess, composable
containers, TimerAction, event handlers, Nodes roshanavi could not decompose --
runs exactly as in ``ros2 launch``.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, \
    OpaqueFunction
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, LifecycleNode, Node

from roshanavi.launch_import.extract import node_identity
from roshanavi.launch_import.skip import ARG_LAUNCH_FILE, ARG_PACKAGE, ARG_SKIP, decode, \
    node_key

MAX_LAUNCH_DEPTH = 2  # same search depth as roshanavi's workspace discovery


def _find(package: str, launch_file: str) -> str:
    base = os.path.join(get_package_share_directory(package), 'launch')
    for current, dirs, files in os.walk(base):
        if os.path.relpath(current, base).count(os.sep) >= MAX_LAUNCH_DEPTH:
            dirs[:] = []
        if launch_file in files:
            return os.path.join(current, launch_file)
    raise RuntimeError(f'{package} has no launch file {launch_file!r}')


def _install_skip(skip):
    """Wrap Node.execute (and LifecycleNode.execute) so the listed Nodes are not started."""
    def wrap(cls):
        original = cls.execute

        def execute(self, context):
            try:
                key = node_key(node_identity(self, context))
            except Exception:  # cannot tell: start it, as ros2 launch would
                key = None
            if key in skip and not isinstance(self, ComposableNodeContainer):
                return [LogInfo(msg=f'roshanavi runs {key[0]}/{key[1]} '
                                    f'({key[2] or "unnamed"}) as its own target')]
            return original(self, context)
        cls.execute = execute

    wrap(Node)
    wrap(LifecycleNode)


def _setup(context):
    package = LaunchConfiguration(ARG_PACKAGE).perform(context)
    launch_file = LaunchConfiguration(ARG_LAUNCH_FILE).perform(context)
    _install_skip(decode(LaunchConfiguration(ARG_SKIP).perform(context)))
    return [IncludeLaunchDescription(AnyLaunchDescriptionSource(_find(package, launch_file)))]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(ARG_PACKAGE, description='package of the taken-over launch file'),
        DeclareLaunchArgument(ARG_LAUNCH_FILE, description='the taken-over launch file'),
        DeclareLaunchArgument(ARG_SKIP, default_value='',
                              description='Nodes roshanavi runs separately (package:exe:name:ns)'),
        OpaqueFunction(function=_setup),
    ])
