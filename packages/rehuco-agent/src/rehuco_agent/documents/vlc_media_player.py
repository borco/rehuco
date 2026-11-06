"""libvlc as the player dock's engine, speaking ``QMediaPlayer``'s language ([[appendices.vlc#python-vlc-events]],
#319)."""

# QMediaPlayer's own method names, so the view calls either engine the same way
# pylint: disable=invalid-name

import ctypes
from typing import Any, Final

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from rehuco_core import (
    SubtitleChoice,
    SubtitlePreferences,
    SubtitleTrack,
    VlcLibrary,
    remembered_track,
    subtitle_cycle,
    subtitle_entries,
    subtitle_index,
    subtitle_labels,
)

from .vlc_frame_sink import CHROMA, VlcFrameSink
from .vlc_surface import VlcSurface

INSTANCE_OPTIONS: Final = ("--no-video-title-show", "--no-osd", "--quiet")
"""How the libvlc instance is made: nothing drawn into the frames but the video and its subtitles -- not the file
name, not VLC's on-screen messages -- and no console noise."""

SUBTITLES_OFF: Final = -1
"""libvlc's id for no subtitle track: ``video_set_spu`` with it hides them, and its track list names it first."""

NO_SUBTITLES_LABEL: Final = "Subs: none"
"""The one entry of the subtitle menu for a video libvlc lists no subtitle for, once it has been waited on."""

SUBTITLE_POLL_MS: Final = 250
"""How often the subtitle tracks libvlc lists are read while waiting for the list to settle: it is empty for seconds
after a video starts (measured), and a sidecar file's tracks come after the video's own."""

SUBTITLE_POLL_LIMIT: Final = 40
"""How many reads are made before a video with no subtitles is given up on."""

