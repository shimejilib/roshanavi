"""File extension -> media kind and forced ffmpeg demuxer (no dependencies)."""

import os
from typing import Dict, Optional

IMAGE_DEMUXERS: Dict[str, str] = {'.png': 'png_pipe', '.jpg': 'jpeg_pipe', '.jpeg': 'jpeg_pipe',
                                  '.bmp': 'bmp_pipe', '.webp': 'webp_pipe'}
VIDEO_DEMUXERS: Dict[str, str] = {'.mp4': 'mov', '.mov': 'mov', '.m4v': 'mov',
                                  '.mkv': 'matroska', '.webm': 'matroska', '.avi': 'avi'}
AUDIO_DEMUXERS: Dict[str, str] = {'.wav': 'wav', '.mp3': 'mp3', '.flac': 'flac', '.ogg': 'ogg',
                                  '.oga': 'ogg', '.m4a': 'mov'}
KIND_DEMUXERS = {'image': IMAGE_DEMUXERS, 'video': VIDEO_DEMUXERS, 'audio': AUDIO_DEMUXERS}


def media_kind(path: str) -> Optional[str]:
    """'image' / 'video' / 'audio' from the extension, or None."""
    ext = os.path.splitext(path)[1].lower()
    for kind, table in KIND_DEMUXERS.items():
        if ext in table:
            return kind
    return None
