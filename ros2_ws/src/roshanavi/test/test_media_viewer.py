"""Viewers: image throttling / downscale, audio forwarding, subscription lifetime."""

import json
import time

import numpy as np
from sensor_msgs.msg import Image
from std_msgs.msg import Int16MultiArray

from conftest import wait_for
from roshanavi.media.adapters.base import AudioChunk, ImageFrame
from roshanavi.media.imaging import encode_jpeg, jpeg_size
from roshanavi.media.viewer import downmix


def big_image(i):
    msg = Image(width=1280, height=720, encoding='rgb8', step=1280 * 3)
    msg.data = bytes([i % 256]) * (1280 * 720 * 3)
    return msg


def test_encode_jpeg_downscales_to_640():
    frame = ImageFrame(1280, 720, 'rgb8', bytes(1280 * 720 * 3))
    out = encode_jpeg(frame, 640)
    assert (out.width, out.height, out.fmt) == (640, 360, 'jpeg')
    assert jpeg_size(out.data) == (640, 360)
    small = ImageFrame(320, 240, 'jpeg', out.data)
    assert encode_jpeg(small, 640) is small


def test_downmix_stereo():
    pcm = np.array([100, 300, -100, -300], dtype='<i2').tobytes()
    mono = np.frombuffer(downmix(AudioChunk(pcm, 16000, 2)), dtype='<i2')
    assert list(mono) == [200, -200]


def test_image_viewer_throttles_and_downscales(client, lab, helper):
    helper.periodic_publisher(Image, '/tl_view_img', 30.0, big_image)
    wait_for(lambda: '/tl_view_img' in dict(lab.runtime.topic_names_and_types()), timeout=10)
    frames = []
    with client.websocket_connect('ws://localhost/ws/view/tl_view_img') as ws:
        ready = ws.receive_json()
        assert ready == {'event': 'ready', 'topic': '/tl_view_img',
                         'type': 'sensor_msgs/msg/Image', 'kind': 'image'}
        wait_for(lambda: lab.runtime.publishers_info('/tl_view_img'), timeout=5)
        start = time.monotonic()
        while len(frames) < 8:
            meta = ws.receive_json()
            data = ws.receive_bytes()
            frames.append((time.monotonic(), meta, data))
        elapsed = time.monotonic() - start
    assert elapsed >= 0.6  # <= 10 fps although the topic runs at 30 Hz
    assert all(m['width'] == 640 and m['height'] == 360 for _, m, _ in frames)
    assert all(jpeg_size(d) == (640, 360) for _, _, d in frames)
    # the viewer subscription is gone once the socket closes
    wait_for(lambda: not any(i.node_name.startswith('roshanavi')
                             for i in lab.runtime.subscriptions_info('/tl_view_img')),
             timeout=5)


def test_audio_viewer_forwards_pcm(client, lab, helper):
    samples = np.arange(256, dtype=np.int16)
    helper.periodic_publisher(Int16MultiArray, '/tl_view_mic', 20.0,
                              lambda i: Int16MultiArray(data=samples.tolist()))
    wait_for(lambda: '/tl_view_mic' in dict(lab.runtime.topic_names_and_types()), timeout=10)
    with client.websocket_connect('ws://localhost/ws/view/tl_view_mic?sample_rate=8000') as ws:
        assert ws.receive_json()['kind'] == 'audio'
        meta = ws.receive_json()
        data = ws.receive_bytes()
    assert meta['event'] == 'audio' and meta['sample_rate'] == 8000
    assert meta['samples'] == len(data) // 2 and meta['samples'] % 256 == 0
    assert list(np.frombuffer(data, dtype='<i2')[:4]) == [0, 1, 2, 3]


def test_viewer_rejects_unsupported_types(client, helper, lab):
    from std_msgs.msg import String
    helper.periodic_publisher(String, '/tl_view_str', 5.0, lambda i: String(data='x'))
    wait_for(lambda: '/tl_view_str' in dict(lab.runtime.topic_names_and_types()), timeout=10)
    with client.websocket_connect('ws://localhost/ws/view/tl_view_str') as ws:
        body = json.loads(ws.receive_text())
    assert body['error']['code'] == 'media_type_unsupported'
