"""sensor_msgs Image / CompressedImage adapters (+ CameraInfo companion)."""

import array
from typing import Any, List

import numpy as np

from ... import msgutil
from .. import imaging
from ..camera_info import build_camera_info
from ..errors import MediaError
from .base import (BYTES_PER_PIXEL, KIND_IMAGE, Companion, ImageFrame, MediaAdapter,
                   MediaSettings, sibling_topic, stamp_header)

CAMERA_INFO_TYPE = 'sensor_msgs/msg/CameraInfo'
CAMERA_INFO_NAME = 'camera_info'
VIEWABLE_ENCODINGS = {'rgb8', 'bgr8', 'mono8', 'rgba8', 'bgra8', '8UC1', '8UC3', 'mono16',
                      '16UC1'}


def camera_info_companion(topic: str, settings: MediaSettings) -> List[Companion]:
    if not settings.camera_info:
        return []
    info_type = msgutil.resolve_type(CAMERA_INFO_TYPE)

    def build(stamp: Any, frame: ImageFrame) -> Any:
        return build_camera_info(info_type, stamp, settings.frame_id, frame.width, frame.height,
                                 settings.calibration)
    return [Companion(CAMERA_INFO_TYPE,
                      settings.camera_info_topic or sibling_topic(topic, CAMERA_INFO_NAME),
                      build, every_frame=True)]


def _mono16_to_mono8(msg: Any) -> bytes:
    dtype = '>u2' if msg.is_bigendian else '<u2'
    values = np.frombuffer(bytes(msg.data), dtype=dtype).reshape(msg.height, -1)[:, :msg.width]
    top = int(values.max()) or 1
    return (values.astype(np.float32) * (255.0 / top)).astype(np.uint8).tobytes()


class ImageAdapter(MediaAdapter):
    type_name = 'sensor_msgs/msg/Image'
    kind = KIND_IMAGE

    def frame_format(self, settings: MediaSettings) -> str:
        return settings.encoding

    def to_message(self, frame: ImageFrame, stamp: Any, settings: MediaSettings) -> Any:
        if frame.fmt != settings.encoding:
            frame = self._convert(frame, settings.encoding)
        msg = msgutil.resolve_type(self.type_name)()
        stamp_header(msg.header, stamp, settings.frame_id)
        msg.height, msg.width = frame.height, frame.width
        msg.encoding = frame.fmt
        msg.is_bigendian = 0
        msg.step = frame.width * BYTES_PER_PIXEL[frame.fmt]
        msg.data = array.array('B', frame.data)
        return msg

    @staticmethod
    def _convert(frame: ImageFrame, fmt: str) -> ImageFrame:
        if not frame.is_raw:
            return imaging.decode(frame.data, fmt)
        rgb = imaging.to_rgb(frame)
        return ImageFrame(frame.width, frame.height, fmt, imaging.convert_raw(rgb, fmt))

    def from_message(self, msg: Any, settings: MediaSettings) -> ImageFrame:
        encoding = msg.encoding
        if encoding not in VIEWABLE_ENCODINGS:
            raise MediaError('viewer_unsupported', f'image encoding {encoding!r} cannot be shown')
        if encoding in ('mono16', '16UC1'):
            return ImageFrame(msg.width, msg.height, 'mono8', _mono16_to_mono8(msg))
        fmt = {'8UC1': 'mono8', '8UC3': 'bgr8'}.get(encoding, encoding)
        row = msg.width * BYTES_PER_PIXEL[fmt]
        data = bytes(msg.data)
        if msg.step != row:  # drop row padding
            data = b''.join(data[y * msg.step:y * msg.step + row] for y in range(msg.height))
        return ImageFrame(msg.width, msg.height, fmt, data)

    def companions(self, topic: str, settings: MediaSettings) -> List[Companion]:
        return camera_info_companion(topic, settings)


class CompressedImageAdapter(MediaAdapter):
    type_name = 'sensor_msgs/msg/CompressedImage'
    kind = KIND_IMAGE

    def frame_format(self, settings: MediaSettings) -> str:
        return settings.format

    def to_message(self, frame: ImageFrame, stamp: Any, settings: MediaSettings) -> Any:
        if frame.is_raw:
            raise MediaError('invalid_media', 'CompressedImage needs a JPEG or PNG frame')
        msg = msgutil.resolve_type(self.type_name)()
        stamp_header(msg.header, stamp, settings.frame_id)
        msg.format = frame.fmt
        msg.data = array.array('B', frame.data)
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> ImageFrame:
        data = bytes(msg.data)
        fmt = imaging.encoded_format(data)
        if fmt is None:
            raise MediaError('viewer_unsupported', f'compressed format {msg.format!r} cannot be '
                             'shown (JPEG / PNG only)')
        width, height = imaging.image_size(data)
        return ImageFrame(width, height, fmt, data)

    def companions(self, topic: str, settings: MediaSettings) -> List[Companion]:
        return camera_info_companion(topic, settings)
