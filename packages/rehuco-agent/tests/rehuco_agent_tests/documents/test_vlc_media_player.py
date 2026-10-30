"""Tests for libvlc as the player dock's engine: QMediaPlayer's language over python-vlc's events
([[appendices.vlc#python-vlc-events]], #319)."""

# fixture-heavy tests, and small stand-ins for python-vlc's objects
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-few-public-methods

import sys
import threading
from collections.abc import Callable
from typing import Any, Final
from unittest.mock import Mock

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QWidget
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.vlc_media_player import INSTANCE_OPTIONS, VlcEngineError, VlcMediaPlayer
from rehuco_core import VlcLibrary

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown


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


Fire = Callable[[Kind, Any], None]

ENGINE: Final = "rehuco_agent.documents.vlc_media_player"


class FakeLibvlc:
    """What the engine touches of python-vlc: the module's enumeration, an instance and a player recording its calls."""

    def __init__(self) -> None:
        self.module: Final = Mock(EventType=EventType)
        self.player: Final = Mock()
        self.player.get_time.return_value = -1
        self.player.video_take_snapshot.return_value = 0
        self.callbacks: dict[int, tuple[Callable[..., None], int]] = {}
        self.player.event_manager.return_value.event_attach.side_effect = self.__attach
        self.instance: Final = Mock()
        self.instance.media_player_new.return_value = self.player
        self.instance.media_new.side_effect = lambda path: f"media:{path}"

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


@fixture(autouse=True)
def fixture_no_window_picture(mocker: MockerFixture) -> None:
    """On Windows the still is read off the window first; here that gives nothing unless a test says otherwise,
    so the snapshot path is what the other tests see.

    :param mocker: pytest-mock fixture.
    """
    if sys.platform == "win32":
        mocker.patch(f"{ENGINE}.window_picture.picture_of", return_value=None)


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
def fixture_surface(qtbot: QtBot) -> QWidget:
    """A native widget to draw into.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@fixture(name="engine")
def fixture_engine(library: Mock, surface: QWidget, delete_at_teardown: DeleteAtTeardown) -> VlcMediaPlayer:
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


@mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_the_engine_is_made_of_the_proxys_instance_and_player_with_input_off(
    library: Mock,
    libvlc: FakeLibvlc,
    surface: QWidget,
    delete_at_teardown: DeleteAtTeardown,
    mocker: MockerFixture,
    platform: str,
) -> None:
    """**Test steps:**

    * build an engine
    * verify the instance was asked with the fixed options, the player made of it, mouse and key input turned off,
      every event attached, and the surface's window handed over once for this OS
    """
    mocker.patch.object(sys, "platform", platform)

    delete_at_teardown(VlcMediaPlayer(library, surface))

    library.instance.assert_called_once_with(*INSTANCE_OPTIONS)
    library.media_player.assert_called_once_with(libvlc.instance)
    libvlc.player.video_set_mouse_input.assert_called_once_with(False)
    libvlc.player.video_set_key_input.assert_called_once_with(False)
    assert set(libvlc.callbacks) == {kind.value for kind in EventType.members()}
    handed = {"win32": libvlc.player.set_hwnd, "darwin": libvlc.player.set_nsobject}.get(
        platform, libvlc.player.set_xwindow
    )
    handed.assert_called_once_with(int(surface.winId()))


def test_a_proxy_with_no_player_is_an_engine_error(library: Mock, surface: QWidget) -> None:
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
    assert libvlc.player.set_media.call_args.args[0].startswith("media:")  # pylint: disable=no-member
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

    * play, and fire opening, length, playing, a time, paused, and end reached, each from another thread
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


def test_a_pause_while_playing_pauses_and_a_stop_stops(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play, see it playing, pause, then stop
    * verify libvlc was paused, then stopped, and the state is stopped at once after the stop
    """
    playback, _ = states(engine)
    engine.play()
    libvlc.fire(EventType.MediaPlayerPlaying)
    qtbot.waitUntil(lambda: QMediaPlayer.PlaybackState.PlayingState in playback)

    engine.pause()
    libvlc.player.set_pause.assert_called_once_with(1)

    engine.stop()
    libvlc.player.stop.assert_called_once_with()
    assert engine.playbackState() == QMediaPlayer.PlaybackState.StoppedState


