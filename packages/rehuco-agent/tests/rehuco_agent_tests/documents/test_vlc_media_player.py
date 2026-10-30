"""Tests for libvlc as the player dock's engine: QMediaPlayer's language over python-vlc's events, and its frames
rendered into memory ([[appendices.vlc#python-vlc-events]], [[appendices.vlc#memory-rendering]], #319)."""

# fixture-heavy tests, and small stand-ins for python-vlc's objects
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-few-public-methods

import ctypes
import sys
import threading
from collections.abc import Callable
from typing import Any, Final
from unittest.mock import Mock

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from pytest import fixture, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.vlc_media_player import INSTANCE_OPTIONS, VlcEngineError, VlcMediaPlayer
from rehuco_agent.documents.vlc_surface import VlcSurface
from rehuco_core import VlcLibrary

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

VideoLockCb = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
VideoUnlockCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
VideoDisplayCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
VideoCleanupCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
VideoFormatCb = ctypes.CFUNCTYPE(
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
)
"""python-vlc's callback prototypes, as ``vlc.CallbackDecorators`` declares them."""

PADDED: Final = (640, 384)
"""The decoder's picture size for a 640x360 video: padded to its alignment."""

VISIBLE: Final = (640, 360)


class Kind:
    """One member of a fake ``vlc.EventType``, shaped like python-vlc's: the number in ``value``, and no ``int()`` --
    the real members are ctypes enumerations, and ``int(member)`` raises (measured against 3.0.21203).

    :param value: the event's number.
    """

    def __init__(self, value: int) -> None:
        self.value: Final = value

    def __index__(self) -> int:  # noqa: PLE0307  # what int() would reach
        raise TypeError("python-vlc's enumeration members are not integers")


class EventType:
    """The event types a fake ``vlc`` module hands out."""

    MediaPlayerOpening = Kind(0x102)
    MediaPlayerPlaying = Kind(0x104)
    MediaPlayerPaused = Kind(0x105)
    MediaPlayerStopped = Kind(0x106)
    MediaPlayerEndReached = Kind(0x109)
    MediaPlayerEncounteredError = Kind(0x10A)
    MediaPlayerTimeChanged = Kind(0x10B)
    MediaPlayerLengthChanged = Kind(0x111)
    MediaPlayerVout = Kind(0x112)

    @classmethod
    def members(cls) -> list[Kind]:
        """Every member.

        :returns: the members.
        """
        return [value for value in vars(cls).values() if isinstance(value, Kind)]


class CallbackDecorators:
    """The prototypes a fake ``vlc`` module hands out."""

    VideoLockCb = VideoLockCb
    VideoUnlockCb = VideoUnlockCb
    VideoDisplayCb = VideoDisplayCb
    VideoCleanupCb = VideoCleanupCb
    VideoFormatCb = VideoFormatCb


