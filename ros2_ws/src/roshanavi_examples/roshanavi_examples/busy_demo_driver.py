"""busy_demo_driver: the message source for executor_busy_demo.

Publishes a short String at a steady rate (default 100 Hz) on /busy_demo/in. At that rate the
subscriber is often still busy with the previous message when the next one arrives, which is
exactly the situation in which the MultiThreadedExecutor busy-loop shows up
(see executor_busy_demo.py).

Parameters
    rate_hz (double, default 100.0)   messages per second
    topic   (string, default "/busy_demo/in")

Run:  ros2 run roshanavi_examples busy_demo_driver --ros-args -p rate_hz:=100.0
"""

import sys
from typing import Optional

MAX_RATE_HZ = 2000.0


def main(args: Optional[list] = None) -> int:
    import rclpy
    from rcl_interfaces.msg import ParameterDescriptor
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    rclpy.init(args=args)
    node = Node('busy_demo_driver')
    rate = float(node.declare_parameter(
        'rate_hz', 100.0, ParameterDescriptor(dynamic_typing=True)).value)
    topic = str(node.declare_parameter('topic', '/busy_demo/in').value)
    if not 0.0 < rate <= MAX_RATE_HZ:
        print(f'busy_demo_driver: rate_hz must be in (0, {MAX_RATE_HZ:g}], got {rate}',
              file=sys.stderr)
        node.destroy_node()
        rclpy.try_shutdown()
        return 1
    pub = node.create_publisher(
        String, topic, QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
    counter = {'n': 0}

    def tick() -> None:
        counter['n'] += 1
        pub.publish(String(data=f'sample {counter["n"]}'))

    node.create_timer(1.0 / rate, tick)
    node.get_logger().info(f'busy_demo_driver: publishing {rate:g} Hz on {topic}')
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0
