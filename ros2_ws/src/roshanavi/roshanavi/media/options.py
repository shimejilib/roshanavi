"""Options of the ``media`` inject mode (API, project file and dummy config share them)."""

import os
from typing import Any, Dict, List, Literal, Optional, Sequence

from ..pydantic_compat import (StrictModel, ValidationError, confloat, conint, constr,
                               validation_errors)
from ..ros_runtime import RosRuntime
from .adapters.base import MediaSettings
from .camera_info import Calibration, load_calibration
from .errors import MediaError

DEFAULT_IMAGE_RATE_HZ = 1.0
DEFAULT_VIDEO_FPS = 30.0


class MediaOptions(StrictModel):
    """Conversion settings. Topic, type, rate_hz, count and loop live on the job itself."""

    kind: Literal['auto', 'image', 'video', 'audio'] = 'auto'
    # images (Image: pixel layout; CompressedImage: encoding)
    encoding: Literal['rgb8', 'bgr8', 'mono8'] = 'rgb8'
    format: Literal['jpeg', 'png'] = 'jpeg'
    frame_id: constr(max_length=256) = ''
    width: Optional[conint(ge=16, le=7680)] = None
    height: Optional[conint(ge=16, le=4320)] = None
    camera_info: bool = True
    camera_info_topic: Optional[constr(max_length=256)] = None
    calibration: Optional[constr(max_length=1024)] = None
    # video / audio section
    start_sec: confloat(ge=0, le=86400) = 0.0
    end_sec: Optional[confloat(gt=0, le=86400)] = None
    # audio target format
    sample_rate: conint(ge=8000, le=192000) = 16000
    channels: conint(ge=1, le=8) = 1
    chunk_samples: conint(ge=32, le=65536) = 1024
    jitter_ms: confloat(ge=0, le=1000) = 0.0
    # real-time pacing (see pacing.py / prefetch.py)
    prebuffer_ms: confloat(ge=0, le=10000) = 300.0
    late_policy: Literal['shift', 'catch_up', 'drop'] = 'shift'
    drop_ratio: confloat(ge=0, le=0.9) = 0.0
    audio_info: bool = True
    audio_info_topic: Optional[constr(max_length=256)] = None


def check_section(opts: MediaOptions) -> None:
    if opts.end_sec is not None and opts.end_sec <= opts.start_sec:
        raise MediaError('invalid_request', 'end_sec must be after start_sec')


def settings_for(opts: MediaOptions, calibration: Optional[Calibration] = None) -> MediaSettings:
    return MediaSettings(frame_id=opts.frame_id, encoding=opts.encoding, format=opts.format,
                         sample_rate=opts.sample_rate, channels=opts.channels,
                         camera_info=opts.camera_info, camera_info_topic=opts.camera_info_topic,
                         calibration=calibration, audio_info=opts.audio_info,
                         audio_info_topic=opts.audio_info_topic)


def resolve_calibration(opts: MediaOptions, roots: Sequence[str]) -> Optional[Calibration]:
    if not opts.calibration:
        return None
    path = opts.calibration
    if not os.path.isabs(path):
        path = os.path.join(roots[0], path)
    return load_calibration(path, roots)


def parse_options(raw: Optional[Dict[str, Any]]) -> MediaOptions:
    try:
        opts = MediaOptions.model_validate(raw or {})
    except ValidationError as exc:
        parts = ['.'.join(str(p) for p in e['loc']) + ': ' + e['msg']
                 for e in validation_errors(exc)]
        raise MediaError('invalid_request', 'media: ' + '; '.join(parts)) from exc
    check_section(opts)
    return opts


def endpoint_types(runtime: RosRuntime, topic: str) -> Dict[str, List[str]]:
    """Types used by the topic's existing subscribers and publishers."""
    subs = sorted({i.topic_type for i in runtime.subscriptions_info(topic)})
    pubs = sorted({i.topic_type for i in runtime.publishers_info(topic)})
    return {'subscribers': subs, 'publishers': pubs}


def detect_type(types: Dict[str, List[str]]) -> Optional[str]:
    """Subscriber types first (what the receiving node expects), then publishers."""
    for side in ('subscribers', 'publishers'):
        if len(types[side]) == 1:
            return types[side][0]
        if len(types[side]) > 1:
            raise MediaError('media_type_ambiguous', f'the topic has several {side} types: '
                             f'{", ".join(types[side])}; choose one explicitly')
    return None
