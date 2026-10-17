"""Sample nodes (roshanavi_examples): pure logic of the Python nodes, then each node over ROS."""

import math
import subprocess
import time

import pytest
from builtin_interfaces.msg import Time
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, Int16MultiArray, String

from conftest import wait_for
from roshanavi_examples.audio_level import (FLOOR_DB, SilenceDetector, level_db,
                                            samples_from_bytes)
from roshanavi_examples.state_machine import StateMachine
from test_dummy import stop_group


# ---- pure logic --------------------------------------------------------------------------

def sine(amplitude, n=1024, rate=16000, freq=440.0):
    return [int(amplitude * 32767 * math.sin(2 * math.pi * freq * k / rate)) for k in range(n)]


def test_level_db_of_sine_square_and_silence():
    assert level_db([0] * 100) == FLOOR_DB
    assert level_db([]) == FLOOR_DB
    assert level_db([16384] * 100) == pytest.approx(-6.02, abs=0.01)
    # RMS of a sine is amplitude / sqrt(2): -3 dB below its peak.
    assert level_db(sine(0.5)) == pytest.approx(20 * math.log10(0.5 / math.sqrt(2)), abs=0.1)


def test_samples_from_little_endian_bytes():
    assert list(samples_from_bytes(b'\x01\x00\xff\xff\x00\x80')) == [1, -1, -32768]
    assert list(samples_from_bytes(b'\x01\x00\x07')) == [1]  # odd byte ignored


def test_silence_hysteresis():
    det = SilenceDetector(-45, -35)
    assert det.update(-60) is True
    assert det.update(-40) is True     # between thresholds: stays silent
    assert det.update(-30) is False
    assert det.update(-40) is False    # between thresholds: stays loud
    assert det.update(-50) is True
    with pytest.raises(ValueError):
        SilenceDetector(-30, -40)


def test_state_machine_transitions():
    sm = StateMachine()
    assert sm.state == 'IDLE'
    assert sm.handle('start') == (True, 'IDLE --start--> RUNNING')
    assert sm.handle('START ')[0] is False and sm.state == 'RUNNING'  # already running
    assert sm.handle('stop')[0] and sm.state == 'IDLE'
    assert sm.handle('fault')[0] and sm.state == 'ERROR'
    assert sm.handle('start')[0] is False and sm.state == 'ERROR'      # needs reset first
    assert sm.handle('reset')[0] and sm.state == 'IDLE'
    assert sm.handle('dance') == (False, 'ignored "dance" in state IDLE')
    with pytest.raises(ValueError):
        StateMachine('FLYING')


# ---- nodes over ROS ----------------------------------------------------------------------

