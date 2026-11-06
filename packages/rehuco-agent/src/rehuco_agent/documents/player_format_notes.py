"""What the player explains about a video Qt shows badly ([[plugins#in-app-player]], #317)."""

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, QTimer
from rehuco_core import VideoFormat, read_video_format

from .latest_runner import LatestRunner
from .player_notices import PlayerNotices

NO_FRAME_MS: Final = 1500
"""How long an AV1 video may play without showing a frame before the player says why: Qt decodes AV1 in hardware only,
and a machine without it plays the sound with no picture and no error."""

INTERLACED_NOTICE: Final = (
    "This video is interlaced, and this player shows it without deinterlacing: moving edges look combed."
)


class PlayerFormatNotes(QObject):  # pylint: disable=too-many-instance-attributes  # one wait's whole state
    """Explains what Qt cannot show well about the video selected.

    Qt shows interlaced video combed, and plays AV1 with sound and no picture where the graphics hardware has no AV1
    decoder, raising no error. The file's codec and scan type are read off the GUI thread; an interlaced file is noted
    at once, an AV1 one when no frame has shown within :data:`NO_FRAME_MS` of playing. libvlc deinterlaces and decodes
    AV1 in software, so neither is said under it.

    :param notices: where the notes are said.
    :param no_frame_ms: how long an AV1 video may show no frame before the notice.
    :param plays: whether the video plays now, asked when the wait runs out.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(self, notices: PlayerNotices, no_frame_ms: int, plays: Callable[[], bool], parent: QObject) -> None:
        super().__init__(parent)
        self.__notices: Final = notices
        self.__plays: Final = plays
        self.__key: str | None = None
        self.__explains = False
        self.__armed = False
        """Whether the video has started to play, so an AV1 one's wait for a frame runs."""
        self.__frame_seen = False
        self.__av1 = False
        self.__runner: Final = LatestRunner(self)
        self.__runner.setObjectName("format_runner")
        self.__runner.read.connect(self.__on_read)
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(no_frame_ms)
        self.__timer.timeout.connect(self.__on_no_frame)

    def select(self, key: str, path: Path, *, explains: bool) -> None:
        """Start over on a video just selected, and read its format.

        :param key: the video's content key.
        :param path: its file.
        :param explains: whether its engine is one this explains: Qt, not libvlc.
        """
        self.__key = key
        self.__explains = explains
        self.__armed = False
        self.__frame_seen = False
        self.__av1 = False
        self.__timer.stop()
        self.__runner.start(key, partial(read_video_format, path))

    def stop(self) -> None:
        """Say nothing more: the player stopped showing a video."""
        self.__runner.discard()
        self.__timer.stop()

    def arm(self) -> None:
        """Start waiting for a picture, now the video plays and has buffered."""
        self.__armed = True
        if self.__av1 and not self.__frame_seen:
            self.__timer.start()

    def disarm(self) -> None:
        """Stop waiting for a picture: the video no longer plays, and a format read meanwhile arms nothing."""
        self.__armed = False
        self.__timer.stop()

    def frame_seen(self) -> None:
        """Take a frame of the video playing as proof it is no silent one."""
        self.__frame_seen = True
        self.__timer.stop()

    def __on_no_frame(self) -> None:
        """Say why an AV1 video that plays shows nothing."""
        if not self.__frame_seen and self.__plays():
            self.__notices.add_av1()

    def __on_read(self, key: str, result: object) -> None:
        """Explain what Qt cannot show well about the video, once its format is known.

        :param key: the video the format is of.
        :param result: its format, or ``None``, or the error reading it ended in -- the file could not be read.
        """
        if key != self.__key or not isinstance(result, VideoFormat) or not self.__explains:
            return
        if result.interlaced:
            self.__notices.add(INTERLACED_NOTICE)
        self.__av1 = result.is_av1
        if self.__armed:
            self.arm()
