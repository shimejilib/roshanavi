"""state_machine: a sample Python (rclpy) node for roshanavi.

What it does
    Subscribes  cmd    std_msgs/msg/String: "start", "stop", "fault" or "reset"
    Publishes   state  std_msgs/msg/String: "IDLE", "RUNNING" or "ERROR"

Transitions (anything else is ignored with a warning, the state stays the same):

    IDLE    --start--> RUNNING
    RUNNING --stop---> IDLE
    IDLE / RUNNING --fault--> ERROR
    ERROR   --reset--> IDLE

The state is published on every change and once a second (``publish_period_sec``),
with "transient local" durability: a subscriber that starts later still gets the
current state right away. That makes it a good target for scenario checks such as
"after sending fault, /state becomes ERROR within 1 s".

Parameters
    initial_state (string, default "IDLE")       state at start-up
    publish_period_sec (double, default 1.0)     repeat the state this often (0 = only on change)

Run:  ros2 run roshanavi_examples state_machine
      ros2 topic pub --once /cmd std_msgs/msg/String "{data: start}"
"""

import sys
from typing import Dict, Optional, Tuple

STATES = ('IDLE', 'RUNNING', 'ERROR')
# (current state, command) -> next state. Commands are case-insensitive.
TRANSITIONS: Dict[Tuple[str, str], str] = {
    ('IDLE', 'start'): 'RUNNING',
    ('RUNNING', 'stop'): 'IDLE',
    ('IDLE', 'fault'): 'ERROR',
    ('RUNNING', 'fault'): 'ERROR',
    ('ERROR', 'reset'): 'IDLE',
}


class StateMachine:
    """The transition rules (pure logic, no ROS; unit-tested)."""

    def __init__(self, initial: str = 'IDLE'):
        if initial not in STATES:
            raise ValueError(f'initial_state must be one of {STATES}, got {initial!r}')
        self.state = initial

    def handle(self, command: str) -> Tuple[bool, str]:
        """Apply ``command``. Returns (changed, message for the log)."""
        cmd = command.strip().lower()
        nxt = TRANSITIONS.get((self.state, cmd))
        if nxt is None:
            return False, f'ignored "{command}" in state {self.state}'
        previous, self.state = self.state, nxt
        return True, f'{previous} --{cmd}--> {nxt}'


def main(args: Optional[list] = None) -> int:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    class StateMachineNode(Node):
        def __init__(self) -> None:
            super().__init__('state_machine')
            initial = self.declare_parameter('initial_state', 'IDLE').value
            period = float(self.declare_parameter('publish_period_sec', 1.0).value)
            self.machine = StateMachine(str(initial))
            latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                 durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.pub = self.create_publisher(String, 'state', latched)
            self.create_subscription(String, 'cmd', self.on_cmd, 10)
            if period > 0:
                self.create_timer(period, self.publish_state)
            self.publish_state()
            self.get_logger().info(f'state_machine ready in state {self.machine.state}')

        def on_cmd(self, msg: String) -> None:
            changed, text = self.machine.handle(msg.data)
            if changed:
                self.get_logger().info(text)
                self.publish_state()
            else:
                self.get_logger().warning(text)

        def publish_state(self) -> None:
            self.pub.publish(String(data=self.machine.state))

    rclpy.init(args=args)
    try:
        node = StateMachineNode()
    except ValueError as exc:
        print(f'state_machine: {exc}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0
