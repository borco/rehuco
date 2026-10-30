"""libvlc as the player dock's engine, speaking ``QMediaPlayer``'s language ([[appendices.vlc#python-vlc-events]],
#319)."""

# QMediaPlayer's own method names, so the view calls either engine the same way
# pylint: disable=invalid-name

import ctypes
from typing import Any, Final

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from rehuco_core import VlcLibrary

from .vlc_frame_sink import CHROMA, VlcFrameSink
from .vlc_surface import VlcSurface

INSTANCE_OPTIONS: Final = ("--no-video-title-show", "--no-osd", "--quiet")
"""How the libvlc instance is made: nothing drawn into the frames but the video and its subtitles -- not the file
name, not VLC's on-screen messages -- and no console noise."""

FORMAT_CALLBACK: Final = ctypes.CFUNCTYPE(
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_char),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
)
"""``libvlc_video_format_cb`` with the chroma as a writable buffer: python-vlc's own prototype declares it
``c_char_p``, which ctypes hands over as copied bytes, so the chroma could not be set through it (measured). The
callback is cast to python-vlc's type where it is passed."""


class VlcEngineError(Exception):
    """libvlc could not be made into a player: the reason is the message."""


# one engine's whole state: the libvlc objects, its callbacks, the media and what it is known to be doing
# pylint: disable-next=too-many-instance-attributes
class VlcMediaPlayer(QObject):
    """A libvlc media player that answers the calls and emits the signals `PlayerView` makes of a ``QMediaPlayer``,
    with Qt's own enumerations, so the view's state machine does not know which engine it drives.

    **libvlc renders into memory** ([[appendices.vlc#memory-rendering]]): it decodes into a buffer of this process's
    (:class:`VlcFrameSink`) and each frame is painted by an ordinary widget (:class:`VlcSurface`), so there is no
    native window, anything may be drawn over the picture, the still of a paused video is simply the last frame, and
    the engine is the same on every OS. Audio, the clock the frames are timed by, and subtitles stay libvlc's;
    subtitles arrive blended into the frames.

    **Events cross to the GUI thread through a queued signal**, never a blocking one: libvlc raises each on a thread of
    its own, and ``stop()`` joins that thread, so a blocking connection deadlocks the first stop (#315). The frames
    cross the same way.

    **The mapping.** ``Opening`` is ``LoadingMedia``; ``Playing`` is ``BufferedMedia`` and ``PlayingState``, the
    moment the view calls a video ready and seeks it; ``Paused`` is ``PausedState``; ``EndReached`` is ``EndOfMedia``
    and, since libvlc then stays *Ended* and ignores ``play()``, a stop is made before any replay;
    ``EncounteredError`` is ``errorOccurred``.

    **A paused load** (:meth:`pause` before anything played) plays muted until the first frame, pauses, and emits
    :attr:`still_ready` with it; the view then lets the file go, as it does with a frame from Qt's sink. **A pause
    while playing** keeps the file held, which is the view's business: it takes :meth:`grab_still` and stops.

    :param library: the loaded python-vlc.
    :param surface: the widget the frames are painted on.
    :param parent: optional Qt parent.
    :raises VlcEngineError: if libvlc gives no instance or no player.
    """

    positionChanged = Signal(int)  # noqa: N815  # QMediaPlayer's names
    durationChanged = Signal(int)  # noqa: N815
    playbackStateChanged = Signal(QMediaPlayer.PlaybackState)  # noqa: N815
    mediaStatusChanged = Signal(QMediaPlayer.MediaStatus)  # noqa: N815
    errorOccurred = Signal(QMediaPlayer.Error, str)  # noqa: N815
    still_ready = Signal(QImage)
    """A paused load has its picture: the first frame at the position it was opened at."""

    event_raised = Signal(int, object)
    """A libvlc event, ``(event type, value)``, emitted on libvlc's thread and delivered on this object's. Internal."""

    def __init__(self, library: VlcLibrary, surface: VlcSurface, parent: QObject | None = None) -> None:
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
        self.__sink: Final = VlcFrameSink(self)
        self.__source = QUrl()
        self.__media: Any | None = None
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        self.__status = QMediaPlayer.MediaStatus.NoMedia
        self.__duration_ms = 0
        self.__visible: tuple[int, int] | None = None
        """The video's visible size, read once it plays; the decoder's buffer is padded past it."""
        self.__grabbing = False
        """Whether a paused load is under way: playing muted until the first frame."""
        self.__ended = False
        self.event_raised.connect(self.__on_event, Qt.ConnectionType.QueuedConnection)
        self.__sink.frame_ready.connect(self.__on_frame, Qt.ConnectionType.QueuedConnection)
        # kept on the object: ctypes callbacks live exactly as long as their Python references
        self.callbacks: Final = self.__make_callbacks()
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
        self.__visible = None
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
        """Pause a playing file; before anything played, load it paused: play muted until the first frame."""
        if self.__media is None:
            return
        if self.__state == QMediaPlayer.PlaybackState.PlayingState:
            self.__player.set_pause(1)
            return
        self.__grabbing = True
        self.__player.audio_set_mute(True)
        self.__player.play()

    def stop(self) -> None:
        """Stop, which lets the file go, and show nothing; costs tens of milliseconds on this thread."""
        self.__grabbing = False
        self.__ended = False
        self.__player.stop()
        self.__surface.set_frame(None)
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
        """The picture shown now: the frame painted last.

        :returns: the image, or ``None`` when no frame has arrived.
        """
        return self.__surface.frame

    # endregion

    # region libvlc's callbacks and events

    def __make_callbacks(self) -> tuple[Any, ...]:
        """Give libvlc the sink's three moments and the format, as ctypes callbacks it holds by address.

        :returns: every callback object made, so they stay referenced for as long as this player (``callbacks``).
        """
        decorators = self.__vlc.CallbackDecorators
        sink = self.__sink

        def setup(_opaque: Any, chroma: Any, width: Any, height: Any, pitches: Any, lines: Any) -> int:
            """Choose the chroma and allocate for the decoder's picture size; one picture in the pool."""
            pitch, line_count = sink.setup(int(width[0]), int(height[0]))
            ctypes.memmove(chroma, CHROMA, len(CHROMA))
            pitches[0] = pitch
            lines[0] = line_count
            return 1

        def lock(_opaque: Any, planes: Any) -> None:
            """Point libvlc at the buffer."""
            planes[0] = sink.lock()

        def unlock(_opaque: Any, _picture: Any, _planes: Any) -> None:
            """Nothing to do: the frame is read when it is displayed."""

        def display(_opaque: Any, _picture: Any) -> None:
            """The frame is due."""
            sink.display()

        def cleanup(_opaque: Any) -> None:
            """The video is over."""
            sink.cleanup()

        setup_cb = FORMAT_CALLBACK(setup)
        lock_cb = decorators.VideoLockCb(lock)
        unlock_cb = decorators.VideoUnlockCb(unlock)
        display_cb = decorators.VideoDisplayCb(display)
        cleanup_cb = decorators.VideoCleanupCb(cleanup)
        self.__player.video_set_callbacks(lock_cb, unlock_cb, display_cb, None)
        self.__player.video_set_format_callbacks(ctypes.cast(setup_cb, decorators.VideoFormatCb), cleanup_cb)
        return setup_cb, lock_cb, unlock_cb, display_cb, cleanup_cb

    def __attach_events(self) -> None:
        """Have each event libvlc raises re-emitted as :attr:`event_raised`."""
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
        ):
            self.__player.event_manager().event_attach(kind, self.__relay, self.__number(kind))

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

    def __on_frame(self, frame: QImage) -> None:
        """Show a frame, cropped to the video's visible size, and end a paused load on its first one.

        :param frame: the frame, at the decoder's padded size.
        """
        if self.__visible is None:
            width, height = self.__player.video_get_size(0)
            if width > 0 and height > 0:
                self.__visible = (int(width), int(height))
        if self.__visible is not None and (frame.width(), frame.height()) != self.__visible:
            frame = frame.copy(0, 0, *self.__visible)
        self.__surface.set_frame(frame)
        if self.__grabbing:
            self.__grabbing = False
            self.__player.set_pause(1)
            self.__player.audio_set_mute(False)
            self.still_ready.emit(frame)

    @staticmethod
    def __number(kind: Any) -> int:
        """The number of an event type: python-vlc's enumeration members carry it in ``value`` and cannot be made
        ``int`` directly (measured against 3.0.21203).

        :param kind: the member.
        :returns: its number.
        """
        return int(kind.value)

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
