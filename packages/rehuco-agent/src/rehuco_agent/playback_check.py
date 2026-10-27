"""The release build's playback smoke test: play one short clip through Qt Multimedia and say whether it was seen
([[packaging-deployment#qt-multimedia]], #317).

A bundle whose ``PySide6-Addons`` was pruned too far builds, installs and starts, and fails only when a reader double-
clicks a video. ``rehuco-agent --check-playback CLIP`` is what the release workflow runs on the built bundle, beside
``--version``: it imports Qt Multimedia from the bundle, loads the FFmpeg backend, decodes the clip and exits 0 only if
a picture arrived and the position moved.
"""

import os
import sys
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink

TIMEOUT_MS: Final = 10_000
"""How long the clip has to show a frame and move: a cold start loads FFmpeg and, on a runner, may find no hardware
to decode with."""


class PlaybackCheck(QObject):
    """Plays a clip into a video sink, with no window and no sound, until a picture has arrived and the position has
    moved, or something says it cannot.

    Succeeds as soon as both are seen, rather than at the clip's end: that is what shows the bundle can decode.

    :param clip: the video to play.
    :param timeout_ms: how long it has to do so.
    :param parent: optional Qt parent.
    """

    finished = Signal(int)
    """Emitted once with the exit status: 0 when the clip played, 1 when it did not."""

    def __init__(self, clip: Path, timeout_ms: int = TIMEOUT_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__clip: Final = clip
        self.__frames = 0
        self.__moved = False
        self.__done = False
        self.__player: Final = QMediaPlayer(self)
        self.__sink: Final = QVideoSink(self)
        self.__player.setVideoSink(self.__sink)
        self.__sink.videoFrameChanged.connect(self.__on_frame)
        self.__player.positionChanged.connect(self.__on_position)
        self.__player.errorOccurred.connect(self.__on_error)
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(timeout_ms)
        self.__timer.timeout.connect(self.__on_timeout)

    def start(self) -> None:
        """Start the clip, and the clock it has to be seen within."""
        self.__timer.start()
        self.__player.setSource(QUrl.fromLocalFile(str(self.__clip)))
        self.__player.play()

    def __on_frame(self, frame: QVideoFrame) -> None:
        """Count a picture that arrived.

        :param frame: what the sink was given.
        """
        if frame.isValid():
            self.__frames += 1
            self.__settle()

    def __on_position(self, position_ms: int) -> None:
        """Note that the clip moved.

        :param position_ms: where playback is.
        """
        if position_ms > 0:
            self.__moved = True
            self.__settle()

    def __settle(self) -> None:
        """Succeed once a picture has arrived and the clip has moved."""
        if self.__frames and self.__moved:
            self.__finish(0, f"played {self.__clip.name}: {self.__frames} frames")

    def __on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        """Fail with Qt's own account.

        :param _error: the kind of error.
        :param message: Qt's description of it.
        """
        self.__finish(1, f"could not play {self.__clip.name}: {message}")

    def __on_timeout(self) -> None:
        """Fail with what had been seen, which says whether it was the picture or the clock that never came."""
        self.__finish(
            1, f"no playback of {self.__clip.name} in time: {self.__frames} frames, position moved: {self.__moved}"
        )

    def __finish(self, status: int, message: str) -> None:
        """Say how it went, once.

        :param status: the exit status.
        :param message: what to print.
        """
        if self.__done:
            return
        self.__done = True
        self.__timer.stop()
        self.__player.stop()
        # nowhere at all in a packaged GUI-subsystem build on Windows, where the exit status is all there is
        print(message, file=sys.stderr if status else sys.stdout)
        self.finished.emit(status)


def check_playback(clip: Path, timeout_ms: int = TIMEOUT_MS) -> int:
    """Play ``clip`` and report whether Qt Multimedia, as this build ships it, could.

    Offscreen, so a runner with no display needs none; the platform is only a default, so a developer can see a window
    by setting it.

    :param clip: the video to play.
    :param timeout_ms: how long it has to show a frame and move.
    :returns: the exit status: 0 when it played, 1 when it did not.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    check = PlaybackCheck(clip, timeout_ms, application)
    status: list[int] = []
    loop = QEventLoop(check)
    check.finished.connect(status.append)
    check.finished.connect(loop.quit)
    QTimer.singleShot(0, check.start)
    loop.exec()
    return status[0]
