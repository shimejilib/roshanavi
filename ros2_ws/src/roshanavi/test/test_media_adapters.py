"""Adapters: field mapping, encodings, AudioInfo / CameraInfo companions, registry, plugins."""

import numpy as np
import pytest

from media_fixtures import jpeg_bytes
from roshanavi.media import adapters
from roshanavi.media.adapters.audio import build_audio_info
from roshanavi.media.adapters.base import AudioChunk, ImageFrame, MediaAdapter, MediaSettings
from roshanavi.media.camera_info import default_calibration, parse_calibration
from roshanavi.media.errors import MediaError
from roshanavi.media.options import detect_type
from roshanavi.msgutil import resolve_type

STAMP = resolve_type('builtin_interfaces/msg/Time')(sec=12, nanosec=34)
RGB = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 10, 20, 30])  # 2x2: red green blue gray-ish


def frame(fmt='rgb8'):
    return ImageFrame(2, 2, 'rgb8', RGB) if fmt == 'rgb8' else None


@pytest.mark.parametrize('encoding,expected', [
    ('rgb8', RGB),
    ('bgr8', bytes([0, 0, 255, 0, 255, 0, 255, 0, 0, 30, 20, 10])),
    ('mono8', bytes([76, 150, 29, 18])),
])
def test_image_encodings(encoding, expected):
    adapter = adapters.get('sensor_msgs/msg/Image')
    msg = adapter.to_message(frame(), STAMP, MediaSettings(encoding=encoding, frame_id='cam'))
    assert (msg.width, msg.height, msg.encoding) == (2, 2, encoding)
    assert msg.step == 2 * (1 if encoding == 'mono8' else 3)
    assert bytes(msg.data) == expected
    assert msg.header.frame_id == 'cam' and msg.header.stamp.sec == 12
    back = adapter.from_message(msg, MediaSettings())
    assert back.fmt == encoding and back.data == expected


def test_image_from_jpeg_needs_decode():
    adapter = adapters.get('sensor_msgs/msg/Image')
    jpg = ImageFrame(64, 48, 'jpeg', jpeg_bytes())
    msg = adapter.to_message(jpg, STAMP, MediaSettings(encoding='bgr8'))
    assert (msg.width, msg.height, len(msg.data)) == (64, 48, 64 * 48 * 3)
    assert msg.data[0] > 200 and msg.data[2] < 50  # blue in BGR order


def test_compressed_image_and_camera_info_companion():
    adapter = adapters.get('sensor_msgs/msg/CompressedImage')
    data = jpeg_bytes()
    msg = adapter.to_message(ImageFrame(64, 48, 'jpeg', data), STAMP, MediaSettings())
    assert msg.format == 'jpeg' and bytes(msg.data) == data
    assert adapter.from_message(msg, MediaSettings()).width == 64
    with pytest.raises(MediaError):
        adapter.to_message(frame(), STAMP, MediaSettings())
    [comp] = adapter.companions('/cam/image_raw/compressed', MediaSettings(frame_id='cam'))
    assert comp.topic == '/cam/image_raw/camera_info' and comp.every_frame
    info = comp.build(STAMP, ImageFrame(640, 480, 'jpeg', data))
    assert (info.width, info.height, info.header.frame_id) == (640, 480, 'cam')
    assert info.k[2] == 320.0 and info.k[5] == 240.0 and info.p[10] == 1.0
    assert adapter.companions('/x', MediaSettings(camera_info=False)) == []


def test_camera_info_from_calibration_yaml_is_scaled():
    calib = parse_calibration('''
image_width: 640
image_height: 480
camera_name: cam
camera_matrix: {rows: 3, cols: 3, data: [500, 0, 320, 0, 500, 240, 0, 0, 1]}
distortion_model: plumb_bob
distortion_coefficients: {rows: 1, cols: 5, data: [0.1, -0.2, 0, 0, 0]}
rectification_matrix: {rows: 3, cols: 3, data: [1, 0, 0, 0, 1, 0, 0, 0, 1]}
projection_matrix: {rows: 3, cols: 4, data: [500, 0, 320, 0, 0, 500, 240, 0, 0, 0, 1, 0]}
''')
    adapter = adapters.get('sensor_msgs/msg/Image')
    [comp] = adapter.companions('/image', MediaSettings(calibration=calib,
                                                        camera_info_topic='/my_info'))
    assert comp.topic == '/my_info'
    info = comp.build(STAMP, ImageFrame(320, 240, 'rgb8', b''))
    assert list(info.k[:3]) == [250.0, 0.0, 160.0] and list(info.d[:2]) == [0.1, -0.2]
    with pytest.raises(MediaError):
        parse_calibration('image_width: 1')
    assert default_calibration(100, 50).k[2] == 50.0