def test_a_paused_load_plays_muted_until_a_picture_then_gives_a_still_and_pauses(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """libvlc decodes no frame without playing, so a load for a still plays muted until the first picture.

    **Test steps:**

    * pause before anything played
    * verify libvlc was muted and told to play
    * have the snapshot write a picture and fire the first video output
    * verify the still arrives as an image, libvlc was paused and unmuted, and the state says paused once libvlc does
    """
    picture = QImage(4, 3, QImage.Format.Format_RGB32)
    picture.fill(0xFF336699)

    def snapshot(_number: int, path: str, _width: int, _height: int) -> int:
        picture.save(path)
        return 0

    libvlc.player.video_take_snapshot.side_effect = snapshot

    engine.pause()

    libvlc.player.audio_set_mute.assert_called_with(True)
    libvlc.player.play.assert_called_once_with()
    with qtbot.waitSignal(engine.still_ready, timeout=2000) as blocker:
        libvlc.fire(EventType.MediaPlayerVout)
    assert blocker.args is not None
    assert blocker.args[0].size() == picture.size()  # pylint: disable=no-member
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


def test_a_still_that_libvlc_cannot_take_is_none(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * have the snapshot fail, then succeed without writing a file
    * verify ``None`` both times
    """
    libvlc.player.video_take_snapshot.return_value = -1
    assert engine.grab_still() is None

    libvlc.player.video_take_snapshot.return_value = 0
    assert engine.grab_still() is None


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
    library: Mock, libvlc: FakeLibvlc, surface: QWidget, delete_at_teardown: DeleteAtTeardown
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


def test_an_event_after_the_engine_is_deleted_is_dropped(library: Mock, libvlc: FakeLibvlc, surface: QWidget) -> None:
    """libvlc may still have a thread going when the engine is gone; its callback must not raise.

    **Test steps:**

    * build an engine, delete it, and fire an event
    * verify nothing raised
    """
    from shiboken6 import delete  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    engine = VlcMediaPlayer(library, surface)
    delete(engine)

    libvlc.fire(EventType.MediaPlayerPlaying)


def test_a_paused_load_whose_picture_cannot_be_taken_gives_no_still(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * pause before anything played, with the snapshot failing, and fire the first video output
    * verify libvlc was paused all the same and no still was emitted
    """
    libvlc.player.video_take_snapshot.return_value = -1
    stills: list[QImage] = []
    engine.still_ready.connect(stills.append)
    engine.pause()

    libvlc.fire(EventType.MediaPlayerVout)
    qtbot.waitUntil(lambda: libvlc.player.set_pause.called)

    libvlc.player.set_pause.assert_called_once_with(1)
    assert not stills


def test_a_video_output_while_playing_is_not_a_grab(engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot) -> None:
    """**Test steps:**

    * play, and fire the video output event
    * verify no snapshot was taken and nothing was paused
    """
    playback, _ = states(engine)
    engine.play()
    libvlc.fire(EventType.MediaPlayerPlaying)
    qtbot.waitUntil(lambda: QMediaPlayer.PlaybackState.PlayingState in playback)

    libvlc.fire(EventType.MediaPlayerVout)
    qtbot.wait(50)

    libvlc.player.video_take_snapshot.assert_not_called()
    libvlc.player.set_pause.assert_not_called()


@mark.windows
def test_on_windows_the_still_is_the_windows_picture_and_no_snapshot_is_taken(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, surface: QWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * have the window picture answer an image
    * verify the still is that image, taken of the surface, and libvlc was not asked for a snapshot
    """
    picture = QImage(6, 4, QImage.Format.Format_RGB32)
    picture.fill(0xFF102030)
    picture_of = mocker.patch(f"{ENGINE}.window_picture.picture_of", return_value=picture)

    still = engine.grab_still()

    assert still is not None and still.size() == picture.size()
    picture_of.assert_called_once_with(surface)
    libvlc.player.video_take_snapshot.assert_not_called()


@mark.windows
def test_on_windows_a_window_picture_refused_falls_back_to_the_snapshot(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * with the window picture giving nothing, have the snapshot write a file
    * verify the still comes from the snapshot
    """
    picture = QImage(4, 3, QImage.Format.Format_RGB32)
    picture.fill(0xFF336699)

    def snapshot(_number: int, path: str, _width: int, _height: int) -> int:
        picture.save(path)
        return 0

    libvlc.player.video_take_snapshot.side_effect = snapshot

    still = engine.grab_still()

    assert still is not None and still.size() == picture.size()
