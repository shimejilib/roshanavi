"""CameraInfo for image injection: defaults or a camera_calibration YAML file.

The YAML format is the one written by ``camera_calibration`` /
``camera_info_manager``::

    image_width: 640
    image_height: 480
    camera_name: cam
    camera_matrix: {rows: 3, cols: 3, data: [fx, 0, cx, 0, fy, cy, 0, 0, 1]}
    distortion_model: plumb_bob
    distortion_coefficients: {rows: 1, cols: 5, data: [k1, k2, t1, t2, k3]}
    rectification_matrix: {rows: 3, cols: 3, data: [...]}
    projection_matrix: {rows: 3, cols: 4, data: [...]}

The file must lie inside the workspace or the data directory.
"""

import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import yaml

from .errors import MediaError

IDENTITY3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
MAX_CALIBRATION_BYTES = 64 * 1024


@dataclass(frozen=True)
class Calibration:
    width: int
    height: int
    k: Sequence[float]
    d: Sequence[float] = field(default_factory=lambda: (0.0,) * 5)
    r: Sequence[float] = IDENTITY3
    p: Sequence[float] = ()
    distortion_model: str = 'plumb_bob'


def default_calibration(width: int, height: int) -> Calibration:
    """A plausible pinhole camera (about 60 degrees horizontal FOV), no distortion."""
    focal = width * 0.866  # = (width / 2) / tan(30 deg)
    cx, cy = width / 2.0, height / 2.0
    return Calibration(width, height, k=(focal, 0.0, cx, 0.0, focal, cy, 0.0, 0.0, 1.0))


def _matrix(raw: Any, name: str, size: int) -> List[float]:
    data = raw.get('data') if isinstance(raw, dict) else raw
    if not isinstance(data, list) or len(data) != size:
        raise MediaError('invalid_calibration', f'{name} must have {size} numbers')
    try:
        return [float(v) for v in data]
    except (TypeError, ValueError) as exc:
        raise MediaError('invalid_calibration', f'{name} must contain numbers') from exc


def parse_calibration(text: str) -> Calibration:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MediaError('invalid_calibration', f'calibration YAML is not valid: {exc}') from exc
    if not isinstance(raw, dict):
        raise MediaError('invalid_calibration', 'calibration YAML must be a mapping')
    try:
        width, height = int(raw['image_width']), int(raw['image_height'])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaError('invalid_calibration', 'image_width / image_height are required') from exc
    dist = raw.get('distortion_coefficients', {'data': [0.0] * 5})
    dist_data = dist.get('data') if isinstance(dist, dict) else dist
    return Calibration(
        width, height, k=_matrix(raw.get('camera_matrix'), 'camera_matrix', 9),
        d=_matrix(dist, 'distortion_coefficients', len(dist_data or [])) if dist_data else [],
        r=_matrix(raw.get('rectification_matrix', list(IDENTITY3)), 'rectification_matrix', 9),
        p=_matrix(raw['projection_matrix'], 'projection_matrix', 12)
        if 'projection_matrix' in raw else (),
        distortion_model=str(raw.get('distortion_model') or 'plumb_bob'))


def load_calibration(path: str, roots: Sequence[str]) -> Calibration:
    """Read a calibration file whose realpath is inside one of ``roots``."""
    real = os.path.realpath(path)
    allowed = [os.path.realpath(r) for r in roots if r]
    if not any(os.path.commonpath([root, real]) == root for root in allowed):
        raise MediaError('forbidden_path', 'calibration file must be inside the workspace or '
                         'the data directory')
    if not os.path.isfile(real) or os.path.getsize(real) > MAX_CALIBRATION_BYTES:
        raise MediaError('invalid_calibration', f'not a calibration file: {path}')
    with open(real, encoding='utf-8') as fh:
        return parse_calibration(fh.read())


def build_camera_info(msg_type: type, stamp: Any, frame_id: str, width: int, height: int,
                      calib: Optional[Calibration]) -> Any:
    """CameraInfo for a frame; the calibration is scaled when the frame size differs."""
    cal = calib or default_calibration(width, height)
    sx, sy = width / cal.width, height / cal.height
    k = list(cal.k)
    k[0], k[2], k[4], k[5] = k[0] * sx, k[2] * sx, k[4] * sy, k[5] * sy
    if cal.p:
        p = list(cal.p)
        p[0], p[2], p[5], p[6] = p[0] * sx, p[2] * sx, p[5] * sy, p[6] * sy
    else:
        p = [k[0], 0.0, k[2], 0.0, 0.0, k[4], k[5], 0.0, 0.0, 0.0, 1.0, 0.0]
    msg = msg_type()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.width, msg.height = width, height
    msg.distortion_model = cal.distortion_model
    msg.d = [float(v) for v in cal.d]
    msg.k = [float(v) for v in k]
    msg.r = [float(v) for v in cal.r]
    msg.p = [float(v) for v in p]
    return msg
