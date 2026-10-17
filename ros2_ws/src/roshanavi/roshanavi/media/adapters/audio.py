"""Audio adapters: audio_common_msgs (AudioData / AudioDataStamped + AudioInfo)
and std_msgs Int16 / UInt8 / Float32 MultiArray. Payload is PCM S16LE.

AudioInfo naming follows ``audio_capture`` (audio_common 0.4.x for Jazzy): the
capture node publishes ``audio`` (AudioData), ``audio_stamped`` and
``audio_info`` side by side in its namespace, so the default info topic is the
sibling ``audio_info`` of the target topic (``/audio/audio`` ->
``/audio/audio_info``). It is configurable (``audio_info_topic``).
"""

import array
from typing import Any, List

import numpy as np

from ... import msgutil
from ..errors import MediaError
from .base import (KIND_AUDIO, AudioChunk, Companion, MediaAdapter, MediaSettings,
                   sibling_topic, stamp_header)

AUDIO_INFO_TYPE = 'audio_common_msgs/msg/AudioInfo'
AUDIO_INFO_NAME = 'audio_info'
SAMPLE_FORMAT = 'S16LE'
CODING_FORMAT = 'wave'
FLOAT_SCALE = 32768.0


def audio_info_topic(topic: str, settings: MediaSettings) -> str:
    return settings.audio_info_topic or sibling_topic(topic, AUDIO_INFO_NAME)


def build_audio_info(msg_type: type, sample_rate: int, channels: int) -> Any:
    msg = msg_type()
    msg.channels = channels
    msg.sample_rate = sample_rate
    msg.sample_format = SAMPLE_FORMAT
    msg.bitrate = sample_rate * channels * 16
    msg.coding_format = CODING_FORMAT
    return msg


def check_wave(info: Any) -> None:
    """Viewer: refuse AudioInfo streams that are not raw PCM (e.g. audio_capture's mp3)."""
    if info is not None and str(getattr(info, 'coding_format', 'wave')).lower() not in (
            'wave', 'wav', 'pcm', ''):
        raise MediaError('viewer_unsupported', f'audio coded as {info.coding_format!r} cannot '
                         'be shown (PCM / wave only)')


class AudioDataAdapter(MediaAdapter):
    type_name = 'audio_common_msgs/msg/AudioData'
    kind = KIND_AUDIO

    def to_message(self, chunk: AudioChunk, stamp: Any, settings: MediaSettings) -> Any:
        msg = msgutil.resolve_type(self.type_name)()
        msg.data = array.array('B', chunk.data)
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> AudioChunk:
        return AudioChunk(bytes(msg.data), settings.sample_rate, settings.channels)

    def companions(self, topic: str, settings: MediaSettings) -> List[Companion]:
        if not settings.audio_info:
            return []
        info_type = msgutil.resolve_type(AUDIO_INFO_TYPE)

        def build(_stamp: Any, _frame: Any) -> Any:
            return build_audio_info(info_type, settings.sample_rate, settings.channels)
        return [Companion(AUDIO_INFO_TYPE, audio_info_topic(topic, settings), build,
                          every_frame=False, latched=True)]


class AudioDataStampedAdapter(AudioDataAdapter):
    type_name = 'audio_common_msgs/msg/AudioDataStamped'

    def to_message(self, chunk: AudioChunk, stamp: Any, settings: MediaSettings) -> Any:
        msg = msgutil.resolve_type(self.type_name)()
        stamp_header(msg.header, stamp, settings.frame_id)
        msg.audio.data = array.array('B', chunk.data)
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> AudioChunk:
        return AudioChunk(bytes(msg.audio.data), settings.sample_rate, settings.channels)


def _layout(msg: Any, chunk: AudioChunk) -> None:
    """dim[0] = samples per channel, dim[1] = channels (interleaved)."""
    dim_cls = msgutil.resolve_type('std_msgs/msg/MultiArrayDimension')
    samples = dim_cls(label='samples', size=chunk.samples, stride=chunk.samples * chunk.channels)
    channels = dim_cls(label='channels', size=chunk.channels, stride=chunk.channels)
    msg.layout.dim = [samples, channels]


def _layout_channels(msg: Any, fallback: int) -> int:
    dims = list(msg.layout.dim)
    return int(dims[1].size) if len(dims) >= 2 and dims[1].size else fallback


class Int16ArrayAdapter(MediaAdapter):
    type_name = 'std_msgs/msg/Int16MultiArray'
    kind = KIND_AUDIO

    def to_message(self, chunk: AudioChunk, stamp: Any, settings: MediaSettings) -> Any:
        msg = msgutil.resolve_type(self.type_name)()
        _layout(msg, chunk)
        samples = array.array('h')
        samples.frombytes(chunk.data)
        msg.data = samples
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> AudioChunk:
        data = np.asarray(msg.data, dtype='<i2').tobytes()
        return AudioChunk(data, settings.sample_rate, _layout_channels(msg, settings.channels))


class UInt8ArrayAdapter(MediaAdapter):
    """Raw PCM S16LE bytes in a byte array."""

    type_name = 'std_msgs/msg/UInt8MultiArray'
    kind = KIND_AUDIO

    def to_message(self, chunk: AudioChunk, stamp: Any, settings: MediaSettings) -> Any:
        msg = msgutil.resolve_type(self.type_name)()
        _layout(msg, chunk)
        msg.data = array.array('B', chunk.data)
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> AudioChunk:
        data = bytes(msg.data)
        return AudioChunk(data[:len(data) // 2 * 2], settings.sample_rate,
                          _layout_channels(msg, settings.channels))


class Float32ArrayAdapter(MediaAdapter):
    """Samples scaled to [-1, 1)."""

    type_name = 'std_msgs/msg/Float32MultiArray'
    kind = KIND_AUDIO

    def to_message(self, chunk: AudioChunk, stamp: Any, settings: MediaSettings) -> Any:
        msg = msgutil.resolve_type(self.type_name)()
        _layout(msg, chunk)
        pcm = np.frombuffer(chunk.data, dtype='<i2').astype(np.float32) / FLOAT_SCALE
        msg.data = array.array('f', pcm.tobytes())
        return msg

    def from_message(self, msg: Any, settings: MediaSettings) -> AudioChunk:
        values = np.clip(np.asarray(msg.data, dtype=np.float32) * FLOAT_SCALE, -32768, 32767)
        return AudioChunk(values.astype('<i2').tobytes(), settings.sample_rate,
                          _layout_channels(msg, settings.channels))
