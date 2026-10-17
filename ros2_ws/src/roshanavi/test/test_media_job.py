"""Media inject jobs on a live Lab: type detection, video/audio delivery, pacing, stop."""

import threading
import time

import psutil
import pytest
from sensor_msgs.msg import CameraInfo, Image
from audio_common_msgs.msg import AudioDataStamped
from std_msgs.msg import Int16MultiArray

import media_fixtures as fx
from conftest import wait_for
from roshanavi.jobs import InjectError, InjectSpec
from roshanavi.launcher.schema import DummySpec
from roshanavi.media import factory as media_factory
from roshanavi.media.adapters.base import AudioChunk
from roshanavi.media.sources import FrameSource


def subscribe_visible(lab, topic):
    wait_for(lambda: lab.runtime.subscriptions_info(topic), timeout=10)


def no_ffmpeg():
    return not [p for p in psutil.Process().children(recursive=True)
                if p.name().startswith('ffmpeg')]


def test_video_to_detected_image_type_with_camera_info(lab, helper, data_dir):
    fx.video(data_dir / 'clip.mp4', seconds=1.0, size='320x240', rate=10)
    images = helper.collector(Image, '/tl_cam/image_raw')
    infos = helper.collector(CameraInfo, '/tl_cam/camera_info')
    subscribe_visible(lab, '/tl_cam/image_raw')
    job = lab.injector.start(InjectSpec(mode='media', topic='/tl_cam/image_raw',
                                        source='clip.mp4',
                                        media={'encoding': 'bgr8', 'width': 160,
                                               'frame_id': 'cam'}))
    assert job['type'] == 'sensor_msgs/msg/Image'  # detected from the subscriber
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=15)
    wait_for(lambda: len(images) == 10 and len(infos) == 10, timeout=5)
    first = images[0]
    assert (first.width, first.height, first.encoding, first.header.frame_id) == \
        (160, 120, 'bgr8', 'cam')
    assert infos[0].header.stamp == first.header.stamp and infos[0].width == 160
    assert lab.injector.get(job['id'])['send_hz'] is not None
    assert no_ffmpeg()


def thread_cpu_seconds(name):
    """CPU time (user + system) of the live thread called ``name``; None if it is gone."""
    native = {t.name: t.native_id for t in threading.enumerate()}.get(name)
    for t in psutil.Process().threads():
        if t.id == native:
            return t.user_time + t.system_time
    return None


def test_audio_is_paced_in_real_time(lab, helper, data_dir):
    """Send times (header.stamp of AudioDataStamped) are evenly spaced at chunk duration."""
    fx.sine(data_dir / 'tone.wav', seconds=1.0, rate=16000)
    received = helper.collector(AudioDataStamped, '/tl_mic', 50)
    subscribe_visible(lab, '/tl_mic')
    executor_cpu0 = thread_cpu_seconds('roshanavi-executor')
    job = lab.injector.start(InjectSpec(mode='media', topic='/tl_mic', source='tone.wav',
                                        media={'sample_rate': 16000, 'chunk_samples': 1024}))
    assert job['type'] == 'audio_common_msgs/msg/AudioDataStamped'
    wait_for(lambda: lab.injector.get(job['id'])['sent'] >= 10, timeout=15)
    pacer_cpu = thread_cpu_seconds(f'media-{job["id"]}')  # mid-run: the thread is still alive
    executor_cpu = thread_cpu_seconds('roshanavi-executor') - executor_cpu0
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=15)
    wait_for(lambda: len(received) >= 16, timeout=5)
    assert len(received) == 16 and len(received[0].audio.data) == 2048
    stamps = [m.header.stamp.sec + m.header.stamp.nanosec / 1e9 for m in received]
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert stamps[-1] - stamps[0] == pytest.approx(15 * 1024 / 16000, rel=0.05)  # 0.96 s
    assert all(abs(g - 0.064) < 0.02 for g in gaps), gaps
    status = lab.injector.get(job['id'])
    assert status['late_events'] == 0 and status['late_policy'] == 'shift', status
    assert pacer_cpu is not None and pacer_cpu < 0.05, pacer_cpu  # sleeps, no busy-wait
    # regression guard: the executor used to busy-loop (0.3-0.8 s CPU here) while the traffic
    # monitor's subscription and this publisher shared a topic, starving the pacer of the GIL
    assert executor_cpu < 0.15, executor_cpu


class StallingSource(FrameSource):
    """20 audio chunks of 50 ms; decoding item ``stall_at`` takes ``stall_sec``."""

    def __init__(self, stall_at, stall_sec, total=20):
        self.period = 0.05
        self._stall_at, self._stall_sec, self._total = stall_at, stall_sec, total
        self._n = 0
        self._closed = threading.Event()

    def next(self):
        if self._n >= self._total or self._closed.is_set():
            return None
        if self._n == self._stall_at and self._closed.wait(self._stall_sec):
            return None
        self._n += 1
        return AudioChunk(bytes(1600), 16000, 1)

    def close(self):
        self._closed.set()


