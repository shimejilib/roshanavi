"""Browser capture WebSocket: fake PCM / JPEG frames -> published messages."""

import threading

import numpy as np
import pytest
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from starlette.websockets import WebSocketDisconnect
from std_msgs.msg import Int16MultiArray

from conftest import wait_for
from media_fixtures import jpeg_bytes
from roshanavi.media.capture import ByteBudget, CaptureJob, MinInterval, Rechunker


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_rechunker_and_rate_limits():
    r = Rechunker(4)
    assert r.push(b'abc') == [] and r.push(b'defghij') == [b'abcd', b'efgh']
    assert r.push(b'kl') == [b'ijkl']  # the remainder was kept
    clock = Clock()
    gate = MinInterval(10, clock)  # >= 80 ms apart (20 % slack)
    assert gate.allow() and not gate.allow()
    clock.now += 0.085
    assert gate.allow()
    budget = ByteBudget(1000, clock)
    assert budget.allow(1400) and not budget.allow(200)
    clock.now += 1.0
    assert budget.allow(1000)


def pcm(samples):
    t = np.arange(samples)
    return (np.sin(2 * np.pi * 440 * t / 16000) * 8000).astype('<i2').tobytes()


def test_mic_capture_publishes_chunks(client, lab, helper):
    received = helper.collector(Int16MultiArray, '/tl_cap_mic', 50)
    wait_for(lambda: lab.runtime.subscriptions_info('/tl_cap_mic'), timeout=10)
    with client.websocket_connect('ws://localhost/ws/capture') as ws:
        ws.send_json({'kind': 'audio', 'topic': '/tl_cap_mic', 'sample_rate': 16000,
                      'chunk_samples': 512})
        ready = ws.receive_json()
        assert ready['event'] == 'ready' and ready['type'] == 'std_msgs/msg/Int16MultiArray'
        jobs = client.get('/api/inject').json()['jobs']
        assert any(j['mode'] == 'capture' and j['topic'] == '/tl_cap_mic' for j in jobs)
        # one capture per topic
        with client.websocket_connect('ws://localhost/ws/capture') as second:
            second.send_json({'kind': 'audio', 'topic': '/tl_cap_mic'})
            assert second.receive_json()['error']['code'] == 'capture_busy'
        for _ in range(4):
            ws.send_bytes(pcm(320))  # 20 ms browser chunks -> 2.5 chunks of 512
        wait_for(lambda: len(received) == 2, timeout=5)
    assert len(received[0].data) == 512
    wait_for(lambda: not any(j['state'] == 'running' and j['mode'] == 'capture'
                             for j in client.get('/api/inject').json()['jobs']), timeout=5)


def test_camera_capture_compressed_and_image_with_info(client, lab, helper):
    compressed = helper.collector(CompressedImage, '/tl_cap/image/compressed')
    raw = helper.collector(Image, '/tl_cap/image_raw')
    infos = helper.collector(CameraInfo, '/tl_cap/camera_info')
    frame = jpeg_bytes('64x48')
    for topic in ('/tl_cap/image/compressed', '/tl_cap/image_raw', '/tl_cap/camera_info'):
        wait_for(lambda topic=topic: lab.runtime.subscriptions_info(topic), timeout=10)
    with client.websocket_connect('ws://localhost/ws/capture') as ws:
        ws.send_json({'kind': 'camera', 'topic': '/tl_cap/image/compressed',
                      'type': 'sensor_msgs/msg/CompressedImage', 'fps': 30, 'camera_info': False})
        assert ws.receive_json()['event'] == 'ready'
        ws.send_bytes(frame)
        wait_for(lambda: compressed, timeout=5)
    with client.websocket_connect('ws://localhost/ws/capture') as ws:
        ws.send_json({'kind': 'camera', 'topic': '/tl_cap/image_raw',
                      'type': 'sensor_msgs/msg/Image', 'encoding': 'rgb8', 'frame_id': 'web'})
        ready = ws.receive_json()
        assert ready['companions'] == ['/tl_cap/camera_info']
        ws.send_bytes(frame)
        ws.send_bytes(frame)  # same instant: dropped by the fps cap
        wait_for(lambda: raw and infos, timeout=5)
    assert bytes(compressed[0].data) == frame and compressed[0].format == 'jpeg'
    assert (raw[0].width, raw[0].height, raw[0].encoding) == (64, 48, 'rgb8')
    assert infos[0].header.frame_id == 'web' and len(raw) == 1