SEEK_TOLERANCE_MS: Final = 1000
"""How far from the position a paused load was asked to start at its first frame may be and still be its still."""

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

    **Events and frames cross to the GUI thread through queued signals**, never blocking ones: libvlc raises each on a
    thread of its own, and ``stop()`` joins that thread, so a blocking connection deadlocks the first stop (#315).
    Each carries the **epoch** of the source it belongs to, and one queued behind a :meth:`setSource` or :meth:`stop`
    is dropped on arrival, so a frame or an end of the video just left is never taken for the next video's.

    **The mapping.** ``Opening`` is ``LoadingMedia``; ``Playing`` is ``BufferedMedia`` and ``PlayingState``, the
    moment the view calls a video ready and seeks it; ``Paused`` is ``PausedState``; ``EndReached`` is ``EndOfMedia``
    and, since libvlc then stays *Ended* and ignores ``play()``, a stop is made before any replay;
    ``EncounteredError`` is ``errorOccurred``.

    **A paused load** (:meth:`pause` before anything played) opens the file with ``:no-audio`` -- libvlc then decodes
    no audio track at all (measured) -- and plays until the first frame **at the position asked for** (the first picture
    libvlc decodes is the file's start, ahead of the seek the view makes as the video buffers), then pauses and emits
    :attr:`still_ready` with it; the view then lets the file go, as it does with a frame from Qt's sink. Played before
    that, the file is opened again with its audio, at the position (``:start-time``). **Nothing is ever muted**: libvlc
    takes a mute or an unmute only while its audio output lives, so a load muted around it let a blip, then seconds,
    of sound out at the start, and an unmute after the view's stop was lost and left the next video silent (owner,
    measured: #574). **A pause while playing** keeps the file held, which is the view's business.

    **libvlc's objects are released** by :meth:`close`: the media each time another replaces it, and the player and the
    instance when the view lets the engine go; the event callbacks are attached to one event manager kept for as long
    as the engine, since python-vlc hands out a new wrapper per call and the callback lives with the wrapper.

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

    still_refreshed = Signal(QImage)
    """A subtitle change made while paused has its picture: the frame at the same position, with the subtitle as it is
    now (libvlc draws none on a paused picture until the position is sought again, measured)."""

    subtitle_chosen = Signal(object)
    """The reader chose a subtitle track, or none, with a key: the :class:`~rehuco_core.SubtitleChoice` that says so."""

    subtitle_menu_changed = Signal(object, int, int)
    """The entries of the subtitle menu (:func:`~rehuco_core.subtitle_labels`), which of them is on, and how many of the
    tracks after *none* the keys visit -- the rest are the video's others, which the reader may still pick -- as they
    are set or applied; no entries while libvlc has not listed them, and :data:`NO_SUBTITLES_LABEL` alone for a video it
    listed none for. A silent stretch of a video shows nothing, so this
    is how the reader tells a track was set."""

    event_raised = Signal(int, object, int)
    """A libvlc event, ``(event type, value, epoch)``, emitted on libvlc's thread and delivered on this object's.
    Internal."""

    def __init__(
        self,
        library: VlcLibrary,
        surface: VlcSurface,
        parent: QObject | None = None,
        *,
        subtitle_poll_ms: int = SUBTITLE_POLL_MS,
    ) -> None:
        super().__init__(parent)
        module = library.module
        instance = library.instance(*INSTANCE_OPTIONS)
        player = library.media_player(instance)
        if module is None or instance is None or player is None:
            raise VlcEngineError(library.reason or "libvlc gave no player.")
        self.__vlc: Final[Any] = module
        self.__instance: Final[Any] = instance
        self.__player: Final[Any] = player
        self.__events: Final[Any] = player.event_manager()
        """The one event manager wrapper, kept: python-vlc keeps a callback alive through the wrapper it was attached
        on."""
        self.__surface: Final = surface
        self.__sink: Final = VlcFrameSink(self)
        self.__source = QUrl()
        self.__media: Any | None = None
        self.__epoch = 0
        """Counts the sources set and the stops made; what crosses the threads is stamped with it."""
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        self.__status = QMediaPlayer.MediaStatus.NoMedia
        self.__duration_ms = 0
        self.__visible: tuple[int, int] | None = None
        """The video's visible size, read once it plays; the decoder's buffer is padded past it."""
        self.__grabbing = False
        """Whether a paused load is under way: playing, without audio, until the first frame at the position asked
        for."""
        self.__wanted_ms: int | None = None
        """The position a paused load was seeked to, which its still must be at; ``None`` when none was asked."""
        self.__ended = False
        self.__refreshing = False
        """Whether a subtitle change made while paused awaits the frame that shows it."""
        self.__preferences = SubtitlePreferences((), show_all=True)
        self.__choice = SubtitleChoice(shown=False)
        """What the reader wants of the subtitles: given by the owner, and changed by the keys."""
        self.__ring: list[SubtitleTrack | None] = []
        """The entries the subtitle menu offers last: none, then the tracks the keys visit."""
        self.__listed: list[SubtitleTrack] = []
        """The tracks libvlc listed at the last read, which the next read compares with."""
        self.__polls = 0
        self.__subtitle_timer: Final = QTimer(self)
        self.__subtitle_timer.setInterval(subtitle_poll_ms)
        self.__subtitle_timer.timeout.connect(self.__poll_subtitles)
        self.__closed = False
        self.event_raised.connect(self.__on_event, Qt.ConnectionType.QueuedConnection)
        self.__sink.frame_ready.connect(self.__on_frame, Qt.ConnectionType.QueuedConnection)
        # kept on the object and never read: ctypes callbacks live exactly as long as their Python references
        self.__callbacks: Final = self.__make_callbacks()  # pylint: disable=unused-private-member
        self.__attach_events()

    # region What QMediaPlayer answers

    def setSource(self, url: QUrl) -> None:  # noqa: N802
        """Open a file, or let the one held go; what the file before it still has queued is dropped.

        :param url: the file's URL, or an empty one to release the file.
        """
        self.__epoch += 1
        self.__sink.epoch = self.__epoch
        self.__source = url
        self.__grabbing = False
        self.__wanted_ms = None
        self.__ended = False
        self.__refreshing = False
        self.__subtitle_timer.stop()
        self.__announce([], None)
        if url.isEmpty():
            self.__player.set_media(None)
            self.__release_media()
            self.__set_status(QMediaPlayer.MediaStatus.NoMedia)
            return
        self.__open_media()
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
            # opened without audio for its still: opened again with it, where the load had got to
            self.__grabbing = False
            start_ms = self.__wanted_ms if self.__wanted_ms is not None else self.position()
            self.__wanted_ms = None
            self.__epoch += 1
            self.__sink.epoch = self.__epoch
            self.__open_media(f":start-time={start_ms / 1000:.3f}")
            self.__player.play()
            return
        if self.__ended:
            self.__player.stop()
            self.__ended = False
        self.__player.play()

    def pause(self) -> None:
        """Pause a playing file; before anything played, load it paused: play it without audio until the first frame.

        libvlc itself is asked whether it plays, not the state that queued events have reached, so a pause right after
        a resume pauses rather than starting a muted load.
        """
        if self.__media is None:
            return
        if self.__grabbing:
            # a paused load is a pause already: paused half-way, it would give no still
            return
        if self.__state == QMediaPlayer.PlaybackState.PlayingState or self.__player.is_playing():
            self.__player.set_pause(1)
            return
        self.__grabbing = True
        self.__wanted_ms = None
        self.__open_media(":no-audio")
        self.__player.play()

    def stop(self) -> None:
        """Stop, which lets the file go, and show nothing; costs tens of milliseconds on this thread."""
        self.__epoch += 1
        self.__sink.epoch = self.__epoch
        self.__grabbing = False
        self.__wanted_ms = None
        self.__ended = False
        self.__refreshing = False
        self.__subtitle_timer.stop()
        self.__announce([], None)
        self.__player.stop()
        self.__surface.set_frame(None)
        self.__set_state(QMediaPlayer.PlaybackState.StoppedState)

    def position(self) -> int:
        """Where the file is.

        :returns: the position in milliseconds; 0 when nothing is open.
        """
        return max(int(self.__player.get_time()), 0)

    def setPosition(self, position_ms: int) -> None:  # noqa: N802
        """Move to a position; during a paused load, the position its still must be at.

        :param position_ms: where, in milliseconds.
        """
        if self.__grabbing:
            self.__wanted_ms = int(position_ms)
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

    def set_subtitle_preferences(self, preferences: SubtitlePreferences) -> None:
        """Say which languages the keys visit, and in what order.

        :param preferences: the user's list.
        """
        self.__preferences = preferences

    def set_subtitle_choice(self, choice: SubtitleChoice) -> None:
        """Say what the reader wants of the subtitles of the videos to come: it is applied to the next video once
        libvlc has listed its tracks, and to the one open if that has not happened yet.

        :param choice: on or off, and the track they are shown as.
        """
        self.__choice = choice

    def next_subtitle(self) -> None:
        """Show the next track of the cycle; after the last, none, and after none, the first. Nothing when the video
        has no track the cycle visits."""
        self.__step_subtitle(1)

    def previous_subtitle(self) -> None:
        """Show the previous track of the cycle, which :meth:`next_subtitle` walks the other way."""
        self.__step_subtitle(-1)

    def select_subtitle(self, index: int) -> None:
        """Show the entry the reader picked in the subtitle menu, as the key that reaches it would.

        :param index: the entry's position in the last menu announced (:attr:`subtitle_menu_changed`); one outside it,
            as a menu that has since been emptied may hand back, is ignored.
        """
        if 0 <= index < len(self.__ring):
            target = self.__ring[index]
            self.__choose(self.__subtitle_tracks(), target, self.__choice_of(target))

    def toggle_subtitles(self) -> None:
        """Hide the subtitles, or show again the track shown last, which is the cycle's first when none was or the
        subtitles were last turned off by cycling to none. Nothing when the video has no track the cycle visits."""
        tracks = self.__subtitle_tracks()
        cycle = subtitle_cycle(tracks, self.__preferences)
        if not cycle:
            return
        current = self.__current_subtitle(tracks)
        if current is not None:
            self.__choose(tracks, None, SubtitleChoice.of_track(current, shown=False))
        else:
            target = remembered_track(cycle, self.__choice)
            self.__choose(tracks, target, self.__choice_of(target))

    def grab_still(self) -> QImage | None:
        """The picture shown now: the frame painted last.

        :returns: the image, or ``None`` when no frame has arrived.
        """
        return self.__surface.frame

    def close(self) -> None:
        """Let libvlc's objects go: stop, detach the events, release the media, the player and the instance.

        What the view does as it drops the engine; nothing is usable afterwards.
        """
        if self.__closed:
            return
        self.__closed = True
        self.stop()
        for kind in self.__event_kinds():
            self.__events.event_detach(kind)
        self.__player.set_media(None)
        self.__release_media()
        self.__player.release()
        self.__instance.release()

    # endregion

    # region libvlc's callbacks and events

    def __make_callbacks(self) -> tuple[Any, ...]:
        """Give libvlc the sink's three moments and the format, as ctypes callbacks it holds by address.

        :returns: every callback object made, so they stay referenced for as long as this player.
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

    def __event_kinds(self) -> tuple[Any, ...]:
        """The events listened to.

        :returns: python-vlc's enumeration members.
        """
        kinds = self.__vlc.EventType
        return (
            kinds.MediaPlayerOpening,
            kinds.MediaPlayerPlaying,
            kinds.MediaPlayerPaused,
            kinds.MediaPlayerStopped,
            kinds.MediaPlayerEndReached,
            kinds.MediaPlayerEncounteredError,
            kinds.MediaPlayerTimeChanged,
            kinds.MediaPlayerLengthChanged,
        )

    def __attach_events(self) -> None:
        """Have each event libvlc raises re-emitted as :attr:`event_raised`, through the one event manager kept."""
        for kind in self.__event_kinds():
            self.__events.event_attach(kind, self.__relay, self.__number(kind))

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
            self.event_raised.emit(kind, value, self.__epoch)
        except RuntimeError:  # this object was deleted while libvlc still had a thread going
            pass

    def __on_event(self, kind: int, value: object, epoch: int) -> None:
        """Turn an event into what ``QMediaPlayer`` would have said, on this object's thread.

        :param kind: the event type's number.
        :param value: the new time or length, for the events that carry one.
        :param epoch: the source the event belongs to; one of a source since replaced or stopped is dropped.
        """
        if epoch != self.__epoch or self.__closed:
            return
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

    def __on_frame(self, frame: QImage, epoch: int) -> None:
        """Show a frame, cropped to the video's visible size, and end a paused load on its first one at the position
        asked for.

        :param frame: the frame, at the decoder's padded size.
        :param epoch: the source the frame belongs to; one of a source since replaced or stopped is dropped.
        """
        if epoch != self.__epoch or self.__closed:
            return
        if self.__visible is None:
            width, height = self.__player.video_get_size(0)
            if width > 0 and height > 0:
                self.__visible = (int(width), int(height))
        if self.__visible is not None and (frame.width(), frame.height()) != self.__visible:
            frame = frame.copy(0, 0, *self.__visible)
        self.__surface.set_frame(frame)
        if self.__refreshing:
            self.__refreshing = False
            self.still_refreshed.emit(frame)
        if self.__grabbing and self.__at_wanted_position():
            self.__grabbing = False
            self.__wanted_ms = None
            self.__player.set_pause(1)
            self.still_ready.emit(frame)

    def __at_wanted_position(self) -> bool:
        """Whether a paused load has reached the position it was seeked to, when it was seeked at all.

        :returns: ``True`` when no seek was asked, or the player is within the tolerance of it.
        """
        return self.__wanted_ms is None or abs(self.position() - self.__wanted_ms) <= SEEK_TOLERANCE_MS

    def __subtitle_tracks(self) -> list[SubtitleTrack]:
        """The subtitle tracks libvlc lists, in its order, without the *disable* entry.

        :returns: the tracks; none while libvlc has not listed any.
        """
        described = self.__player.video_get_spu_description() or []
        return [
            SubtitleTrack.parse(
                int(track_id), name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
            )
            for track_id, name in described
            if int(track_id) != SUBTITLES_OFF
        ]

    def __current_subtitle(self, tracks: list[SubtitleTrack]) -> SubtitleTrack | None:
        """The track libvlc shows.

        :param tracks: the tracks it lists.
        :returns: the track, or ``None`` when none is shown.
        """
        shown = int(self.__player.video_get_spu())
        return next((track for track in tracks if track.track_id == shown), None)

    def __step_subtitle(self, delta: int) -> None:
        """Move along the cycle of none and the tracks the preferences visit.

        :param delta: how many places forward, or back when negative.
        """
        tracks = self.__subtitle_tracks()
        cycle = subtitle_cycle(tracks, self.__preferences)
        if not cycle:
            return
        ring: list[SubtitleTrack | None] = [None, *cycle]
        current = self.__current_subtitle(tracks)
        index = ring.index(current) if current in ring else 0
        target = ring[(index + delta) % len(ring)]
        self.__choose(tracks, target, self.__choice_of(target))

    @staticmethod
    def __choice_of(track: SubtitleTrack | None) -> SubtitleChoice:
        """What showing a track, or none, says the reader wants: none forgets the track, so turning the subtitles on
        again starts the cycle over.

        :param track: the track shown, ``None`` for none.
        :returns: the choice.
        """
        return SubtitleChoice(shown=False) if track is None else SubtitleChoice.of_track(track)

    def __choose(self, tracks: list[SubtitleTrack], track: SubtitleTrack | None, choice: SubtitleChoice) -> None:
        """Show a track by the reader's key or pick, and say what was chosen. This settles the matter: the choice
        waiting for the track list is dropped.

        :param tracks: the tracks libvlc lists.
        :param track: the track to show, ``None`` for none.
        :param choice: what showing it means.
        """
        self.__subtitle_timer.stop()
        self.__choice = choice
        self.__show_subtitle(track)
        self.__announce(tracks, track)
        self.subtitle_chosen.emit(choice)

    def __announce(self, tracks: list[SubtitleTrack], track: SubtitleTrack | None) -> None:
        """Say what the subtitle menu offers and which entry is on.

        :param tracks: the tracks libvlc lists; none to empty the menu.
        :param track: the track shown, ``None`` for none.
        """
        cycle = subtitle_cycle(tracks, self.__preferences)
        entries = subtitle_entries(tracks, cycle)
        self.__ring = [None, *entries] if entries else []
        self.subtitle_menu_changed.emit(subtitle_labels(entries), subtitle_index(entries, track), len(cycle))

    def __show_subtitle(self, track: SubtitleTrack | None) -> None:
        """Show a subtitle track; paused, seek to where the video is so a frame shows it.

        :param track: the track to show, ``None`` for none.
        """
        self.__player.video_set_spu(SUBTITLES_OFF if track is None else track.track_id)
        if self.__state == QMediaPlayer.PlaybackState.PausedState and not self.__grabbing:
            self.__refreshing = True
            self.__player.set_time(self.position())

    def __poll_subtitles(self) -> None:
        """Read libvlc's track list, and apply the choice once it has settled: the same two reads running, with
        something in it. A video that lists none is given up on after :data:`SUBTITLE_POLL_LIMIT` reads."""
        self.__polls += 1
        tracks = self.__subtitle_tracks()
        settled = bool(tracks) and tracks == self.__listed
        self.__listed = tracks
        if settled:
            self.__subtitle_timer.stop()
            cycle = subtitle_cycle(tracks, self.__preferences)
            target = remembered_track(cycle, self.__choice) if self.__choice.shown else None
            self.__show_subtitle(target)
            self.__announce(tracks, target)
        elif self.__polls >= SUBTITLE_POLL_LIMIT:
            self.__subtitle_timer.stop()
            self.subtitle_menu_changed.emit([NO_SUBTITLES_LABEL], 0, 0)

    def __open_media(self, *options: str) -> None:
        """Open the source as a new media, with libvlc options, in place of the one held.

        :param options: the media's options, ``:no-audio`` or ``:start-time=…``.
        """
        media = self.__instance.media_new(self.__source.toLocalFile(), *options)
        self.__player.set_media(media)
        self.__release_media()
        self.__media = media
        self.__polls = 0
        self.__listed = []
        self.__subtitle_timer.start()

    def __release_media(self) -> None:
        """Release the media held, if any."""
        if self.__media is not None:
            self.__media.release()
            self.__media = None

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
