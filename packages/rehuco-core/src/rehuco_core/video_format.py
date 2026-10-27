"""What a player needs to know about a video before it plays it: its codec and whether it is interlaced
([[plugins#in-app-player]], #317).

Qt Multimedia has two gaps a player explains rather than shows: AV1 on a machine with no AV1 decoding hardware plays
sound with no picture, and interlaced video is shown combed. Neither can be asked of Qt beforehand, so the file is
asked. Read through the bundled MediaInfo library the duration probe already uses, and never stored: the answer is
about the file as it is now.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pymediainfo import MediaInfo

INTERLACED_SCAN_TYPES: Final = frozenset({"interlaced", "mbaff", "mixed"})
"""MediaInfo's ``scan_type`` values (lower-cased) for video whose fields come from different instants: ``Interlaced``,
``MBAFF`` (an H.264 stream interlaced per macroblock pair) and ``Mixed``."""

AV1_FORMAT: Final = "av1"
"""MediaInfo's ``format`` for AV1 (lower-cased)."""


@dataclass(frozen=True)
class VideoFormat:
    """The two facts about a video's picture that decide whether Qt Multimedia shows it well."""

    codec: str | None
    """MediaInfo's name for the codec (``AV1``, ``AVC``, ``HEVC``), or ``None`` when it names none."""

    interlaced: bool
    """Whether the picture is interlaced, in whole or in part."""

    @property
    def is_av1(self) -> bool:
        """Whether the codec is AV1, which Qt decodes in hardware only."""
        return self.codec is not None and self.codec.lower() == AV1_FORMAT


def read_video_format(path: Path) -> VideoFormat | None:
    """Read ``path``'s codec and scan type out of its first Video track.

    :param path: the video file.
    :returns: its format, or ``None`` when the file cannot be read or carries no video track.
    """
    try:
        media_info = MediaInfo.parse(path)
    except Exception:  # pylint: disable=broad-exception-caught
        # pymediainfo raises whatever the library and the ctypes layer under it raise (see MediaInfoDurationProbe): to
        # a player every one of them means it knows nothing about the file, and plays it without a notice
        return None
    video = next((track for track in media_info.tracks if track.track_type == "Video"), None)
    if video is None:
        return None
    codec = getattr(video, "format", None)
    scan_type = getattr(video, "scan_type", None)
    return VideoFormat(
        codec if isinstance(codec, str) and codec else None,
        isinstance(scan_type, str) and scan_type.lower() in INTERLACED_SCAN_TYPES,
    )