class FakeLibvlc:
    """What the engine touches of python-vlc: the module's enumerations, an instance and a player recording its calls,
    and the callbacks the engine registered, which a test calls the way libvlc would."""

    def __init__(self) -> None:
        self.module: Final = Mock(EventType=EventType, CallbackDecorators=CallbackDecorators)
        self.player: Final = Mock()
        self.player.get_time.return_value = -1
        self.player.is_playing.return_value = False
        self.media: list[Mock] = []
        self.player.video_get_size.return_value = VISIBLE
        self.callbacks: dict[int, tuple[Callable[..., None], int]] = {}
        self.player.event_manager.return_value.event_attach.side_effect = self.__attach
        self.instance: Final = Mock()
        self.instance.media_player_new.return_value = self.player
        self.instance.media_new.side_effect = self.__new_media
        self.__set_up = False

    def releases(self, index: int) -> int:
        """How often one of the media made was released.

        :param index: which media, in the order made.
        :returns: the count.
        """
        return self.media[index].release.call_count  # pylint: disable=no-member

    def __new_media(self, path: str) -> Mock:
        """A media wrapper, kept so a test can see it released."""
        media = Mock(path=path)
        self.media.append(media)
        return media

    def __attach(self, kind: Kind, callback: Callable[..., None], *args: Any) -> None:
        """Keep a callback the way libvlc would call it."""
        self.callbacks = {**self.callbacks, kind.value: (callback, args[0])}  # astroid's E1137

    def fire(self, kind: Kind, value: Any = None) -> None:
        """Raise an event the way libvlc does: on a thread of its own, with the value in the event's union.

        :param kind: which event.
        :param value: the new time or length, for those that carry one.
        """
        callback, number = self.callbacks[kind.value]
        union = Mock(new_time=value, new_length=value)
        event = Mock(u=union)
        thread = threading.Thread(target=callback, args=(event, number), name="libvlc")
        thread.start()
        thread.join()

    @property
    def video_callbacks(self) -> tuple[Any, Any, Any]:
        """The lock, unlock and display callbacks the engine registered."""
        lock, unlock, display, _opaque = self.player.video_set_callbacks.call_args.args
        return lock, unlock, display

    @property
    def format_callbacks(self) -> tuple[Any, Any]:
        """The setup and cleanup callbacks the engine registered."""
        setup, cleanup = self.player.video_set_format_callbacks.call_args.args
        return setup, cleanup

    def set_up(self) -> tuple[bytes, int, int]:
        """Call the format callback the way libvlc does, for a padded 640x384 picture.

        :returns: the chroma the engine chose, the pitch and the lines it answered.
        """
        setup, _ = self.format_callbacks
        chroma = ctypes.create_string_buffer(b"I420", 4)
        width = (ctypes.c_uint * 1)(PADDED[0])
        height = (ctypes.c_uint * 1)(PADDED[1])
        pitches = (ctypes.c_uint * 1)()
        lines = (ctypes.c_uint * 1)()
        assert setup(None, chroma, width, height, pitches, lines) == 1
        self.__set_up = True
        return chroma.raw, pitches[0], lines[0]

    def feed_frame(self, byte: int) -> None:
        """Write one frame of one byte value and display it, on a thread of its own, as libvlc does.

        :param byte: the value every byte of the frame takes.
        """
        if not self.__set_up:
            self.set_up()
        lock, unlock, display = self.video_callbacks

        def libvlc_thread() -> None:
            planes = (ctypes.c_void_p * 1)()
            lock(None, planes)
            ctypes.memset(planes[0], byte, PADDED[0] * 4 * PADDED[1])
            unlock(None, None, planes)
            display(None, None)

        thread = threading.Thread(target=libvlc_thread, name="libvlc")
        thread.start()
        thread.join()


@fixture(name="libvlc")
def fixture_libvlc() -> FakeLibvlc:
    """A fake python-vlc.

    :returns: the fake.
    """
    return FakeLibvlc()


@fixture(name="library")
def fixture_library(libvlc: FakeLibvlc) -> Mock:
    """A loaded proxy over the fake.

    :param libvlc: the fake.
    :returns: the proxy, a mock of the real one.
    """
    library = Mock(spec=VlcLibrary)
    library.available = True
    library.reason = None
    library.module = libvlc.module
    library.instance.return_value = libvlc.instance
    library.media_player.return_value = libvlc.player
    return library


@fixture(name="surface")
def fixture_surface(qtbot: QtBot) -> VlcSurface:
    """The widget the frames are painted on.

    :param qtbot: pytest-qt fixture.
    :returns: the surface.
    """
    surface = VlcSurface()
    qtbot.addWidget(surface)
    return surface


@fixture(name="engine")
def fixture_engine(library: Mock, surface: VlcSurface, delete_at_teardown: DeleteAtTeardown) -> VlcMediaPlayer:
    """An engine over the fake, with a file opened.

    :param library: the proxy.
    :param surface: the widget.
    :param delete_at_teardown: deletes what is built bare.
    :returns: the engine.
    """
    engine = delete_at_teardown(VlcMediaPlayer(library, surface))
    engine.setSource(QUrl.fromLocalFile("C:/clips/a.mp4" if sys.platform == "win32" else "/clips/a.mp4"))
    return engine


def states(engine: VlcMediaPlayer) -> tuple[list[QMediaPlayer.PlaybackState], list[QMediaPlayer.MediaStatus]]:
    """Listen to the engine's state and status signals.

    :param engine: the engine.
    :returns: the lists the signals append to.
    """
    playback: list[QMediaPlayer.PlaybackState] = []
    status: list[QMediaPlayer.MediaStatus] = []
    engine.playbackStateChanged.connect(playback.append)
    engine.mediaStatusChanged.connect(status.append)
    return playback, status


