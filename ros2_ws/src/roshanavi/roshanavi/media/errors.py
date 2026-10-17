"""Media error with a machine readable code (rendered by the API error envelope)."""


class MediaError(ValueError):
    """``code`` examples: ffmpeg_missing, invalid_media, forbidden_media,
    media_type_unsupported, media_type_required, capture_busy, recording_active."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status
