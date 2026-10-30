"""libvlc as the player dock's engine, speaking ``QMediaPlayer``'s language ([[appendices.vlc#python-vlc-events]],
#319)."""

# QMediaPlayer's own method names, so the view calls either engine the same way
# pylint: disable=invalid-name

import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QWidget
from rehuco_core import VlcLibrary

if sys.platform == "win32":
    from borco_pyside.platforms.windows import window_picture
else:  # pragma: no cover  (the other platforms' run)
    window_picture = None  # pylint: disable=invalid-name

INSTANCE_OPTIONS: Final = ("--no-video-title-show", "--no-osd", "--no-snapshot-preview", "--quiet")
"""How the libvlc instance is made: nothing drawn over the picture -- not the file name, not VLC's on-screen messages,
not the thumbnail it shows after each snapshot (a pause takes one) -- and no console noise."""


class VlcEngineError(Exception):
    """libvlc could not be made into a player: the reason is the message."""


# one engine's whole state: the libvlc objects, the surface, the media and what it is known to be doing
# pylint: disable-next=too-many-instance-attributes
class VlcMediaPlayer(QObject):
    """A libvlc media player that answers the calls and emits the signals `PlayerView` makes of a ``QMediaPlayer``,
    with Qt's own enumerations, so the view's state machine does not know which engine it drives.

    **Events cross to the GUI thread through a queued signal**, never a blocking one: libvlc raises each on a thread of
    its own, and ``stop()`` joins that thread, so a blocking connection deadlocks the first stop (#315). Two events are
    raised on the calling thread -- the snapshot's and the stop's -- and the queue is right for those too.

    **The mapping.** ``Opening`` is ``LoadingMedia``; ``Playing`` is ``BufferedMedia`` and ``PlayingState``, the
    moment the view calls a video ready and seeks it; ``Paused`` is ``PausedState``; ``EndReached`` is ``EndOfMedia``
    and, since libvlc then stays *Ended* and ignores ``play()``, a stop is made before any replay;
    ``EncounteredError`` is ``errorOccurred``.

    **A paused load** (:meth:`pause` before anything played) plays muted until the first picture, takes a still of it,
    pauses, and emits :attr:`still_ready`; the view then lets the file go, as it does with a frame from Qt's sink.
    **A pause while playing** keeps the file held, which is the view's business: it takes :meth:`grab_still` and stops.

    :param library: the loaded python-vlc.
    :param surface: the native widget libvlc draws into.
    :param parent: optional Qt parent.
    :raises VlcEngineError: if libvlc gives no instance or no player.
    """

    positionChanged = Signal(int)  # noqa: N815  # QMediaPlayer's names
    durationChanged = Signal(int)  # noqa: N815
    playbackStateChanged = Signal(QMediaPlayer.PlaybackState)  # noqa: N815
    mediaStatusChanged = Signal(QMediaPlayer.MediaStatus)  # noqa: N815
    errorOccurred = Signal(QMediaPlayer.Error, str)  # noqa: N815
    still_ready = Signal(QImage)
    """A paused load has its picture: the frame at the position it was opened at."""

    event_raised = Signal(int, object)
    """A libvlc event, ``(event type, value)``, emitted on libvlc's thread and delivered on this object's. Internal."""

    def __init__(self, library: VlcLibrary, surface: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        module = library.module
        instance = library.instance(*INSTANCE_OPTIONS)
        player = library.media_player(instance)
        if module is None or instance is None or player is None:
            raise VlcEngineError(library.reason or "libvlc gave no player.")
        self.__vlc: Final[Any] = module
        self.__instance: Final[Any] = instance
        self.__player: Final[Any] = player
        self.__surface: Final = surface
        self.__source = QUrl()
        self.__media: Any | None = None
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        self.__status = QMediaPlayer.MediaStatus.NoMedia
        self.__duration_ms = 0
        self.__grabbing = False
        """Whether a paused load is under way: playing muted until the first picture."""
        self.__ended = False
        self.event_raised.connect(self.__on_event, Qt.ConnectionType.QueuedConnection)
        player.video_set_mouse_input(False)
        player.video_set_key_input(False)
        self.__attach_events()

    # region What QMediaPlayer answers

    def setSource(self, url: QUrl) -> None:  # noqa: N802
        """Open a file, or let the one held go.

        :param url: the file's URL, or an empty one to release the file.
        """
        self.__source = url
        if url.isEmpty():
            self.__player.set_media(None)
            self.__media = None
            self.__set_status(QMediaPlayer.MediaStatus.NoMedia)
            return
        self.__media = self.__instance.media_new(url.toLocalFile())
        self.__player.set_media(self.__media)
        self.__ended = False
        self.__duration_ms = 0
        self.__set_status(QMediaPlayer.MediaStatus.LoadingMedia)

    def source(self) -> QUrl:
        """The file opened.

        :returns: its URL, empty when none is.
        """
        return self.__source

    def play(self) -> None:
        """Play the file from where it is, or from the start after its end."""
        if self.__media is None:
            return
        if self.__grabbing:
            self.__grabbing = False
            self.__player.audio_set_mute(False)
            self.__player.set_pause(0)
            return
        if self.__ended:
            self.__player.stop()
            self.__ended = False
        self.__player.audio_set_mute(False)
        self.__player.play()

    def pause(self) -> None:
        """Pause a playing file; before anything played, load it paused: play muted until the first picture."""
        if self.__media is None:
            return
        if self.__state == QMediaPlayer.PlaybackState.PlayingState:
            self.__player.set_pause(1)
            return
        self.__grabbing = True
        self.__player.audio_set_mute(True)
        self.__player.play()

    def stop(self) -> None:
        """Stop, which lets the file go and closes the picture; costs tens of milliseconds on this thread."""
        self.__grabbing = False
        self.__ended = False
        self.__player.stop()
        self.__set_state(QMediaPlayer.PlaybackState.StoppedState)

    def position(self) -> int:
        """Where the file is.

        :returns: the position in milliseconds; 0 when nothing is open.
        """
        return max(int(self.__player.get_time()), 0)

    def setPosition(self, position_ms: int) -> None:  # noqa: N802
        """Move to a position.

        :param position_ms: where, in milliseconds.
        """
        self.__player.set_time(int(position_ms))

    def duration(self) -> int:
        """The file's length.

        :returns: the length in milliseconds; 0 while unknown.
        """
        return self.__duration_ms

    def playbackState(self) -> QMediaPlayer.PlaybackState:  # noqa: N802
        """Whether it plays, is paused or is stopped.

        :returns: the state.
        """
        return self.__state

    def mediaStatus(self) -> QMediaPlayer.MediaStatus:  # noqa: N802
        """Where loading the file got to.

        :returns: the status.
        """
        return self.__status

    def setPlaybackRate(self, rate: float) -> None:  # noqa: N802
        """Play faster or slower.

        :param rate: 1 for the file's own pace.
        """
        self.__player.set_rate(float(rate))

    def setVolume(self, volume: float) -> None:  # noqa: N802
        """Set the volume.

        :param volume: 0 to 1.
        """
        self.__player.audio_set_volume(round(volume * 100))

    def grab_still(self) -> QImage | None:
        """Take the picture shown now, while the file is still held.

        On Windows it is read off the surface's native window in memory (``PrintWindow``, a few milliseconds,
        [[appendices.vlc#python-vlc-events]]); elsewhere, where that was not measured, libvlc's own snapshot is
        written to a temporary file and read back at once.

        :returns: the image, or ``None`` when neither gives one.
        """
        image = window_picture.picture_of(self.__surface) if window_picture is not None else None
        if image is not None:
            return image
        with tempfile.TemporaryDirectory(prefix="rehuco-still-") as scratch:
            path = Path(scratch) / "still.png"
            if self.__player.video_take_snapshot(0, str(path), 0, 0) != 0 or not path.is_file():
                return None
            image = QImage(str(path))
        return None if image.isNull() else image

    # endregion

    # region libvlc's events

    def __attach_events(self) -> None:
        """Have each event libvlc raises re-emitted as :attr:`event_raised`, and give libvlc the surface's window."""
        kinds = self.__vlc.EventType
        for kind in (
            kinds.MediaPlayerOpening,
            kinds.MediaPlayerPlaying,
            kinds.MediaPlayerPaused,
            kinds.MediaPlayerStopped,
            kinds.MediaPlayerEndReached,
            kinds.MediaPlayerEncounteredError,
            kinds.MediaPlayerTimeChanged,
            kinds.MediaPlayerLengthChanged,
            kinds.MediaPlayerVout,
        ):
            self.__player.event_manager().event_attach(kind, self.__relay, self.__number(kind))
        window_id = int(self.__surface.winId())
        if sys.platform == "win32":
            self.__player.set_hwnd(window_id)
        elif sys.platform == "darwin":
            self.__player.set_nsobject(window_id)
        else:
            self.__player.set_xwindow(window_id)

    def __relay(self, event: Any, kind: int) -> None:
        """Re-emit an event; libvlc's thread, so nothing of Qt is touched here but the signal.

        :param event: libvlc's event; its union carries the new time or length.
        :param kind: the event type's number.
        """
        value: object = None
        union = getattr(event, "u", None)
        if kind == self.__number(self.__vlc.EventType.MediaPlayerTimeChanged):
            value = getattr(union, "new_time", None)
        elif kind == self.__number(self.__vlc.EventType.MediaPlayerLengthChanged):
            value = getattr(union, "new_length", None)
        try:
            self.event_raised.emit(kind, value)
        except RuntimeError:  # this object was deleted while libvlc still had a thread going
            pass

    def __on_event(self, kind: int, value: object) -> None:
        """Turn an event into what ``QMediaPlayer`` would have said, on this object's thread.

        :param kind: the event type's number.
        :param value: the new time or length, for the events that carry one.
        """
        kinds = self.__vlc.EventType
        if kind == self.__number(kinds.MediaPlayerOpening):
            self.__set_status(QMediaPlayer.MediaStatus.LoadingMedia)
        elif kind == self.__number(kinds.MediaPlayerPlaying):
            self.__set_state(QMediaPlayer.PlaybackState.PlayingState)
            self.__set_status(QMediaPlayer.MediaStatus.BufferedMedia)
        elif kind == self.__number(kinds.MediaPlayerPaused):
            self.__set_state(QMediaPlayer.PlaybackState.PausedState)
        elif kind == self.__number(kinds.MediaPlayerStopped):
            self.__set_state(QMediaPlayer.PlaybackState.StoppedState)
        elif kind == self.__number(kinds.MediaPlayerEndReached):
            self.__ended = True
            self.__set_state(QMediaPlayer.PlaybackState.StoppedState)
            self.__set_status(QMediaPlayer.MediaStatus.EndOfMedia)
        elif kind == self.__number(kinds.MediaPlayerEncounteredError):
            self.__set_status(QMediaPlayer.MediaStatus.InvalidMedia)
            self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, "VLC could not play it.")
        elif kind == self.__number(kinds.MediaPlayerTimeChanged) and isinstance(value, int):
            self.positionChanged.emit(value)
        elif kind == self.__number(kinds.MediaPlayerLengthChanged) and isinstance(value, int) and value > 0:
            self.__duration_ms = value
            self.durationChanged.emit(value)
        elif kind == self.__number(kinds.MediaPlayerVout) and self.__grabbing:
            self.__finish_grab()

    @staticmethod
    def __number(kind: Any) -> int:
        """The number of an event type: python-vlc's enumeration members carry it in ``value`` and cannot be made
        ``int`` directly (measured against 3.0.21203).

        :param kind: the member.
        :returns: its number.
        """
        return int(kind.value)

    def __finish_grab(self) -> None:
        """A paused load has its first picture: take it, pause, and say so."""
        self.__grabbing = False
        image = self.grab_still()
        self.__player.set_pause(1)
        self.__player.audio_set_mute(False)
        if image is not None:
            self.still_ready.emit(image)

    def __set_state(self, state: QMediaPlayer.PlaybackState) -> None:
        """Change the state, saying so when it changes.

        :param state: the new state.
        """
        if state != self.__state:
            self.__state = state
            self.playbackStateChanged.emit(state)

    def __set_status(self, status: QMediaPlayer.MediaStatus) -> None:
        """Change the status, saying so when it changes.

        :param status: the new status.
        """
        if status != self.__status:
            self.__status = status
            self.mediaStatusChanged.emit(status)

    # endregion
