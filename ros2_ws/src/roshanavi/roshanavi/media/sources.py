"""Frame sources for media injection, all decoded by ffmpeg through streaming pipes.

* :class:`ImageFilesSource` - one image or a folder slideshow (name order).
* :class:`VideoSource` - video frames (fps from the file unless overridden).
* :class:`AudioSource` - PCM S16LE chunks resampled to the target format.

Nothing is loaded whole: video and audio are read frame by frame / chunk by
chunk from ffmpeg's stdout. ``close()`` kills the running ffmpeg (which also
unblocks a reader waiting on the pipe).
"""

import logging
import os
import threading
from collections import OrderedDict
from typing import Any, List, Optional, Tuple

from .adapters.base import BYTES_PER_PIXEL, AudioChunk, ImageFrame
from .errors import MediaError
from .ffmpeg import FfmpegProcess, MediaInput, probe, run_once

LOG = logging.getLogger(__name__)

PIX_FMT = {'rgb8': 'rgb24', 'bgr8': 'bgr24', 'mono8': 'gray'}
ENCODER = {'jpeg': ['-c:v', 'mjpeg', '-q:v', '4', '-pix_fmt', 'yuvj420p'], 'png': ['-c:v', 'png']}
NATIVE_EXT = {'jpeg': ('.jpg', '.jpeg'), 'png': ('.png',)}
MAX_IMAGE_BYTES = 64 * 1024 * 1024
IMAGE_CACHE_BYTES = 256 * 1024 * 1024
READ_SIZE = 256 * 1024


def output_size(src_w: int, src_h: int, width: Optional[int],
                height: Optional[int]) -> Tuple[int, int]:
    """Target size; with one side given the aspect ratio is kept (even numbers)."""
    if not src_w or not src_h:
        raise MediaError('invalid_media', 'the file has no picture')
    if width and height:
        return width, height
    if width:
        return width, max(2, round(src_h * width / src_w / 2) * 2)
    if height:
        return max(2, round(src_w * height / src_h / 2) * 2), height
    return src_w, src_h


def output_args(fmt: str) -> List[str]:
    if fmt in PIX_FMT:
        return ['-f', 'rawvideo', '-pix_fmt', PIX_FMT[fmt], 'pipe:1']
    return [*ENCODER[fmt], '-f', 'image2pipe', 'pipe:1']


def decode_image(media: MediaInput, fmt: str, width: Optional[int] = None,
                 height: Optional[int] = None) -> ImageFrame:
    info = probe(media)
    out_w, out_h = output_size(info['width'], info['height'], width, height)
    resized = (out_w, out_h) != (info['width'], info['height'])
    if fmt in NATIVE_EXT and not resized and media.path.lower().endswith(NATIVE_EXT[fmt]):
        if os.path.getsize(media.path) > MAX_IMAGE_BYTES:
            raise MediaError('invalid_media', 'image file too large')
        with open(media.path, 'rb') as fh:  # already in the wanted encoding
            return ImageFrame(out_w, out_h, fmt, fh.read())
    args = [*media.args(), '-frames:v', '1', '-vf', f'scale={out_w}:{out_h}', *output_args(fmt)]
    data = run_once(args, MAX_IMAGE_BYTES)
    if fmt in PIX_FMT and len(data) != out_w * out_h * BYTES_PER_PIXEL[fmt]:
        raise MediaError('invalid_media', 'decoded image has an unexpected size')
    return ImageFrame(out_w, out_h, fmt, data)


