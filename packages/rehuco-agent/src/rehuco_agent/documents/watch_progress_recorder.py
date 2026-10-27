"""How often a player's position reaches the record (#316, [[field-schema#watch-progress]])."""

from typing import Final

from PySide6.QtCore import QObject, QTimer

from .rehu_document_model import RehuDocumentModel

WRITE_INTERVAL_MS: Final = 5000
"""How long a playing video's position waits before it is written: about every five seconds
([[mounts-and-storage#node-handoff]]), so a node taking over a viewing loses seconds, and a share is not written to
on every tick."""


class WatchProgressRecorder(QObject):
    """Collects a player's positions and writes them to the document's model at a steady pace.

    A player calls :meth:`position` as often as it likes while a video plays: the latest is kept and written once per
    :data:`WRITE_INTERVAL_MS`. At every other moment that matters -- pause, stop, seek, switching video, closing the
    player, closing the document -- it calls :meth:`flush`, which writes at once what is waiting. Both players, the
    in-app one and the external VLC, record through this and neither owns it ([[plugins#tutorial-plugin]]).

    The write itself is :meth:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.record_progress`'s, off the
    GUI thread, so a flush never waits for a share.

    :param model: the document the progress is recorded on.
    :param parent: optional Qt parent.
    :param interval_ms: how long a position waits to be written.
    """

    def __init__(
        self, model: RehuDocumentModel, parent: QObject | None = None, interval_ms: int = WRITE_INTERVAL_MS
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__pending: tuple[str, float, float | None] | None = None
        """The latest position not written yet: the video's content key, the position and the length the player saw."""
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(interval_ms)
        self.__timer.timeout.connect(self.flush)

    def position(self, relative: str, position: float, duration: float | None) -> None:
        """Note where a video is now; written within one interval, or sooner by :meth:`flush`.

        A position for another video than the one waiting writes that one first, so no video's last position is lost
        to a player that moved on without flushing.

        :param relative: the video's content key.
        :param position: where playback is, in seconds.
        :param duration: the length the player saw, or ``None`` when it does not know.
        """
        if self.__pending is not None and self.__pending[0] != relative:
            self.flush()
        self.__pending = (relative, position, duration)
        if not self.__timer.isActive():
            self.__timer.start()

    def flush(self) -> None:
        """Write the position waiting, if any, now."""
        self.__timer.stop()
        pending, self.__pending = self.__pending, None
        if pending is not None:
            self.__model.record_progress(*pending)