def run_stalling(monkeypatch, lab, helper, source, **media):
    monkeypatch.setattr(media_factory, 'build_source', lambda *a, **k: source)
    received = helper.collector(AudioDataStamped, '/tl_stall', 50)
    subscribe_visible(lab, '/tl_stall')
    job = lab.injector.start(InjectSpec(mode='media', topic='/tl_stall', source='any.wav',
                                        media={'chunk_samples': 800, **media}))
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=15)
    wait_for(lambda: len(received) >= lab.injector.get(job['id'])['sent'], timeout=5)
    stamps = [m.header.stamp.sec + m.header.stamp.nanosec / 1e9 for m in received]
    return [b - a for a, b in zip(stamps, stamps[1:])], lab.injector.get(job['id'])


@pytest.fixture
def any_wav(data_dir):
    fx.sine(data_dir / 'any.wav', seconds=0.2, rate=16000)


def test_decode_stall_within_the_buffer_does_not_disturb_the_spacing(
        monkeypatch, lab, helper, any_wav):
    """A 150 ms decode hiccup mid-stream is absorbed by the reader-ahead buffer."""
    gaps, status = run_stalling(monkeypatch, lab, helper, StallingSource(8, 0.15))
    assert len(gaps) == 19 and all(abs(g - 0.05) < 0.02 for g in gaps), gaps
    assert status['late_events'] == 0


def test_prebuffer_delays_the_start_until_the_buffer_is_filled(monkeypatch, lab, helper, any_wav):
    """Items 0-3 are ready at once, item 4 takes 400 ms: the first send waits for item 5."""
    started = time.time()
    gaps, status = run_stalling(monkeypatch, lab, helper, StallingSource(4, 0.4),
                                prebuffer_ms=300)
    assert all(abs(g - 0.05) < 0.02 for g in gaps), gaps
    assert status['finished_at'] - started >= 0.4 + 19 * 0.05 - 0.1   # start was held back


@pytest.mark.parametrize('policy', ['shift', 'catch_up', 'drop'])
def test_underrun_follows_the_late_policy(monkeypatch, lab, helper, any_wav, policy):
    """A 700 ms stall beyond the (tiny) buffer makes the pacer wake late."""
    gaps, status = run_stalling(monkeypatch, lab, helper, StallingSource(8, 0.7),
                                prebuffer_ms=50, late_policy=policy)
    assert status['late_policy'] == policy and status['late_events'] >= 1
    assert status['max_lateness_ms'] > 100
    after = gaps[8:]
    if policy == 'shift':
        assert status['late_events'] == 1 and status['sent'] == 20
        assert all(g > 0.03 for g in after), gaps          # spacing kept, no burst
    elif policy == 'catch_up':
        assert status['sent'] == 20 and any(g < 0.01 for g in after), gaps   # burst
    else:
        assert status['late_skipped'] >= 1
        assert status['sent'] == 20 - status['late_skipped']


def test_drop_injection_and_stop_kills_ffmpeg(lab, helper, data_dir):
    fx.sine(data_dir / 'long.flac', seconds=20.0, rate=16000)
    received = helper.collector(Int16MultiArray, '/tl_drop', 100)
    subscribe_visible(lab, '/tl_drop')
    job = lab.injector.start(InjectSpec(mode='media', topic='/tl_drop', source='long.flac',
                                        loop=True,
                                        media={'chunk_samples': 256, 'drop_ratio': 0.5,
                                               'jitter_ms': 3}))
    time.sleep(1.5)
    status = lab.injector.get(job['id'])
    assert status['dropped'] > 5 and status['sent'] > 5
    assert not no_ffmpeg()
    lab.injector.stop(job['id'])
    wait_for(no_ffmpeg, timeout=5)
    assert received


def test_type_errors_are_plain(lab, helper, data_dir):
    fx.sine(data_dir / 'a.wav', seconds=0.2)
    with pytest.raises(InjectError) as err:
        lab.injector.start(InjectSpec(mode='media', topic='/tl_nobody', source='a.wav'))
    assert err.value.code == 'media_type_required' and 'Int16MultiArray' in str(err.value)
    with pytest.raises(InjectError) as err:
        lab.injector.start(InjectSpec(mode='media', topic='/tl_x', source='a.wav',
                                      type='geometry_msgs/msg/Twist'))
    assert err.value.code == 'media_type_unsupported' and 'bag' in str(err.value)
    with pytest.raises(InjectError) as err:
        lab.injector.start(InjectSpec(mode='media', topic='/tl_x', source='a.wav',
                                      type='sensor_msgs/msg/Image'))
    assert err.value.code == 'media_kind_mismatch'


