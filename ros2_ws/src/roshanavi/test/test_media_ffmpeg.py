"""ffmpeg sources: decoding, resize, resampling, chunking, path / protocol safety, cleanup."""

import os
import subprocess
import time

import numpy as np
import psutil
import pytest

import media_fixtures as fx
from roshanavi.files import list_files
from roshanavi.media.errors import MediaError
from roshanavi.media.ffmpeg import probe, vet_input
from roshanavi.media.sources import (AudioSource, ImageFilesSource, VideoSource, frame_end,
                                     output_size)


def ffmpeg_children():
    return [p for p in psutil.Process().children(recursive=True)
            if p.name().startswith('ffmpeg') and p.status() != psutil.STATUS_ZOMBIE]


def zombies():
    return [p for p in psutil.Process().children(recursive=True)
            if p.status() == psutil.STATUS_ZOMBIE]


def test_output_size_keeps_aspect():
    assert output_size(320, 240, None, None) == (320, 240)
    assert output_size(320, 240, 160, None) == (160, 120)
    assert output_size(320, 240, None, 100) == (134, 100)
    assert output_size(320, 240, 50, 50) == (50, 50)
    with pytest.raises(MediaError):
        output_size(0, 0, None, None)


def test_probe_and_video_frames_raw_resized(data_dir):
    fx.video(data_dir / 'clip.mp4', seconds=1.0, size='320x240', rate=10)
    media = vet_input(str(data_dir), 'clip.mp4')
    info = probe(media)
    assert (info['width'], info['height'], info['fps']) == (320, 240, 10.0)
    src = VideoSource(media, 'bgr8', None, loop=False, width=160)
    frames = []
    while (f := src.next()) is not None:
        frames.append(f)
    assert len(frames) == 10 and src.period == pytest.approx(0.1)
    assert (frames[0].width, frames[0].height, len(frames[0].data)) == (160, 120, 160 * 120 * 3)
    src.close()


def test_video_jpeg_frames_rate_section_and_loop(data_dir):
    fx.video(data_dir / 'clip.mkv', seconds=2.0, rate=10)
    media = vet_input(str(data_dir), 'clip.mkv')
    src = VideoSource(media, 'jpeg', rate_hz=5, loop=True, start_sec=0.5, end_sec=1.5)
    frames = [src.next() for _ in range(12)]  # 5 frames per pass, loops
    src.close()
    assert all(f.data[:2] == b'\xff\xd8' and f.data[-2:] == b'\xff\xd9' for f in frames)
    assert src.period == pytest.approx(0.2)


def test_png_frame_splitting(data_dir):
    fx.video(data_dir / 'clip.avi', seconds=0.5, rate=10)
    src = VideoSource(vet_input(str(data_dir), 'clip.avi'), 'png', None, loop=False)
    frames = []
    while (f := src.next()) is not None:
        frames.append(f)
    assert len(frames) == 5 and all(f.data.endswith(b'IEND\xaeB`\x82') for f in frames)
    assert frame_end(bytearray(frames[0].data[:-4]), 'png') == 0


def test_audio_resampled_and_chunked(data_dir):
    fx.sine(data_dir / 'tone.mp3', seconds=1.0, rate=44100, freq=1000, channels=2)
    src = AudioSource(vet_input(str(data_dir), 'tone.mp3'), 16000, 1, 1024, loop=False)
    chunks = []
    while (c := src.next()) is not None:
        chunks.append(c)
    assert all(len(c.data) == 2048 and c.sample_rate == 16000 for c in chunks)
    assert 15 <= len(chunks) <= 17  # ~16000 samples (mp3 adds encoder padding)
    pcm = np.frombuffer(b''.join(c.data for c in chunks[2:10]), dtype='<i2').astype(float)
    crossings = np.count_nonzero(np.diff(np.signbit(pcm)))
    freq = crossings / 2 / (len(pcm) / 16000)
    assert freq == pytest.approx(1000, rel=0.03)
    assert src.period == pytest.approx(1024 / 16000)


def test_wav_stereo_target(data_dir):
    fx.sine(data_dir / 'tone.wav', seconds=0.5, rate=48000)
    src = AudioSource(vet_input(str(data_dir), 'tone.wav'), 8000, 2, 400, loop=False)
    chunks = []
    while (c := src.next()) is not None:
        chunks.append(c)
    assert len(chunks) == 10 and chunks[0].channels == 2 and len(chunks[0].data) == 1600


