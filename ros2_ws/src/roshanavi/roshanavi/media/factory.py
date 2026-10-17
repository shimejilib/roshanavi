"""Build a ``media`` inject job from a request: type detection, adapter, source."""

import dataclasses
import os
from typing import Any, Dict, List, Optional, Sequence

from ..files import FileAccessError, resolve_in_data_dir
from ..jobs import InjectSpec, validate_topic
from ..ros_runtime import RosRuntime
from . import adapters
from .adapters.base import KIND_AUDIO, KIND_IMAGE
from .errors import MediaError
from .ffmpeg import MediaInput, require_binary, vet_input
from .kinds import IMAGE_DEMUXERS
from .job import MediaJob
from .options import (DEFAULT_IMAGE_RATE_HZ, DEFAULT_VIDEO_FPS, MediaOptions, detect_type,
                      endpoint_types, parse_options, resolve_calibration, settings_for)
from .sources import AudioSource, FrameSource, ImageFilesSource, VideoSource

MAX_SLIDESHOW_FILES = 10000


def choose_type(runtime: RosRuntime, topic: str, requested: Optional[str]) -> str:
    """The requested type, else the one the topic's endpoints use (subscribers first)."""
    if requested:
        return requested
    detected = detect_type(endpoint_types(runtime, topic))
    if detected is None:
        names = ', '.join(t['type'] for t in adapters.supported())
        raise MediaError('media_type_required', f'no node uses {topic} yet, so its type is '
                         f'unknown; choose one of: {names}')
    return detected


def type_info(runtime: RosRuntime, topic: Optional[str]) -> Dict[str, Any]:
    """For the UI: supported types and, for a topic, its endpoint types / detection."""
    supported = adapters.supported()
    result: Dict[str, Any] = {'supported': supported}
    if topic:
        validate_topic(topic)
        types = endpoint_types(runtime, topic)
        try:
            detected = detect_type(types)
        except MediaError:
            detected = None
        result.update(topic=topic, endpoints=types, detected=detected,
                      detected_supported=detected in {t['type'] for t in supported})
    return result


def _folder_inputs(data_dir: str, folder: str, rel: str) -> List[MediaInput]:
    names = sorted(n for n in os.listdir(folder)
                   if os.path.splitext(n)[1].lower() in IMAGE_DEMUXERS)
    if len(names) > MAX_SLIDESHOW_FILES:
        raise MediaError('invalid_media', f'more than {MAX_SLIDESHOW_FILES} images in the folder')
    return [vet_input(data_dir, os.path.join(rel, n), 'image') for n in names]


def _inputs(data_dir: str, source: str) -> List[MediaInput]:
    try:
        path = resolve_in_data_dir(data_dir, source)
    except FileAccessError as exc:
        raise MediaError(exc.code, str(exc), 404 if exc.code == 'not_found' else 400) from exc
    inputs = _folder_inputs(data_dir, path, source) if os.path.isdir(path) \
        else [vet_input(data_dir, source)]
    if not inputs:
        raise MediaError('invalid_media', f'no images in the folder {source!r}')
    return inputs


def build_source(inputs: List[MediaInput], fmt: str, spec: InjectSpec,
                 opts: MediaOptions) -> FrameSource:
    first = inputs[0]
    if first.kind == 'image':
        single = len(inputs) == 1
        return ImageFilesSource(inputs, fmt, spec.rate_hz or DEFAULT_IMAGE_RATE_HZ,
                                loop=spec.loop or single, width=opts.width, height=opts.height)
    if first.kind == 'video':
        return VideoSource(first, fmt, spec.rate_hz, spec.loop, opts.start_sec, opts.end_sec,
                           opts.width, opts.height, DEFAULT_VIDEO_FPS)
    return AudioSource(first, opts.sample_rate, opts.channels, opts.chunk_samples, spec.loop,
                       opts.start_sec, opts.end_sec)


def _check_kind(inputs: List[MediaInput], opts: MediaOptions, adapter_kind: str,
                type_name: str) -> None:
    file_kind = inputs[0].kind
    if opts.kind != 'auto' and opts.kind != file_kind:
        raise MediaError('invalid_media', f'the file is a {file_kind}, not a {opts.kind}')
    wanted = KIND_AUDIO if file_kind == 'audio' else KIND_IMAGE
    if wanted != adapter_kind:
        raise MediaError('media_kind_mismatch', f'{type_name} carries {adapter_kind} data, but '
                         f'the file is a {file_kind}')


def create_media_job(spec: InjectSpec, runtime: RosRuntime, data_dir: str,
                     roots: Sequence[str] = ()) -> MediaJob:
    validate_topic(spec.topic)
    if not spec.source:
        raise MediaError('invalid_request', 'source (a file or folder in the data dir) is '
                         'required for media mode')
    opts = parse_options(spec.media)
    require_binary('ffmpeg')
    type_name = choose_type(runtime, spec.topic, spec.type)
    adapter = adapters.get(type_name)
    inputs = _inputs(data_dir, spec.source)
    _check_kind(inputs, opts, adapter.kind, type_name)
    calibration = resolve_calibration(opts, [data_dir, *roots])
    settings = settings_for(opts, calibration)
    source = build_source(inputs, adapter.frame_format(settings), spec, opts)
    job_spec = dataclasses.replace(spec, type=adapter.type_name)
    return MediaJob(job_spec, runtime, adapter, source, settings,
                    jitter_sec=opts.jitter_ms / 1000.0, drop_ratio=opts.drop_ratio,
                    prebuffer_ms=opts.prebuffer_ms, late_policy=opts.late_policy)
