"""In-memory image conversions for browser capture and the image viewer.

Raw pixel conversions use numpy (already an rclpy dependency); JPEG/PNG
encode/decode uses Pillow (``python3-pil``). File sources never come here:
they are decoded by ffmpeg (``sources.py``).
"""

import io
import logging
import struct
from typing import Optional, Tuple

import numpy as np

from .adapters.base import BYTES_PER_PIXEL, ImageFrame
from .errors import MediaError

LOG = logging.getLogger(__name__)

try:  # optional: only browser camera -> Image and the viewer need it
    from PIL import Image as PilImage
except ImportError:  # pragma: no cover - depends on the environment
    PilImage = None

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _require_pil() -> None:
    if PilImage is None:
        raise MediaError('pillow_missing', 'Pillow is not installed (apt install python3-pil)', 500)


def encoded_format(data: bytes) -> Optional[str]:
    if data[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if data[:8] == PNG_SIGNATURE:
        return 'png'
    return None


def jpeg_size(data: bytes) -> Tuple[int, int]:
    """(width, height) from the JPEG SOF segment without decoding."""
    if data[:2] != b'\xff\xd8':
        raise MediaError('invalid_media', 'not a JPEG image')
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise MediaError('invalid_media', 'corrupt JPEG (marker expected)')
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        length = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if marker in SOF_MARKERS and pos + 9 <= len(data):
            height, width = struct.unpack('>HH', data[pos + 5:pos + 9])
            return width, height
        pos += 2 + length
    raise MediaError('invalid_media', 'corrupt JPEG (no frame header)')


def image_size(data: bytes) -> Tuple[int, int]:
    fmt = encoded_format(data)
    if fmt == 'jpeg':
        return jpeg_size(data)
    if fmt == 'png' and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    raise MediaError('invalid_media', 'only JPEG and PNG images are supported')


def _pixels(frame: ImageFrame) -> np.ndarray:
    channels = BYTES_PER_PIXEL[frame.fmt]
    expected = frame.width * frame.height * channels
    if len(frame.data) < expected:
        raise MediaError('invalid_media', f'image data too short ({len(frame.data)} < {expected})')
    arr = np.frombuffer(frame.data, dtype=np.uint8, count=expected)
    return arr.reshape(frame.height, frame.width, channels)


def to_rgb(frame: ImageFrame) -> np.ndarray:
    """H x W x 3 uint8 RGB array from any raw frame."""
    px = _pixels(frame)
    if frame.fmt in ('rgb8', 'rgba8'):
        return px[:, :, :3]
    if frame.fmt in ('bgr8', 'bgra8'):
        return px[:, :, 2::-1]
    return np.repeat(px, 3, axis=2)  # mono8


def convert_raw(rgb: np.ndarray, fmt: str) -> bytes:
    """RGB array -> raw bytes in ``fmt`` (rgb8 / bgr8 / mono8)."""
    if fmt == 'rgb8':
        return np.ascontiguousarray(rgb).tobytes()
    if fmt == 'bgr8':
        return np.ascontiguousarray(rgb[:, :, ::-1]).tobytes()
    if fmt == 'mono8':  # ITU-R BT.601 luma
        luma = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
        return np.clip(luma + 0.5, 0, 255).astype(np.uint8).tobytes()
    raise MediaError('invalid_request', f'unsupported pixel format {fmt}')


def decode(data: bytes, fmt: str) -> ImageFrame:
    """JPEG/PNG bytes -> raw frame in ``fmt``."""
    _require_pil()
    try:
        with PilImage.open(io.BytesIO(data)) as img:
            rgb = np.asarray(img.convert('RGB'))
    except (OSError, ValueError) as exc:
        raise MediaError('invalid_media', f'cannot decode image: {exc}') from exc
    height, width = rgb.shape[:2]
    return ImageFrame(width, height, fmt, convert_raw(rgb, fmt))


def encode_jpeg(frame: ImageFrame, max_width: int = 640, quality: int = 75) -> ImageFrame:
    """Any frame -> JPEG no wider than ``max_width`` (JPEGs within the limit pass through)."""
    if frame.fmt == 'jpeg' and frame.width <= max_width:
        return frame
    _require_pil()
    try:
        if frame.is_raw:
            img = PilImage.fromarray(np.ascontiguousarray(to_rgb(frame)), 'RGB')
        else:
            img = PilImage.open(io.BytesIO(frame.data)).convert('RGB')
        if img.width > max_width:
            height = max(1, round(img.height * max_width / img.width))
            img = img.resize((max_width, height))
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=quality)
    except (OSError, ValueError) as exc:
        raise MediaError('invalid_media', f'cannot encode image: {exc}') from exc
    return ImageFrame(img.width, img.height, 'jpeg', out.getvalue())