def run_node(executable, *ros_args):
    return subprocess.Popen(['ros2', 'run', 'roshanavi_examples', executable, '--ros-args',
                             *ros_args], start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


@pytest.fixture
def node_proc():
    procs = []

    def start(executable, *ros_args):
        proc = run_node(executable, *ros_args)
        procs.append(proc)
        return proc
    yield start
    for proc in procs:
        stop_group(proc)


FIXED_STAMP = Time(sec=1234, nanosec=5678)


def squares_image(_i, encoding='rgb8', squares=((10, 10, 20), (60, 40, 30), (120, 80, 12))):
    """160x120 dark image with bright squares (x, y, size)."""
    width, height = 160, 120
    channels = 3 if encoding == 'rgb8' else 1
    data = bytearray(width * height * channels)
    for x0, y0, size in squares:
        for y in range(y0, y0 + size):
            for x in range(x0, x0 + size):
                base = (y * width + x) * channels
                data[base:base + channels] = bytes([240] * channels)
    msg = Image(width=width, height=height, encoding=encoding, step=width * channels,
                data=bytes(data))
    msg.header.stamp = FIXED_STAMP
    msg.header.frame_id = 'camera'
    return msg


@pytest.mark.parametrize('keep_stamp', [True, False])
def test_image_filter_outputs_and_stamp_modes(helper, node_proc, keep_stamp):
    topic = f'/rn_ex_img_{int(keep_stamp)}'
    gray = helper.collector(Image, f'{topic}_gray')
    edges = helper.collector(Image, f'{topic}_edges')
    node_proc('image_filter', '-r', f'__node:=rn_image_filter_{int(keep_stamp)}',
              '-r', f'image:={topic}', '-r', f'image_gray:={topic}_gray',
              '-r', f'image_edges:={topic}_edges', '-p', f'keep_stamp:={str(keep_stamp).lower()}')
    helper.periodic_publisher(Image, topic, 5, squares_image)
    wait_for(lambda: gray and edges, timeout=30)
    g, e = gray[-1], edges[-1]
    assert (g.width, g.height, g.encoding, g.step, len(g.data)) == (160, 120, 'mono8', 160, 19200)
    assert (e.width, e.height, e.encoding) == (160, 120, 'mono8')
    assert g.data[15 * 160 + 15] == 240 and g.data[0] == 0       # inside a square / background
    assert e.data[10 * 160 + 15] > 200 and e.data[15 * 160 + 15] == 0  # edge / flat interior
    assert g.header.frame_id == 'camera'
    if keep_stamp:
        assert (g.header.stamp.sec, g.header.stamp.nanosec) == (1234, 5678)
    else:
        assert abs(g.header.stamp.sec - time.time()) < 60


def test_image_filter_process_delay_slows_it_down(helper, node_proc):
    stamps = []
    helper.node.create_subscription(Image, '/rn_ex_slow_gray',
                                    lambda m: stamps.append(time.monotonic()), 10)
    node_proc('image_filter', '-r', '__node:=rn_image_filter_slow', '-r', 'image:=/rn_ex_slow',
              '-r', 'image_gray:=/rn_ex_slow_gray', '-p', 'process_delay_ms:=250')
    helper.periodic_publisher(Image, '/rn_ex_slow', 20, squares_image)
    wait_for(lambda: len(stamps) >= 6, timeout=40)
    gaps = [b - a for a, b in zip(stamps[1:], stamps[2:])]
    assert sorted(gaps)[len(gaps) // 2] >= 0.2  # at most ~4 per second although 20 are sent


def test_blob_detector_counts_and_boxes(helper, node_proc):
    from vision_msgs.msg import Detection2DArray
    out = helper.collector(Detection2DArray, '/rn_ex_det')
    node_proc('blob_detector', '-r', '__node:=rn_blob_detector', '-r', 'image:=/rn_ex_blobs',
              '-r', 'detections:=/rn_ex_det', '-p', 'min_area:=200')
    helper.periodic_publisher(Image, '/rn_ex_blobs', 5,
                              lambda i: squares_image(i, encoding='mono8'))
    wait_for(lambda: out, timeout=30)
    msg = out[-1]
    assert len(msg.detections) == 2  # 30x30 and 20x20; the 12x12 square (144 px) is too small
    biggest = msg.detections[0]
    assert (biggest.bbox.size_x, biggest.bbox.size_y) == (30.0, 30.0)
    assert (biggest.bbox.center.position.x, biggest.bbox.center.position.y) == (75.0, 55.0)
    assert biggest.results[0].hypothesis.class_id == 'blob'
    assert biggest.results[0].hypothesis.score == pytest.approx(240 / 255)
    assert (msg.header.stamp.sec, msg.header.stamp.nanosec) == (1234, 5678)


def int16_chunk(samples):
    return Int16MultiArray(data=samples)


def test_audio_level_int16_sound_then_silence(helper, node_proc):
    levels = helper.collector(Float32, '/rn_ex_audio/level_db')
    silence = helper.collector(Bool, '/rn_ex_audio/silence')
    node_proc('audio_level', '-r', '__node:=rn_audio_level', '-r', 'audio:=/rn_ex_audio',
              '-r', 'level_db:=/rn_ex_audio/level_db', '-r', 'silence:=/rn_ex_audio/silence',
              '-p', 'input_type:=int16')
    loud = sine(0.5)
    helper.periodic_publisher(Int16MultiArray, '/rn_ex_audio', 10,
                              lambda i: int16_chunk(loud if (i // 10) % 2 == 0 else [0] * 1024))
    wait_for(lambda: any(s.data for s in silence) and any(not s.data for s in silence),
             timeout=40)
    values = [m.data for m in levels]
    assert any(abs(v - (-9.03)) < 0.2 for v in values)
    assert FLOOR_DB in values


def test_audio_level_stamped_input(helper, node_proc):
    from audio_common_msgs.msg import AudioDataStamped
    levels = helper.collector(Float32, '/rn_ex_st/level_db')
    node_proc('audio_level', '-r', '__node:=rn_audio_level_st', '-r', 'audio:=/rn_ex_st',
              '-r', 'level_db:=/rn_ex_st/level_db', '-r', 'silence:=/rn_ex_st/silence')
    pcm = b''.join(int(16384).to_bytes(2, 'little', signed=True) for _ in range(512))

    def chunk(_i):
        msg = AudioDataStamped()
        msg.audio.data = pcm
        return msg
    helper.periodic_publisher(AudioDataStamped, '/rn_ex_st', 10, chunk)
    wait_for(lambda: levels, timeout=30)
    assert levels[-1].data == pytest.approx(-6.02, abs=0.01)


def test_state_machine_node(helper, node_proc):
    states = helper.collector(String, '/rn_ex_state')
    node_proc('state_machine', '-r', '__node:=rn_state_machine', '-r', 'cmd:=/rn_ex_cmd',
              '-r', 'state:=/rn_ex_state', '-p', 'publish_period_sec:=0.2')
    pub = helper.node.create_publisher(String, '/rn_ex_cmd', 10)
    wait_for(lambda: states and states[-1].data == 'IDLE', timeout=30)
    wait_for(lambda: pub.get_subscription_count() > 0, timeout=10)
    for command, expected in (('start', 'RUNNING'), ('fault', 'ERROR'), ('start', 'ERROR'),
                              ('reset', 'IDLE')):
        pub.publish(String(data=command))
        wait_for(lambda: states[-1].data == expected, timeout=10)
        time.sleep(0.3)  # let a periodic repeat confirm the state is stable
        assert states[-1].data == expected, command
