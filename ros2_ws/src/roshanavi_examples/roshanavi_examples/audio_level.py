"""audio_level: a sample Python (rclpy) node for roshanavi.

What it does
    Subscribes  audio      raw PCM audio, signed 16 bit, either
                           - audio_common_msgs/msg/AudioDataStamped (``input_type: stamped``,
                             bytes in ``audio.data``, little endian), or
                           - std_msgs/msg/Int16MultiArray (``input_type: int16``, one sample
                             per element)
    Publishes   level_db   std_msgs/msg/Float32: loudness of each chunk in dB full scale
                           (0 dB = the loudest possible signal, -120 dB = digital silence)
                silence    std_msgs/msg/Bool: true while it is quiet

Parameters
    input_type (string, default "stamped")   "stamped" or "int16" (read at start-up)
    silence_below_db (double, default -45)   become silent when the level drops below this
    sound_above_db (double, default -35)     become "not silent" when the level rises above this

Why two thresholds (hysteresis)? With a single threshold, a level hovering around
it would flip silence true/false on every chunk. With a gap between the two, the
flag only changes on a clear change of loudness.

Why Python? roshanavi's tracing mode can only count received messages for rclpy
nodes (no processed count or processing time); compare with the C++ image samples.

Run:  ros2 run roshanavi_examples audio_level --ros-args -r audio:=/mic/audio
"""

import array
import math
import sys
from typing import Iterable, Optional, Sequence

INT16_FULL_SCALE = 32768.0
FLOOR_DB = -120.0  # what silence (all zeros) is reported as; log10(0) is -infinity
INPUT_TYPES = ('stamped', 'int16')


def level_db(samples: Sequence[int]) -> float:
    """Root-mean-square level of 16-bit samples in dBFS, never below FLOOR_DB."""
    if len(samples) == 0:
        return FLOOR_DB
    mean_square = sum(float(s) * float(s) for s in samples) / len(samples)
    rms = math.sqrt(mean_square) / INT16_FULL_SCALE
    if rms <= 0.0:
        return FLOOR_DB
    return max(FLOOR_DB, 20.0 * math.log10(rms))


def samples_from_bytes(data: Iterable[int]) -> array.array:
    """Little-endian signed 16-bit PCM bytes -> samples (an odd trailing byte is ignored)."""
    raw = bytes(data)
    samples = array.array('h')
    samples.frombytes(raw[:len(raw) - len(raw) % 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    return samples


class SilenceDetector:
    """Silence flag with hysteresis (pure logic, no ROS; unit-tested)."""

    def __init__(self, silence_below_db: float, sound_above_db: float):
        if silence_below_db > sound_above_db:
            raise ValueError('silence_below_db must not be above sound_above_db')
        self.silence_below_db = silence_below_db
        self.sound_above_db = sound_above_db
        self.silent: Optional[bool] = None  # unknown until the first chunk

    def update(self, db: float) -> bool:
        if self.silent is None:
            # First chunk: decide by the middle of the two thresholds.
            self.silent = db < (self.silence_below_db + self.sound_above_db) / 2.0
        elif self.silent and db > self.sound_above_db:
            self.silent = False
        elif not self.silent and db < self.silence_below_db:
            self.silent = True
        return self.silent


def main(args: Optional[list] = None) -> int:
    # ROS imports live here so the pure functions above can be tested without a node.
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import Bool, Float32, Int16MultiArray

    class AudioLevel(Node):
        def __init__(self) -> None:
            super().__init__('audio_level')
            input_type = self.declare_parameter('input_type', 'stamped').value
            below = self.declare_parameter('silence_below_db', -45.0).value
            above = self.declare_parameter('sound_above_db', -35.0).value
            if input_type not in INPUT_TYPES:
                raise ValueError(f'input_type must be one of {INPUT_TYPES}, got {input_type!r}')
            self.detector = SilenceDetector(float(below), float(above))
            self.level_pub = self.create_publisher(Float32, 'level_db', 10)
            self.silence_pub = self.create_publisher(Bool, 'silence', 10)
            if input_type == 'stamped':
                # Optional dependency: only needed for this input type.
                from audio_common_msgs.msg import AudioDataStamped
                self.create_subscription(AudioDataStamped, 'audio', self.on_stamped,
                                         qos_profile_sensor_data)
            else:
                self.create_subscription(Int16MultiArray, 'audio', self.on_int16,
                                         qos_profile_sensor_data)
            self.get_logger().info(f'audio_level ready (input_type={input_type})')

        def on_stamped(self, msg) -> None:
            self.publish(samples_from_bytes(msg.audio.data))

        def on_int16(self, msg) -> None:
            self.publish(msg.data)

        def publish(self, samples: Sequence[int]) -> None:
            db = level_db(samples)
            self.level_pub.publish(Float32(data=float(db)))
            self.silence_pub.publish(Bool(data=self.detector.update(db)))

    rclpy.init(args=args)
    try:
        node = AudioLevel()
    except (ValueError, ImportError) as exc:
        print(f'audio_level: {exc}', file=sys.stderr)
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
