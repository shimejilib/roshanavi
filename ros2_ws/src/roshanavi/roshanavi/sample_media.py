"""Sample media for the perception demo, generated with ffmpeg on first run (P5).

No binary files are committed: when the server starts (``--sample-media``, on by
default) it creates the missing files under ``<data_dir>/samples/`` in a
background thread:

- ``blobs.mp4``: 10 s, 320x240, 15 fps. Two bright discs moving over ffmpeg's
  ``testsrc`` pattern darkened to 25 %, so ``image_filter`` has edges to find and
  ``blob_detector`` has exactly two clear blobs most of the time.
- ``tone.wav``: 12 s, 16 kHz mono: 2 s of a 440 Hz tone, 2 s of silence, repeated
  (``audio_level`` switches between "sound" and "silence").

Existing files are never overwritten. Each file is written to a temporary name
and renamed when ffmpeg succeeded, so a half-written file is never used.
"""

import logging
import os
import shutil
import subprocess
import threading
from typing import Dict, List

LOG = logging.getLogger(__name__)

SAMPLES_SUBDIR = 'samples'
FFMPEG_TIMEOUT_SEC = 120

# Disc centres move on circles; geq draws them on top of the darkened testsrc.
_DISCS = ("if(lt(hypot(X-(110+60*cos(T*1.3)),Y-(120+50*sin(T*1.3))),26)"
          "+lt(hypot(X-(230+40*sin(T*0.9)),Y-(110+60*cos(T*0.9))),20),255,lum(X,Y)*0.25)")
_MUTED = '128+({p}(X,Y)-128)*0.4'  # muted colours: the discs read as white
VIDEO_ARGS = ['-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=15:duration=10',
              '-vf', f"format=yuv420p,geq=lum='{_DISCS}':cb='{_MUTED.format(p='cb')}'"
                     f":cr='{_MUTED.format(p='cr')}'",
              '-c:v', 'mpeg4', '-q:v', '4', '-f', 'mp4']
AUDIO_ARGS = ['-f', 'lavfi', '-i',
              "aevalsrc='if(lt(mod(t,4),2),0.5*sin(2*PI*440*t),0)':s=16000:d=12",
              '-ac', '1', '-c:a', 'pcm_s16le', '-f', 'wav']
SAMPLES: Dict[str, List[str]] = {'blobs.mp4': VIDEO_ARGS, 'tone.wav': AUDIO_ARGS}


def samples_dir(data_dir: str) -> str:
    return os.path.join(data_dir, SAMPLES_SUBDIR)


def ensure_samples(data_dir: str) -> List[str]:
    """Create missing sample files; returns the names created. Never raises."""
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        LOG.warning('ffmpeg not found: perception demo samples are not generated')
        return []
    directory = samples_dir(data_dir)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        LOG.warning('cannot create %s: %s', directory, exc)
        return []
    created = []
    for name, args in SAMPLES.items():
        path = os.path.join(directory, name)
        if os.path.exists(path):
            continue
        if _generate(ffmpeg, args, path):
            created.append(name)
    if created:
        LOG.info('generated sample media in %s: %s', directory, ', '.join(created))
    return created


def _generate(ffmpeg: str, args: List[str], path: str) -> bool:
    tmp = f'{path}.part'
    cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args, tmp]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning('generating %s failed: %s', path, exc)
        _remove(tmp)
        return False
    if result.returncode != 0:
        LOG.warning('generating %s failed: %s', path, result.stderr.strip()[-500:])
        _remove(tmp)
        return False
    try:
        os.replace(tmp, path)
    except OSError as exc:
        LOG.warning('cannot move %s into place: %s', path, exc)
        _remove(tmp)
        return False
    return True


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        LOG.warning('cannot remove %s: %s', path, exc)


def ensure_in_background(data_dir: str) -> threading.Thread:
    thread = threading.Thread(target=ensure_samples, args=(data_dir,), name='sample-media',
                              daemon=True)
    thread.start()
    return thread