class FrameSource:
    period: float = 1.0

    def next(self) -> Optional[Any]:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources; safe to call from another thread and repeatedly."""


class ImageFilesSource(FrameSource):
    """Images in name order at ``rate_hz``; a bounded cache avoids re-decoding loops."""

    def __init__(self, inputs: List[MediaInput], fmt: str, rate_hz: float, loop: bool,
                 width: Optional[int] = None, height: Optional[int] = None):
        if not inputs:
            raise MediaError('invalid_media', 'the folder has no images')
        self._inputs = sorted(inputs, key=lambda m: os.path.basename(m.path))
        self._fmt, self._size = fmt, (width, height)
        self._loop = loop
        self.period = 1.0 / rate_hz
        self._index = 0
        self._cache: 'OrderedDict[str, ImageFrame]' = OrderedDict()
        self._cached_bytes = 0
        self._first = self._decode(self._inputs[0])  # fail fast on a broken first image

    def _decode(self, media: MediaInput) -> ImageFrame:
        frame = self._cache.get(media.path)
        if frame is not None:
            self._cache.move_to_end(media.path)
            return frame
        frame = decode_image(media, self._fmt, *self._size)
        self._cache[media.path] = frame
        self._cached_bytes += len(frame.data)
        while self._cached_bytes > IMAGE_CACHE_BYTES and len(self._cache) > 1:
            _, old = self._cache.popitem(last=False)
            self._cached_bytes -= len(old.data)
        return frame

    def next(self) -> Optional[ImageFrame]:
        if self._index >= len(self._inputs) and not self._loop:
            return None
        media = self._inputs[self._index % len(self._inputs)]
        self._index += 1
        return self._decode(media)


class _StreamSource(FrameSource):
    """Common ffmpeg lifecycle: (re)start on demand, loop, kill on close."""

    def __init__(self, loop: bool):
        self._loop = loop
        self._lock = threading.Lock()
        self._proc: Optional[FfmpegProcess] = None
        self._closed = False

    def _args(self) -> List[str]:
        raise NotImplementedError

    def _read(self, proc: FfmpegProcess) -> Optional[Any]:
        raise NotImplementedError

    def _process(self) -> Optional[FfmpegProcess]:
        with self._lock:
            if self._closed:
                return None
            if self._proc is None:
                self._proc = FfmpegProcess(self._args())
            return self._proc

    def next(self) -> Optional[Any]:
        for _attempt in range(2):  # at most one restart per call (loop)
            proc = self._process()
            if proc is None:
                return None
            item = self._read(proc)
            if item is not None:
                return item
            self._finish(proc)
            if not self._loop:
                return None
        raise MediaError('invalid_media', 'the media file produced no data')

    def _finish(self, proc: FfmpegProcess) -> None:
        code = proc.wait(timeout=5.0)
        with self._lock:
            self._proc = None
            closed = self._closed
        proc.stop()
        if code != 0 and not closed:
            raise MediaError('ffmpeg_failed', f'ffmpeg failed: {proc.error_tail() or code}')

    def close(self) -> None:
        with self._lock:
            self._closed = True
            proc, self._proc = self._proc, None
        if proc is not None:
            proc.stop()


def _section_args(start_sec: float, end_sec: Optional[float]) -> List[str]:
    return ['-t', f'{end_sec - start_sec:.3f}'] if end_sec else []


class VideoSource(_StreamSource):
    def __init__(self, media: MediaInput, fmt: str, rate_hz: Optional[float], loop: bool,
                 start_sec: float = 0.0, end_sec: Optional[float] = None,
                 width: Optional[int] = None, height: Optional[int] = None,
                 default_fps: float = 30.0):
        super().__init__(loop)
        info = probe(media)
        self.size = output_size(info['width'], info['height'], width, height)
        self.fps = rate_hz or info['fps'] or default_fps
        self.period = 1.0 / self.fps
        self._media, self._fmt = media, fmt
        self._section = (start_sec, end_sec)
        self._buffer = bytearray()

    def _args(self) -> List[str]:
        self._buffer = bytearray()
        w, h = self.size
        return [*self._media.args(self._section[0]), *_section_args(*self._section), '-an',
                '-vf', f'fps={self.fps:.6f},scale={w}:{h}', *output_args(self._fmt)]

    def _read(self, proc: FfmpegProcess) -> Optional[ImageFrame]:
        w, h = self.size
        if self._fmt in PIX_FMT:
            data = proc.read_exact(w * h * BYTES_PER_PIXEL[self._fmt])
        else:
            data = self._read_encoded(proc)
        return None if data is None else ImageFrame(w, h, self._fmt, data)

    def _read_encoded(self, proc: FfmpegProcess) -> Optional[bytes]:
        while True:
            end = frame_end(self._buffer, self._fmt)
            if end:
                frame = bytes(self._buffer[:end])
                del self._buffer[:end]
                return frame
            chunk = proc.read_some(READ_SIZE)
            if not chunk:
                return None
            self._buffer += chunk
            if len(self._buffer) > MAX_IMAGE_BYTES:
                raise MediaError('invalid_media', 'encoded frame too large')


def frame_end(buf: bytearray, fmt: str) -> int:
    """Length of the first complete JPEG / PNG image in ``buf`` (0 if incomplete)."""
    if fmt == 'jpeg':
        idx = buf.find(b'\xff\xd9', 2)  # 0xFF in entropy data is stuffed, so EOI is unique
        return idx + 2 if idx >= 0 else 0
    pos = 8
    while pos + 8 <= len(buf):
        length = int.from_bytes(buf[pos:pos + 4], 'big')
        end = pos + 12 + length
        if end > len(buf):
            return 0
        if buf[pos + 4:pos + 8] == b'IEND':
            return end
        pos = end
    return 0


class AudioSource(_StreamSource):
    """PCM chunks of ``chunk_samples`` per channel; the last one is padded with silence."""

    def __init__(self, media: MediaInput, sample_rate: int, channels: int, chunk_samples: int,
                 loop: bool, start_sec: float = 0.0, end_sec: Optional[float] = None):
        super().__init__(loop)
        info = probe(media)
        if not info['sample_rate']:
            raise MediaError('invalid_media', 'the file has no audio')
        self._media = media
        self._section = (start_sec, end_sec)
        self.sample_rate, self.channels = sample_rate, channels
        self._chunk_bytes = chunk_samples * channels * 2
        self.period = chunk_samples / sample_rate

    def _args(self) -> List[str]:
        return [*self._media.args(self._section[0]), *_section_args(*self._section), '-vn',
                '-ac', str(self.channels), '-ar', str(self.sample_rate),
                '-f', 's16le', '-acodec', 'pcm_s16le', 'pipe:1']

    def _read(self, proc: FfmpegProcess) -> Optional[AudioChunk]:
        data = bytearray()
        while len(data) < self._chunk_bytes:
            chunk = proc.read_some(self._chunk_bytes - len(data))
            if not chunk:
                break
            data += chunk
        if not data:
            return None
        data += bytes(self._chunk_bytes - len(data))  # pad the tail with silence
        return AudioChunk(bytes(data), self.sample_rate, self.channels)
