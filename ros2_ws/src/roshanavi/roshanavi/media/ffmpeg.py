"""Safe ffmpeg / ffprobe invocation for media files inside ``data_dir``.

Safety rules (a crafted file must not make ffmpeg fetch URLs or read files
outside the data directory):

* The path is resolved with ``realpath`` and must stay inside ``data_dir``
  (:func:`roshanavi.files.resolve_in_data_dir`) and be a regular file.
* The demuxer is chosen from the file extension and forced with ``-f``; the
  same single demuxer is the only entry of ``-format_whitelist``. Playlist /
  indirection demuxers (hls, concat, dash, image2 sequences ...) can therefore
  never be selected, even for a playlist renamed to ``.mp4``.
* ``-protocol_whitelist file,pipe`` blocks http/tcp/... and the input is passed
  as ``file:<absolute path>`` so no other protocol prefix can be smuggled in.
* Text playlists are rejected up front with a plain error (``#EXTM3U``,
  ``ffconcat`` ...), before ffmpeg ever sees them.
* argv lists only (no shell); ``-nostdin``; each process gets its own session
  and is always reaped (:class:`FfmpegProcess.stop`).
"""

import json
import logging
import os
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from ..files import FileAccessError, resolve_in_data_dir
from .errors import MediaError
from .kinds import KIND_DEMUXERS, media_kind

LOG = logging.getLogger(__name__)

PLAYLIST_MARKERS = (b'#EXTM3U', b'ffconcat', b'<MPD', b'#EXTINF')
SNIFF_BYTES = 4096
PROBE_TIMEOUT_SEC = 15.0
STOP_TIMEOUT_SEC = 2.0
STDERR_LINES = 20


def require_binary(name: str = 'ffmpeg') -> str:
    path = shutil.which(name)
    if path is None:
        raise MediaError('ffmpeg_missing', f'{name} is not installed (apt install ffmpeg)', 500)
    return path


@dataclass(frozen=True)
class MediaInput:
    """A vetted input file: absolute path, kind and the forced demuxer."""

    path: str
    kind: str
    demuxer: str

    def args(self, start_sec: float = 0.0) -> List[str]:
        """ffmpeg/ffprobe input options + ``-i`` for this file."""
        seek = ['-ss', f'{start_sec:.3f}'] if start_sec > 0 else []
        return ['-protocol_whitelist', 'file,pipe', '-format_whitelist', self.demuxer,
                '-f', self.demuxer, *seek, '-i', f'file:{self.path}']


def _sniff_playlist(path: str) -> None:
    try:
        with open(path, 'rb') as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError as exc:
        raise MediaError('invalid_media', f'cannot read {os.path.basename(path)}: {exc}') from exc
    stripped = head.lstrip(b'\xef\xbb\xbf \t\r\n')
    if any(stripped.startswith(m) or m in head[:512] for m in PLAYLIST_MARKERS):
        raise MediaError('forbidden_media', 'playlist / concat files are not allowed as media '
                         'input (they can point to other files or URLs)')


def vet_input(data_dir: str, user_path: str, kind: Optional[str] = None) -> MediaInput:
    """Check containment, kind and content of a media file; raise MediaError otherwise."""
    try:
        path = resolve_in_data_dir(data_dir, user_path)
    except FileAccessError as exc:
        raise MediaError(exc.code, str(exc), 404 if exc.code == 'not_found' else 400) from exc
    if not os.path.isfile(path):
        raise MediaError('invalid_media', f'not a regular file: {user_path}')
    found = media_kind(path)
    if found is None:
        allowed = sorted(e for table in KIND_DEMUXERS.values() for e in table)
        raise MediaError('invalid_media', f'unsupported media file {user_path!r}; '
                         f'use one of {", ".join(allowed)}')
    if kind is not None and kind != found:
        raise MediaError('invalid_media', f'{user_path!r} is a {found} file, expected {kind}')
    _sniff_playlist(path)
    ext = os.path.splitext(path)[1].lower()
    return MediaInput(path=path, kind=found, demuxer=KIND_DEMUXERS[found][ext])


def _parse_rate(text: Optional[str]) -> Optional[float]:
    if not text or '/' not in text:
        return None
    num, den = text.split('/', 1)
    try:
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    return value if 0 < value <= 240 else None


