"""Media fixtures generated at test time with ffmpeg (no binaries in git)."""

import subprocess
from pathlib import Path


def ffmpeg(*args: str) -> None:
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True, timeout=60,
                   stdin=subprocess.DEVNULL)


def video(path: Path, seconds: float = 1.0, size: str = '320x240', rate: int = 10) -> Path:
    ffmpeg('-f', 'lavfi', '-i', f'testsrc=size={size}:rate={rate}', '-t', str(seconds),
           '-pix_fmt', 'yuv420p', str(path))
    return path


def sine(path: Path, seconds: float = 1.0, rate: int = 44100, freq: int = 440,
         channels: int = 1) -> Path:
    ffmpeg('-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate={rate}:duration={seconds}',
           '-ac', str(channels), str(path))
    return path


def png(path: Path, size: str = '64x48', color: str = 'red') -> Path:
    ffmpeg('-f', 'lavfi', '-i', f'color=c={color}:size={size}', '-frames:v', '1', str(path))
    return path


def jpeg_bytes(size: str = '64x48', color: str = 'blue') -> bytes:
    done = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                           f'color=c={color}:size={size}', '-frames:v', '1', '-f', 'image2pipe',
                           '-c:v', 'mjpeg', 'pipe:1'], capture_output=True, check=True, timeout=30)
    return done.stdout