def test_the_engine_is_made_of_the_proxys_instance_and_player_rendering_into_memory(
    library: Mock, libvlc: FakeLibvlc, surface: VlcSurface, delete_at_teardown: DeleteAtTeardown
) -> None:
    """**Test steps:**

    * build an engine
    * verify the instance was asked with the fixed options, the player made of it, every event but the video
      output's attached, the memory callbacks and the format callbacks registered, and no window handed over
    """
    delete_at_teardown(VlcMediaPlayer(library, surface))

    library.instance.assert_called_once_with(*INSTANCE_OPTIONS)
    library.media_player.assert_called_once_with(libvlc.instance)
    assert set(libvlc.callbacks) == {kind.value for kind in EventType.members()} - {EventType.MediaPlayerVout.value}
    # one event manager wrapper, kept: python-vlc keeps a callback alive through the wrapper it was attached on
    libvlc.player.event_manager.assert_called_once_with()
    assert len(libvlc.video_callbacks) == 3
    assert len(libvlc.format_callbacks) == 2
    libvlc.player.set_hwnd.assert_not_called()


def test_a_proxy_with_no_player_is_an_engine_error(library: Mock, surface: VlcSurface) -> None:
    """**Test steps:**

    * have the proxy give no instance, carrying a reason
    * verify building raises with that reason
    """
    library.instance.return_value = None
    library.media_player.return_value = None
    library.reason = "libvlc is bound elsewhere."

    with raises(VlcEngineError, match="bound elsewhere"):
        VlcMediaPlayer(library, surface)