@pytest.mark.parametrize('start,frame,code', [
    ({'kind': 'audio', 'topic': '/tl_bad', 'type': 'std_msgs/msg/Int16MultiArray'},
     b'\x00\x01\x02', 'invalid_frame'),
    ({'kind': 'camera', 'topic': '/tl_bad2', 'type': 'sensor_msgs/msg/CompressedImage'},
     b'not a jpeg', 'invalid_media'),
    ({'kind': 'camera', 'topic': '/tl_bad3', 'type': 'std_msgs/msg/Int16MultiArray'},
     None, 'media_kind_mismatch'),
    ({'kind': 'audio', 'topic': '/tl_bad4', 'type': 'geometry_msgs/msg/Twist'},
     None, 'media_type_unsupported'),
    ({'kind': 'audio', 'topic': 'bad topic'}, None, 'invalid_request'),
])
def test_capture_errors(client, start, frame, code):
    with client.websocket_connect('ws://localhost/ws/capture') as ws:
        ws.send_json(start)
        if frame is not None:
            assert ws.receive_json()['event'] == 'ready'
            ws.send_bytes(frame)
        assert ws.receive_json()['error']['code'] == code


def test_capture_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect('ws://localhost/ws/capture',
                                      headers={'origin': 'http://evil.example'}):
            pass
    assert err.value.code == 1008


class OrderedPublisher:
    """Records whether it was drained (acked) before it was destroyed."""

    def __init__(self, events, name):
        self._events, self._name = events, name

    def wait_for_all_acked(self, _timeout):
        self._events.append(('acked', self._name))
        return True


def test_teardown_waits_for_acks_before_destroying_the_publishers():
    """#6: frames still in flight to reliable readers must not die with the publisher."""
    events = []

    class Runtime:
        def destroy_publisher(self, pub):
            events.append(('destroyed', pub._name))

    job = object.__new__(CaptureJob)
    job.id = 'unit'
    job.lock = threading.Lock()
    job._runtime = Runtime()
    job._publisher = OrderedPublisher(events, 'main')
    job._companions = [(None, OrderedPublisher(events, 'info'))]
    job._teardown()
    assert events == [('acked', 'main'), ('acked', 'info'),
                      ('destroyed', 'main'), ('destroyed', 'info')]


@pytest.mark.parametrize('how', ['close', 'stop'])
def test_frames_sent_right_before_the_socket_closes_are_all_published(client, lab, helper, how):
    """#6: the browser closes right after its last frame; none of them may be lost."""
    topic = f'/tl_cap_last_{how}'
    received = helper.collector(Int16MultiArray, topic, 100)
    wait_for(lambda: lab.runtime.subscriptions_info(topic), timeout=10)
    frames = 8  # fewer than the publisher history (10): a burst deeper than that is a QoS limit
    with client.websocket_connect('ws://localhost/ws/capture') as ws:
        ws.send_json({'kind': 'audio', 'topic': topic, 'sample_rate': 16000,
                      'chunk_samples': 320, 'reliability': 'reliable'})
        assert ws.receive_json()['event'] == 'ready'
        for _ in range(frames):
            ws.send_bytes(pcm(320))
        if how == 'stop':
            ws.send_json({'cmd': 'stop'})
            # the acknowledgement comes after every earlier frame was handled and drained
            assert ws.receive_json()['event'] == 'stopped'
        # leaving the block closes the socket immediately
    wait_for(lambda: len(received) == frames, timeout=5)
    jobs = client.get('/api/inject').json()['jobs']
    assert [j['sent'] for j in jobs if j['topic'] == topic] == [frames]
