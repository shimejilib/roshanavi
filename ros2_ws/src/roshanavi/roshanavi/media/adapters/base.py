"""Adapter contract: media frames <-> ROS messages for one message type.

An adapter converts an :class:`ImageFrame` (raw pixels or an encoded JPEG/PNG)
or an :class:`AudioChunk` (PCM S16LE, interleaved) into a message of its type,
and back for the viewers. Plugins implement the same class and are registered
through the ``roshanavi.adapters`` entry-point group (see ``registry``).
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from ..errors import MediaError

KIND_IMAGE = 'image'
KIND_AUDIO = 'audio'
RAW_IMAGE_FORMATS = ('rgb8', 'bgr8', 'mono8')
ENCODED_IMAGE_FORMATS = ('jpeg', 'png')
BYTES_PER_PIXEL = {'rgb8': 3, 'bgr8': 3, 'mono8': 1, 'rgba8': 4, 'bgra8': 4}


@dataclass(frozen=True)
class ImageFrame:
    """``fmt`` is a raw pixel layout (rgb8/bgr8/mono8) or an encoding (jpeg/png)."""

    width: int
    height: int
    fmt: str
    data: bytes

    @property
    def is_raw(self) -> bool:
        return self.fmt in BYTES_PER_PIXEL


@dataclass(frozen=True)
class AudioChunk:
    """PCM signed 16-bit little endian, channels interleaved."""

    data: bytes
    sample_rate: int
    channels: int

    @property
    def samples(self) -> int:
        """Samples per channel."""
        return len(self.data) // (2 * self.channels)


@dataclass(frozen=True)
class MediaSettings:
    """What adapters need from the user's options (subset of MediaOptions)."""

    frame_id: str = ''
    encoding: str = 'rgb8'      # Image
    format: str = 'jpeg'        # CompressedImage
    sample_rate: int = 16000
    channels: int = 1
    camera_info: bool = True
    camera_info_topic: Optional[str] = None
    calibration: Optional[Any] = None   # parsed CameraInfo fields (camera_info.py)
    audio_info: bool = True
    audio_info_topic: Optional[str] = None


@dataclass(frozen=True)
class Companion:
    """A side message published next to the main one (CameraInfo, AudioInfo).

    ``build(stamp, frame)`` returns the message; ``every_frame`` sends it with
    each frame (CameraInfo), otherwise once at start and then periodically.
    """

    type_name: str
    topic: str
    build: Callable[[Any, Any], Any]
    every_frame: bool = True
    latched: bool = False


class MediaAdapter:
    """Base class. Subclasses set ``type_name`` and ``kind`` and implement the methods."""

    type_name: str = ''
    kind: str = KIND_IMAGE

    def frame_format(self, settings: MediaSettings) -> str:
        """Image adapters: the frame format to request from the source."""
        return 'rgb8'

    def to_message(self, frame: Any, stamp: Any, settings: MediaSettings) -> Any:
        raise NotImplementedError

    def from_message(self, msg: Any, settings: MediaSettings) -> Any:
        """Viewer side: message -> ImageFrame / AudioChunk."""
        raise MediaError('viewer_unsupported', f'{self.type_name} cannot be shown')

    def companions(self, topic: str, settings: MediaSettings) -> List[Companion]:
        return []


def sibling_topic(topic: str, name: str) -> str:
    """``/cam/image_raw`` + ``camera_info`` -> ``/cam/camera_info`` (same namespace)."""
    parent = topic.rsplit('/', 1)[0]
    return f'{parent}/{name}'


def stamp_header(header: Any, stamp: Any, frame_id: str) -> None:
    header.stamp = stamp
    header.frame_id = frame_id