def test_a_source_is_a_media_of_the_instance_and_an_empty_one_lets_go(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * open a file, then an empty URL
    * verify the media was made of the file and set, then cleared, with the status following
    """
    _, status = states(engine)
    assert libvlc.player.set_media.call_args.args[0] is libvlc.media[0]
    assert engine.source().isLocalFile()

    engine.setSource(QUrl())

    libvlc.player.set_media.assert_called_with(None)
    assert engine.source().isEmpty()
    assert status == [QMediaPlayer.MediaStatus.NoMedia]
    assert engine.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia


def test_libvlcs_events_arrive_on_the_gui_thread_as_qts_states(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """Each event, raised on a libvlc thread, is delivered queued and becomes the state and status Qt would report.

    **Test steps:**

    * play, and fire opening, length, playing, a time, paused, stopped and end reached, each from another thread
    * verify the Qt signals in order, on this thread, and the duration and position kept
    """
    playback, status = states(engine)
    positions: list[int] = []
    durations: list[int] = []
    engine.positionChanged.connect(positions.append)
    engine.durationChanged.connect(durations.append)
    engine.play()
    libvlc.player.play.assert_called_once_with()

    libvlc.fire(EventType.MediaPlayerOpening)
    libvlc.fire(EventType.MediaPlayerLengthChanged, 8000)
    libvlc.fire(EventType.MediaPlayerPlaying)
    libvlc.fire(EventType.MediaPlayerTimeChanged, 1500)
    libvlc.fire(EventType.MediaPlayerPaused)
    libvlc.fire(EventType.MediaPlayerStopped)
    libvlc.fire(EventType.MediaPlayerEndReached)
    qtbot.waitUntil(lambda: QMediaPlayer.MediaStatus.EndOfMedia in status)

    assert playback == [
        QMediaPlayer.PlaybackState.PlayingState,
        QMediaPlayer.PlaybackState.PausedState,
        QMediaPlayer.PlaybackState.StoppedState,
    ]
    # loading was said as the source was set, before this listened, and opening says nothing new
    assert status == [QMediaPlayer.MediaStatus.BufferedMedia, QMediaPlayer.MediaStatus.EndOfMedia]
    assert durations == [8000]
    assert engine.duration() == 8000
    assert positions == [1500]


def test_a_replay_after_the_end_stops_first(engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot) -> None:
    """libvlc stays *Ended* and ignores ``play()`` there, so the engine stops before playing again.

    **Test steps:**

    * play to the end, then play again
    * verify a stop came before the second play, and that a play before the end made no stop
    """
    _, status = states(engine)
    engine.play()
    libvlc.fire(EventType.MediaPlayerEndReached)
    qtbot.waitUntil(lambda: QMediaPlayer.MediaStatus.EndOfMedia in status)
    libvlc.player.stop.assert_not_called()

    engine.play()

    libvlc.player.stop.assert_called_once_with()
    assert libvlc.player.play.call_count == 2


def test_an_error_is_reported_as_qt_reports_one(engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot) -> None:
    """**Test steps:**

    * play and have libvlc raise an error
    * verify ``errorOccurred`` and the invalid-media status
    """
    _, status = states(engine)
    engine.play()

    with qtbot.waitSignal(engine.errorOccurred, timeout=2000) as blocker:
        libvlc.fire(EventType.MediaPlayerEncounteredError)

    assert blocker.args is not None
    assert blocker.args[0] == QMediaPlayer.Error.ResourceError
    assert QMediaPlayer.MediaStatus.InvalidMedia in status


def test_a_pause_while_playing_pauses_and_a_stop_stops_and_clears_the_picture(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play, see it playing with a frame shown, pause, then stop
    * verify libvlc was paused, then stopped, the state stopped at once, and the surface emptied
    """
    playback, _ = states(engine)
    engine.play()
    libvlc.fire(EventType.MediaPlayerPlaying)
    qtbot.waitUntil(lambda: QMediaPlayer.PlaybackState.PlayingState in playback)
    libvlc.feed_frame(0x40)
    qtbot.waitUntil(lambda: surface.frame is not None)

    engine.pause()
    libvlc.player.set_pause.assert_called_once_with(1)

    engine.stop()
    libvlc.player.stop.assert_called_once_with()
    assert engine.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    assert surface.frame is None
    assert engine.grab_still() is None


def test_the_format_callback_chooses_32_bit_pixels_at_the_decoders_size(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * call the format callback as libvlc does, with its padded picture size
    * verify the chroma was changed to ``RV32`` and the pitch and lines answer that size
    """
    del engine
    chroma, pitch, lines = libvlc.set_up()

    assert chroma == b"RV32"
    assert (pitch, lines) == (PADDED[0] * 4, PADDED[1])


def test_a_frame_is_shown_cropped_to_the_videos_visible_size(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """The buffer is the decoder's padded picture; what the surface shows is the video.

    **Test steps:**

    * play and feed one grey frame from a libvlc thread, then a darker one
    * verify the surface shows each at the visible size, in its grey, the size asked of libvlc once, and that the
      still is the last frame
    """
    engine.play()

    libvlc.feed_frame(0x80)
    qtbot.waitUntil(lambda: surface.frame is not None)
    first = surface.frame
    libvlc.feed_frame(0x40)
    qtbot.waitUntil(lambda: surface.frame is not first)

    frame = surface.frame
    assert first is not None and frame is not None
    assert (first.width(), first.height()) == (frame.width(), frame.height()) == VISIBLE
    assert first.pixel(10, 10) & 0xFFFFFF == 0x808080
    assert frame.pixel(10, 10) & 0xFFFFFF == 0x404040
    libvlc.player.video_get_size.assert_called_once_with(0)
    assert engine.grab_still() is frame


def test_a_frame_before_the_visible_size_is_known_is_shown_whole(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """**Test steps:**

    * have libvlc not know the video's size yet and feed a frame
    * verify the padded frame is shown as it is
    """
    libvlc.player.video_get_size.return_value = (0, 0)
    engine.play()

    libvlc.feed_frame(0x20)
    qtbot.waitUntil(lambda: surface.frame is not None)

    frame = surface.frame
    assert frame is not None
    assert (frame.width(), frame.height()) == PADDED


def test_a_paused_load_plays_muted_until_the_first_frame_then_gives_the_still_and_pauses(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """libvlc decodes no frame without playing, so a load for a still plays muted until the first frame.

    **Test steps:**

    * pause before anything played
    * verify libvlc was muted and told to play
    * feed the first frame
    * verify the still arrives as that frame, libvlc was paused and unmuted
    """
    engine.pause()

    libvlc.player.audio_set_mute.assert_called_with(True)
    libvlc.player.play.assert_called_once_with()
    with qtbot.waitSignal(engine.still_ready, timeout=2000) as blocker:
        libvlc.feed_frame(0x60)
    assert blocker.args is not None
    still: QImage = blocker.args[0]
    assert (still.width(), still.height()) == VISIBLE  # pylint: disable=no-member  # a signal's record
    libvlc.player.set_pause.assert_called_once_with(1)
    libvlc.player.audio_set_mute.assert_called_with(False)


def test_play_during_a_paused_load_carries_on_unmuted(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * pause before anything played, then play
    * verify no second play was made: it was unmuted and unpaused instead
    """
    engine.pause()

    engine.play()

    libvlc.player.play.assert_called_once_with()
    libvlc.player.audio_set_mute.assert_called_with(False)
    libvlc.player.set_pause.assert_called_once_with(0)


def test_the_cleanup_callback_lets_the_buffer_go(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * set up, then call the cleanup callback as libvlc does, then lock
    * verify the lock answers no buffer
    """
    del engine
    libvlc.set_up()
    _, cleanup = libvlc.format_callbacks
    lock, _, _ = libvlc.video_callbacks

    cleanup(None)

    planes = (ctypes.c_void_p * 1)()
    lock(None, planes)
    assert planes[0] is None


def test_position_rate_and_volume_reach_libvlc_in_its_units(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * ask the position with nothing playing, then with libvlc at a time; seek; set a rate and a volume
    * verify milliseconds in and out, the rate as a float, and the volume as a percentage
    """
    assert engine.position() == 0
    libvlc.player.get_time.return_value = 2500
    assert engine.position() == 2500

    engine.setPosition(4000)
    engine.setPlaybackRate(1.5)
    engine.setVolume(0.25)

    libvlc.player.set_time.assert_called_once_with(4000)
    libvlc.player.set_rate.assert_called_once_with(1.5)
    libvlc.player.audio_set_volume.assert_called_once_with(25)


def test_nothing_opened_plays_nothing(
    library: Mock, libvlc: FakeLibvlc, surface: VlcSurface, delete_at_teardown: DeleteAtTeardown
) -> None:
    """**Test steps:**

    * play and pause an engine with no source
    * verify libvlc was asked nothing
    """
    engine = delete_at_teardown(VlcMediaPlayer(library, surface))

    engine.play()
    engine.pause()

    libvlc.player.play.assert_not_called()
    libvlc.player.set_pause.assert_not_called()


def test_an_event_after_the_engine_is_deleted_is_dropped(
    library: Mock, libvlc: FakeLibvlc, surface: VlcSurface
) -> None:
    """libvlc may still have a thread going when the engine is gone; its callback must not raise.

    **Test steps:**

    * build an engine, delete it, and fire an event
    * verify nothing raised
    """
    from shiboken6 import delete  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    engine = VlcMediaPlayer(library, surface)
    delete(engine)

    libvlc.fire(EventType.MediaPlayerPlaying)


def test_a_length_of_nothing_is_not_a_duration(engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot) -> None:
    """**Test steps:**

    * fire a length change of 0, then one of 8000
    * verify only the second is reported
    """
    durations: list[int] = []
    engine.durationChanged.connect(durations.append)

    libvlc.fire(EventType.MediaPlayerLengthChanged, 0)
    libvlc.fire(EventType.MediaPlayerLengthChanged, 8000)
    qtbot.waitUntil(lambda: durations == [8000])

    assert engine.duration() == 8000


def test_a_frame_already_at_the_visible_size_is_shown_as_it_is(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """**Test steps:**

    * have the visible size equal the decoder's and feed a frame
    * verify it is shown uncropped
    """
    libvlc.player.video_get_size.return_value = PADDED
    engine.play()

    libvlc.feed_frame(0x10)
    qtbot.waitUntil(lambda: surface.frame is not None)

    frame = surface.frame
    assert frame is not None
    assert (frame.width(), frame.height()) == PADDED


def test_a_source_replaced_releases_the_media_before_it(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * open a second file, then an empty URL
    * verify the first media was released as the second was set, and the second as the source was cleared
    """
    engine.setSource(QUrl.fromLocalFile("C:/clips/b.mp4" if sys.platform == "win32" else "/clips/b.mp4"))
    assert libvlc.releases(0) == 1
    assert libvlc.releases(1) == 0

    engine.setSource(QUrl())

    assert libvlc.releases(1) == 1


def test_a_frame_queued_behind_a_change_of_source_is_dropped(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """A frame of the video just left arrives after the next video was set; it must not be shown as the next one's.

    **Test steps:**

    * play, feed a frame, and set another source before the frame is delivered
    * verify nothing is shown; then feed a frame of the new source and verify it is
    """
    engine.play()
    libvlc.feed_frame(0x80)
    engine.setSource(QUrl.fromLocalFile("C:/clips/b.mp4" if sys.platform == "win32" else "/clips/b.mp4"))
    qtbot.wait(50)
    assert surface.frame is None

    engine.play()
    libvlc.feed_frame(0x40)
    qtbot.waitUntil(lambda: surface.frame is not None)


def test_an_end_queued_behind_a_change_of_source_does_not_restart_the_next_video(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play, fire the end, and set another source before the end is delivered; play, and play again
    * verify no stop was made: the end was the old video's
    """
    engine.play()
    libvlc.fire(EventType.MediaPlayerEndReached)
    engine.setSource(QUrl.fromLocalFile("C:/clips/b.mp4" if sys.platform == "win32" else "/clips/b.mp4"))
    qtbot.wait(50)

    engine.play()
    engine.play()

    libvlc.player.stop.assert_not_called()
    assert engine.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia


def test_a_paused_load_waits_for_the_frame_at_the_position_asked_for(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: VlcSurface, qtbot: QtBot
) -> None:
    """The first frame libvlc decodes is the file's start, ahead of the seek; the still is the frame at the seek.

    **Test steps:**

    * pause (a paused load), seek to 5 s, and feed a frame while libvlc is still at 0
    * verify the frame is shown but is no still, and libvlc was not paused
    * feed a frame with libvlc at 5 s and verify the still arrives and libvlc pauses
    """
    stills: list[QImage] = []
    engine.still_ready.connect(stills.append)
    engine.pause()
    engine.setPosition(5000)
    libvlc.player.get_time.return_value = 0

    libvlc.feed_frame(0x10)
    qtbot.waitUntil(lambda: surface.frame is not None)
    assert not stills
    libvlc.player.set_pause.assert_not_called()

    libvlc.player.get_time.return_value = 4800
    libvlc.feed_frame(0x20)
    qtbot.waitUntil(lambda: len(stills) == 1)
    libvlc.player.set_pause.assert_called_once_with(1)


def test_a_pause_asks_libvlc_whether_it_plays_rather_than_the_queued_state(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """A pause right after a resume, before the playing event arrived, pauses rather than starting a muted load.

    **Test steps:**

    * have libvlc say it plays while the engine's state is still stopped, and pause
    * verify it was paused, and no muted play began
    """
    libvlc.player.is_playing.return_value = True

    engine.pause()

    libvlc.player.set_pause.assert_called_once_with(1)
    libvlc.player.play.assert_not_called()


def test_closing_releases_everything_of_libvlcs(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * close the engine, twice
    * verify it stopped, detached each event from the one manager, released the media, the player and the instance,
      once
    """
    engine.close()
    engine.close()

    libvlc.player.stop.assert_called_once_with()
    detached = libvlc.player.event_manager.return_value.event_detach
    assert detached.call_count == len(libvlc.callbacks)
    assert libvlc.releases(0) == 1
    libvlc.player.release.assert_called_once_with()
    libvlc.instance.release.assert_called_once_with()


def test_an_event_after_closing_changes_nothing(engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot) -> None:
    """**Test steps:**

    * close, then fire a playing event
    * verify the state stays stopped
    """
    engine.close()

    libvlc.fire(EventType.MediaPlayerPlaying)
    qtbot.wait(50)

    assert engine.playbackState() == QMediaPlayer.PlaybackState.StoppedState