def probe(media: MediaInput) -> Dict[str, Optional[float]]:
    """``{width, height, fps, duration, sample_rate, channels}`` of the first streams."""
    argv = [require_binary('ffprobe'), '-v', 'error', *media.args(),
            '-show_entries', 'stream=codec_type,width,height,avg_frame_rate,r_frame_rate,'
            'sample_rate,channels:format=duration', '-of', 'json']
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC,
                              stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError('invalid_media', 'ffprobe timed out') from exc
    if done.returncode != 0:
        tail = ' | '.join(done.stderr.strip().splitlines()[-3:])
        raise MediaError('invalid_media', f'cannot read media file: {tail or "ffprobe failed"}')
    return _summarize(json.loads(done.stdout or '{}'))


def _summarize(info: Dict) -> Dict[str, Optional[float]]:
    streams = info.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'), {})
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
    duration = (info.get('format') or {}).get('duration')
    return {'width': video.get('width'), 'height': video.get('height'),
            'fps': (_parse_rate(video.get('avg_frame_rate'))
                    or _parse_rate(video.get('r_frame_rate'))),
            'duration': float(duration) if duration not in (None, 'N/A') else None,
            'sample_rate': int(audio['sample_rate']) if audio.get('sample_rate') else None,
            'channels': audio.get('channels')}


class FfmpegProcess:
    """One ffmpeg subprocess with streaming pipes; always reaped by :meth:`stop`."""

    def __init__(self, args: List[str], stdin: bool = False):
        self.argv = [require_binary('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                     *([] if stdin else ['-nostdin']), *args]
        self._stderr: Deque[str] = deque(maxlen=STDERR_LINES)
        try:
            self._proc = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            raise MediaError('ffmpeg_failed', f'cannot start ffmpeg: {exc}', 500) from exc
        self._reader = threading.Thread(target=self._drain_stderr, daemon=True,
                                        name=f'ffmpeg-err-{self._proc.pid}')
        self._reader.start()

    @property
    def pid(self) -> int:
        return self._proc.pid

    def _drain_stderr(self) -> None:
        for raw in iter(self._proc.stderr.readline, b''):
            line = raw.decode('utf-8', 'replace').rstrip()
            if line:
                self._stderr.append(line)

    def read_exact(self, size: int) -> Optional[bytes]:
        """Exactly ``size`` bytes, or None at end of stream (a partial tail is dropped)."""
        chunks, remaining = [], size
        while remaining > 0:
            chunk = self._proc.stdout.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def read_some(self, size: int = 65536) -> bytes:
        return self._proc.stdout.read1(size)

    def write(self, data: bytes) -> None:
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def close_stdin(self) -> None:
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            self._proc.stdin.close()

    def error_tail(self) -> str:
        return ' | '.join(list(self._stderr)[-3:])

    def wait(self, timeout: Optional[float] = None) -> int:
        code = self._proc.wait(timeout=timeout)
        self._reader.join(timeout=1.0)
        return code

    def stop(self) -> None:
        """Terminate (then kill) and reap; idempotent."""
        proc = self._proc
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=STOP_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                LOG.warning('ffmpeg %d ignored SIGTERM, killing', proc.pid)
                proc.kill()
                proc.wait()
        for pipe in (proc.stdin, proc.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError as exc:
                    LOG.debug('closing ffmpeg pipe: %s', exc)
        self._reader.join(timeout=1.0)


def run_once(args: List[str], max_bytes: int) -> bytes:
    """Run ffmpeg to completion and return stdout (capped); raise MediaError on failure."""
    proc = FfmpegProcess(args)
    try:
        data = bytearray()
        while len(data) <= max_bytes:
            chunk = proc.read_some()
            if not chunk:
                break
            data += chunk
        if len(data) > max_bytes:
            raise MediaError('invalid_media', f'decoded output larger than {max_bytes} bytes')
        code = proc.wait(timeout=PROBE_TIMEOUT_SEC)
        if code != 0:
            raise MediaError('invalid_media', f'ffmpeg failed: {proc.error_tail()}')
        return bytes(data)
    finally:
        proc.stop()