def chunk(samples, channels=1, rate=16000):
    pcm = np.array(samples, dtype='<i2').tobytes()
    return AudioChunk(pcm, rate, channels)


def test_audio_common_types_and_audio_info_naming():
    adapter = adapters.get('audio_common_msgs/msg/AudioData')
    c = chunk([1, -2, 300, -32768])
    msg = adapter.to_message(c, STAMP, MediaSettings())
    assert bytes(msg.data) == c.data
    settings = MediaSettings(sample_rate=48000, channels=2)
    [comp] = adapter.companions('/audio/audio', settings)
    # audio_capture (audio_common 0.4.x, Jazzy) publishes audio + audio_info side by side
    assert comp.topic == '/audio/audio_info' and comp.latched and not comp.every_frame
    info = comp.build(STAMP, c)
    assert (info.sample_rate, info.channels, info.sample_format, info.coding_format,
            info.bitrate) == (48000, 2, 'S16LE', 'wave', 48000 * 2 * 16)
    custom = adapter.companions('/mic', MediaSettings(audio_info_topic='/mic_info'))
    assert custom[0].topic == '/mic_info'
    stamped = adapters.get('audio_common_msgs/msg/AudioDataStamped')
    smsg = stamped.to_message(c, STAMP, MediaSettings(frame_id='mic'))
    assert bytes(smsg.audio.data) == c.data and smsg.header.frame_id == 'mic'
    assert stamped.from_message(smsg, MediaSettings()).data == c.data
    assert build_audio_info(resolve_type('audio_common_msgs/msg/AudioInfo'), 16000, 1).bitrate \
        == 256000


def test_multiarray_audio_types_round_trip():
    c = chunk([1, -2, 3, -4, 32767, -32768], channels=2)
    int16 = adapters.get('std_msgs/msg/Int16MultiArray')
    msg = int16.to_message(c, STAMP, MediaSettings())
    assert list(msg.data) == [1, -2, 3, -4, 32767, -32768]
    assert [(d.label, d.size) for d in msg.layout.dim] == [('samples', 3), ('channels', 2)]
    assert int16.from_message(msg, MediaSettings()).channels == 2
    uint8 = adapters.get('std_msgs/msg/UInt8MultiArray')
    assert bytes(uint8.to_message(c, STAMP, MediaSettings()).data) == c.data
    f32 = adapters.get('std_msgs/msg/Float32MultiArray')
    fmsg = f32.to_message(c, STAMP, MediaSettings())
    assert fmsg.data[0] == pytest.approx(1 / 32768) and fmsg.data[5] == -1.0
    assert f32.from_message(fmsg, MediaSettings()).data == c.data


def test_missing_message_package_disables_adapter():
    class Missing(MediaAdapter):
        type_name = 'not_installed_msgs/msg/Audio'
    assert adapters.register(Missing()) is False  # e.g. audio_common_msgs not installed
    with pytest.raises(MediaError):
        adapters.get('not_installed_msgs/msg/Audio')


def test_unsupported_type_explains_bag_mode():
    with pytest.raises(MediaError) as err:
        adapters.get('geometry_msgs/msg/Twist')
    assert err.value.code == 'media_type_unsupported' and 'bag' in str(err.value)


def test_type_detection_prefers_subscribers():
    assert detect_type({'subscribers': ['a/msg/B'], 'publishers': ['c/msg/D']}) == 'a/msg/B'
    assert detect_type({'subscribers': [], 'publishers': ['c/msg/D']}) == 'c/msg/D'
    assert detect_type({'subscribers': [], 'publishers': []}) is None
    with pytest.raises(MediaError):
        detect_type({'subscribers': ['a/msg/B', 'c/msg/D'], 'publishers': []})


class PointAdapter(MediaAdapter):
    """A plugin adapter defined in the test (geometry_msgs/Point from audio level)."""

    type_name = 'geometry_msgs/msg/Point'
    kind = 'audio'

    def to_message(self, chunk, stamp, settings):
        msg = resolve_type(self.type_name)()
        msg.x = float(len(chunk.data))
        return msg


class FakeEntryPoint:
    name = 'point'

    def __init__(self, obj):
        self._obj = obj

    def load(self):
        return self._obj


def test_plugin_entry_point_registers_adapter():
    def broken():
        raise RuntimeError('boom')
    added = adapters.load_plugins([FakeEntryPoint(PointAdapter), FakeEntryPoint(broken),
                                   FakeEntryPoint(lambda: [MediaAdapter()])])
    assert added == ['geometry_msgs/msg/Point']
    adapter = adapters.get('geometry_msgs/msg/Point')
    assert adapter.to_message(chunk([1, 2]), STAMP, MediaSettings()).x == 4.0
    assert any(t['type'] == 'geometry_msgs/msg/Point' for t in adapters.supported())
    with adapters._lock:
        del adapters._registry['geometry_msgs/msg/Point']