def test_image_folder_slideshow_in_name_order(data_dir):
    folder = data_dir / 'slides'
    folder.mkdir()
    fx.png(folder / 'b.png', color='green')
    fx.png(folder / 'a.png', color='red')
    inputs = [vet_input(str(data_dir), f'slides/{n}') for n in ('b.png', 'a.png')]
    src = ImageFilesSource(inputs, 'rgb8', rate_hz=2, loop=True)
    first, second, third = src.next(), src.next(), src.next()
    assert first.data[0] > 240 and first.data[1] < 15  # a.png (red) first
    assert second.data[1] > 100  # then b.png (green)
    assert third.data == first.data and src.period == 0.5
    native = ImageFilesSource(inputs[:1], 'png', rate_hz=1, loop=False)
    assert native.next().data == (folder / 'b.png').read_bytes()  # passed through as-is
    assert native.next() is None
    kinds = {f['path']: f['kind'] for f in list_files(str(data_dir))}
    assert kinds['slides'] == 'image_dir' and kinds['slides/a.png'] == 'image'


@pytest.mark.parametrize('name,content', [
    ('evil.mp4', '#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n'),
    ('evil.mkv', 'ffconcat version 1.0\nfile ../../etc/passwd\n'),
    ('evil.mp3', '\n#EXTM3U\n#EXTINF:1,\nfile:/etc/passwd\n'),
])
def test_playlists_are_rejected_before_ffmpeg(data_dir, name, content):
    (data_dir / name).write_text(content)
    with pytest.raises(MediaError) as err:
        vet_input(str(data_dir), name)
    assert err.value.code == 'forbidden_media'


def test_disguised_playlist_cannot_use_hls_or_concat(data_dir, tmp_path):
    """Even without the sniffing, the forced demuxer + whitelists stop indirection."""
    secret = tmp_path / 'secret.wav'
    fx.sine(secret, seconds=0.2)
    # Not detected by the sniffer (marker hidden past 512 bytes), still refused by ffmpeg.
    (data_dir / 'sneaky.mp4').write_text('x' * 600 + f'\nffconcat version 1.0\nfile {secret}\n')
    media = vet_input(str(data_dir), 'sneaky.mp4')
    with pytest.raises(MediaError):
        probe(media)
    # The whitelists alone refuse hls / concat even when ffmpeg would pick them.
    playlist = data_dir / 'list.m3u8'
    playlist.write_text(f'#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/a.wav\n#EXTINF:1,\n{secret}\n')
    done = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                           '-format_whitelist', 'mov', '-i', f'file:{playlist}'],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode != 0


@pytest.mark.parametrize('path', ['../outside.wav', '/etc/passwd', 'missing.mp4', 'notes.txt'])
def test_paths_outside_or_unsupported_are_rejected(data_dir, tmp_path, path):
    fx.sine(tmp_path / 'outside.wav', seconds=0.1)
    (data_dir / 'notes.txt').write_text('hi')
    with pytest.raises(MediaError) as err:
        vet_input(str(data_dir), path)
    assert err.value.code in ('forbidden_path', 'not_found', 'invalid_media')


def test_symlink_escape_is_rejected(data_dir, tmp_path):
    fx.sine(tmp_path / 'outside.wav', seconds=0.1)
    os.symlink(tmp_path / 'outside.wav', data_dir / 'link.wav')
    with pytest.raises(MediaError) as err:
        vet_input(str(data_dir), 'link.wav')
    assert err.value.code == 'forbidden_path'


def test_close_kills_ffmpeg_without_zombies(data_dir):
    fx.video(data_dir / 'long.mp4', seconds=30.0, rate=30)
    src = VideoSource(vet_input(str(data_dir), 'long.mp4'), 'rgb8', None, loop=True)
    assert src.next() is not None
    assert len(ffmpeg_children()) == 1
    src.close()
    assert src.next() is None
    deadline = time.monotonic() + 5
    while (ffmpeg_children() or zombies()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ffmpeg_children() == [] and zombies() == []