def test_api_media_mode_and_type_info(client, helper, data_dir):
    fx.png(data_dir / 'still.png')
    received = helper.collector(Image, '/tl_still')
    wait_for(lambda: client.get('/api/media/types?topic=/tl_still').json()['detected'],
             timeout=10)
    info = client.get('/api/media/types?topic=/tl_still').json()
    assert info['detected'] == 'sensor_msgs/msg/Image' and info['detected_supported']
    assert {'type': 'sensor_msgs/msg/CompressedImage', 'kind': 'image',
            'data_kind': None} in info['supported']  # no data kind: 専用の型
    assert {'type': 'sensor_msgs/msg/Image', 'kind': 'image',
            'data_kind': 'image'} in info['supported']
    resp = client.post('/api/inject', json={'mode': 'media', 'topic': '/tl_still',
                                            'source': 'still.png', 'rate_hz': 20, 'count': 3,
                                            'media': {'encoding': 'mono8'}})
    assert resp.status_code == 201, resp.text
    wait_for(lambda: len(received) == 3, timeout=10)
    assert received[0].encoding == 'mono8' and received[0].width == 64
    bad = client.post('/api/inject', json={'mode': 'media', 'topic': '/tl_still',
                                           'source': '../x.png', 'media': {'bogus': 1}})
    assert bad.status_code == 422


def test_dummy_spec_accepts_media_mode():
    spec = DummySpec(id='cam', name='dummy_cam', topic='/cam', type='sensor_msgs/msg/Image',
                     mode='media', source='clip.mp4', media={'width': 320})
    assert spec.media.width == 320
    with pytest.raises(ValueError):
        DummySpec(id='cam', name='dummy_cam', topic='/cam', type='x/msg/Y', mode='media')


def test_media_job_becomes_persistent_dummy(client, helper, data_dir):
    fx.png(data_dir / 'persist.png', size='32x16')
    received = helper.collector(Image, '/tl_persist_img')
    job = client.post('/api/inject', json={'mode': 'media', 'topic': '/tl_persist_img',
                                           'type': 'sensor_msgs/msg/Image',
                                           'source': 'persist.png', 'rate_hz': 5,
                                           'media': {'encoding': 'mono8'}}).json()
    resp = client.post(f'/api/inject/{job["id"]}/persist', json={'name': 'tl_dummy_cam'})
    assert resp.status_code == 201, resp.text
    target = resp.json()
    assert target['spec']['mode'] == 'media' and target['spec']['media']['encoding'] == 'mono8'
    count = len(received)
    # the separate dummy process keeps publishing after the job was stopped
    wait_for(lambda: len(received) >= count + 3, timeout=30)
    assert received[-1].encoding == 'mono8' and received[-1].width == 32
    client.delete(f"/api/targets/{target['id']}")


def test_pausing_a_media_job_holds_the_source_instead_of_dropping_frames(lab, helper, data_dir):
    """#5: frames are not read (and not counted against `count`) while paused."""
    fx.sine(data_dir / 'pause_tone.wav', seconds=2.0, rate=16000)  # 31 chunks of 64 ms
    received = helper.collector(AudioDataStamped, '/tl_pause_mic', 50)
    subscribe_visible(lab, '/tl_pause_mic')
    job = lab.injector.start(InjectSpec(mode='media', topic='/tl_pause_mic',
                                        source='pause_tone.wav', count=10,
                                        media={'sample_rate': 16000, 'chunk_samples': 1024}))
    wait_for(lambda: lab.injector.get(job['id'])['sent'] >= 3, timeout=15)
    assert lab.injector.set_paused(job['id'], True)['paused'] is True
    time.sleep(0.2)  # let an in-flight chunk finish
    held = lab.injector.get(job['id'])['sent']
    time.sleep(0.7)  # ~11 chunk periods: the old code read and discarded them
    assert lab.injector.get(job['id'])['sent'] == held
    lab.injector.set_paused(job['id'], False)
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=15)
    status = lab.injector.get(job['id'])
    assert status['sent'] == 10 and status['late_events'] == 0, status
    wait_for(lambda: len(received) == 10, timeout=5)


def test_a_paused_media_job_can_still_be_stopped(lab, helper, data_dir):
    fx.sine(data_dir / 'pause_stop.wav', seconds=2.0, rate=16000)
    topic = '/tl_pause_stop'
    helper.collector(AudioDataStamped, topic, 50)
    subscribe_visible(lab, topic)
    job = lab.injector.start(InjectSpec(mode='media', topic=topic,
                                        source='pause_stop.wav',
                                        media={'sample_rate': 16000, 'chunk_samples': 1024}))
    wait_for(lambda: lab.injector.get(job['id'])['sent'] >= 2, timeout=15)
    lab.injector.set_paused(job['id'], True)
    time.sleep(0.2)
    began = time.monotonic()
    lab.injector.stop(job['id'])
    assert time.monotonic() - began < 2.0
    assert lab.injector.get(job['id'])['state'] == 'stopped'
