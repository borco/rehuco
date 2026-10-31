"""What the player view's tests share: Qt Multimedia's playing methods patched on their classes, a runner that answers
at once, a mocked document, and helpers that make the player report what a real one does (#317).

The Qt Multimedia player is a real one, built lazily as the view builds it: its signals are emitted for real, and the
methods that would start playing are patched, so no media is ever loaded. The recorder, the document and the listing of
the tutorial's videos are what the view calls, and are tested elsewhere.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from borco_pyside.widgets import MessageBanner
from PySide6.QtCore import QSize
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoFrameFormat, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QComboBox, QLabel, QSlider, QStackedWidget, QToolButton, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.latest_runner import LatestRunner
from rehuco_agent.documents.player_view import GRAB_TIMEOUT_MS, NO_FRAME_MS, PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_still import VideoStill
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import ProgressEntry, RenameCoordinator, VideoFormat

RECORD: Final = Path.cwd() / "fake" / "tutorial" / "info.rehu"
"""The tutorial's record: its videos are beside it, or in folders under it."""

KEYS: Final = ["01.mp4", "02.mp4", "03.mp4"]
"""The tutorial's videos, by content key, in play order."""

SHORT_MS: Final = 10
"""A wait short enough to sit out in a test."""

LENGTH_MS: Final = 100_000
"""The length every video of these tests reports."""

PLAYING: Final = QMediaPlayer.PlaybackState.PlayingState
PAUSED: Final = QMediaPlayer.PlaybackState.PausedState
STOPPED: Final = QMediaPlayer.PlaybackState.StoppedState
BUFFERED: Final = QMediaPlayer.MediaStatus.BufferedMedia
LOADED: Final = QMediaPlayer.MediaStatus.LoadedMedia


def path_of(key: str) -> Path:
    """Where a video of the tutorial is.

    :param key: its content key.
    :returns: its path, beside the record.
    """
    return RECORD.parent / key


@dataclass(frozen=True)
class Media:  # pylint: disable=too-many-instance-attributes
    """The Qt Multimedia calls that would start real playback, patched on their classes."""

    play: Mock
    pause: Mock
    stop: Mock
    set_source: Mock
    set_position: Mock
    position: Mock
    duration: Mock
    set_rate: Mock
    set_volume: Mock


@dataclass(frozen=True)
class Listing:
    """What the view asks of the document's files: the videos listed, and the formats read."""

    keys: list[str]
    """The tutorial's videos; a test changes it, and the next listing answers with it."""

    formats: dict[str, VideoFormat | None]
    """The format of each video by file name; a video not named reads as none."""

    listed: Mock
    """The listing function, to see what it was asked."""


@fixture(name="media", autouse=True)
def fixture_media(mocker: MockerFixture) -> Media:
    """Patch the playing methods of Qt Multimedia, so a built player loads and plays nothing.

    :param mocker: pytest-mock fixture.
    :returns: the patches.
    """
    return Media(
        play=mocker.patch.object(QMediaPlayer, "play"),
        pause=mocker.patch.object(QMediaPlayer, "pause"),
        stop=mocker.patch.object(QMediaPlayer, "stop"),
        set_source=mocker.patch.object(QMediaPlayer, "setSource"),
        set_position=mocker.patch.object(QMediaPlayer, "setPosition"),
        position=mocker.patch.object(QMediaPlayer, "position", return_value=0),
        duration=mocker.patch.object(QMediaPlayer, "duration", return_value=0),
        set_rate=mocker.patch.object(QMediaPlayer, "setPlaybackRate"),
        set_volume=mocker.patch.object(QAudioOutput, "setVolume"),
    )


@fixture(name="listing", autouse=True)
def fixture_listing(mocker: MockerFixture) -> Listing:
    """Answer the view's background reads at once, from tables a test fills.

    A read that went to the thread pool would make every test wait for it; the runner itself is tested on its own.

    :param mocker: pytest-mock fixture.
    :returns: the tables.
    """
    keys = list(KEYS)
    formats: dict[str, VideoFormat | None] = {}

    def run_now(runner: LatestRunner, tag: str, work: Callable[[], object]) -> None:
        try:
            result: object = work()
        except Exception as error:  # pylint: disable=broad-exception-caught
            result = error
        runner.read.emit(tag, result)

    mocker.patch.object(LatestRunner, "start", autospec=True, side_effect=run_now)
    listed = mocker.patch(
        "rehuco_agent.documents.player_view.tutorial_video_keys", side_effect=lambda *a, **k: list(keys)
    )
    mocker.patch(
        "rehuco_agent.documents.player_view.read_video_format", side_effect=lambda path: formats.get(path.name)
    )
    return Listing(keys, formats, listed)


@fixture(name="progress")
def fixture_progress() -> dict[str, ProgressEntry]:
    """What the document holds of the reader's progress, by content key; a test fills it.

    :returns: the table.
    """
    return {}


@fixture(name="coordinator")
def fixture_coordinator(mocker: MockerFixture) -> RenameCoordinator:
    """A stand-in for the coordinator renames go through, to see who asks to hear of them.

    :param mocker: pytest-mock fixture.
    :returns: the autospecced coordinator.
    """
    return mocker.create_autospec(RenameCoordinator, instance=True)


@fixture(name="model")
def fixture_model(
    mocker: MockerFixture, progress: dict[str, ProgressEntry], coordinator: RenameCoordinator
) -> RehuDocumentModel:
    """A stand-in for the document: its path, its progress, its lengths, and the video watched last.

    :param mocker: pytest-mock fixture.
    :param progress: the progress table.
    :param coordinator: what it renames through.
    :returns: the autospecced model.
    """
    model = mocker.create_autospec(RehuDocumentModel, instance=True)
    model.path = RECORD
    model.rename_coordinator = coordinator
    model.progress_of.side_effect = progress.get
    model.measured_videos.return_value = {}
    model.last_video.return_value = None
    model.video_notes_of.return_value = ""
    model.notes_changed = mocker.Mock()
    return model


@fixture(name="recorder")
def fixture_recorder(mocker: MockerFixture) -> WatchProgressRecorder:
    """A stand-in for the recorder, whose pacing and writes are tested with it.

    :param mocker: pytest-mock fixture.
    :returns: the autospecced recorder.
    """
    return mocker.create_autospec(WatchProgressRecorder, instance=True)


def make_view(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    *,
    no_frame_ms: int = NO_FRAME_MS,
    grab_ms: int = GRAB_TIMEOUT_MS,
) -> PlayerView:
    """A shown player with nothing loaded; shown so its title is laid out and elided to a width.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :param recorder: the recorder.
    :param no_frame_ms: how long an AV1 video may play without a frame before it is blamed.
    :param grab_ms: how long a paused load may wait for its frame.
    :returns: the view.
    """
    view = PlayerView(model, recorder, no_frame_ms=no_frame_ms, grab_ms=grab_ms)
    qtbot.addWidget(view)
    view.resize(640, 400)
    view.show()
    return view


@fixture(name="view")
def fixture_view(qtbot: QtBot, model: RehuDocumentModel, recorder: WatchProgressRecorder) -> PlayerView:
    """A player with nothing loaded.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :param recorder: the recorder.
    :returns: the view.
    """
    return make_view(qtbot, model, recorder, no_frame_ms=SHORT_MS)


def player_of(view: PlayerView) -> QMediaPlayer:
    """The Qt Multimedia player a view has built.

    :param view: the view.
    :returns: its player.
    """
    player = view.findChild(QMediaPlayer)
    assert isinstance(player, QMediaPlayer)
    return player


def action_of(view: PlayerView, name: str) -> QAction:
    """One of a view's actions.

    :param view: the view.
    :param name: the action's object name.
    :returns: the action.
    """
    action = view.findChild(QAction, name)
    assert isinstance(action, QAction)
    return action


def slider_of(view: PlayerView) -> QSlider:
    """A view's seek slider.

    :param view: the view.
    :returns: the slider.
    """
    slider = view.findChild(QSlider, "position_slider")
    assert isinstance(slider, QSlider)
    return slider


def speed_combo_of(view: PlayerView) -> QComboBox:
    """A view's speed combo.

    :param view: the view.
    :returns: the combo.
    """
    combo = view.findChild(QComboBox, "speed_combo")
    assert isinstance(combo, QComboBox)
    return combo


def sink_of(view: PlayerView) -> QVideoSink:
    """The sink a view's video widget draws into.

    :param view: the view.
    :returns: its sink.
    """
    video_widget = view.findChild(QVideoWidget)
    assert isinstance(video_widget, QVideoWidget)
    return video_widget.videoSink()


def still_of(view: PlayerView) -> VideoStill:
    """The widget a view shows a frame of a video that is not playing on.

    :param view: the view.
    :returns: the still.
    """
    still = view.findChild(VideoStill)
    assert isinstance(still, VideoStill)
    return still


def shown_of(view: PlayerView) -> QWidget:
    """What the view's surface shows now: the video, or the still.

    :param view: the view.
    :returns: the widget on top.
    """
    stack = view.findChild(QStackedWidget, "surface_stack")
    assert isinstance(stack, QStackedWidget)
    return stack.currentWidget()


def notice_buttons(view: PlayerView) -> list[QToolButton]:
    """The remedies a view's banner offers.

    :param view: the view.
    :returns: the buttons of its rows.
    """
    banner = view.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return banner.findChildren(QToolButton)


def notices(view: PlayerView) -> list[str]:
    """What a view's banner says.

    :param view: the view.
    :returns: the texts of its rows.
    """
    banner = view.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return [label.text() for label in banner.findChildren(QLabel) if label.wordWrap()]


def label_text(view: PlayerView, name: str) -> str:
    """The text of one of a view's labels.

    :param view: the view.
    :param name: the label's object name.
    :returns: its text.
    """
    label = view.findChild(QLabel, name)
    assert isinstance(label, QLabel)
    return label.text()


def format_runner_of(view: PlayerView) -> LatestRunner:
    """The runner a view reads its videos' formats with.

    :param view: the view.
    :returns: its runner.
    """
    runner = view.findChild(LatestRunner, "format_runner")
    assert isinstance(runner, LatestRunner)
    return runner


def list_runner_of(view: PlayerView) -> LatestRunner:
    """The runner a view lists the tutorial's videos with.

    :param view: the view.
    :returns: its runner.
    """
    runner = view.findChild(LatestRunner, "list_runner")
    assert isinstance(runner, LatestRunner)
    return runner


def picture(start_ms: int | None = None) -> QVideoFrame:
    """A frame the sink counts as a picture.

    :param start_ms: when in the video it is from; unknown by default, as a frame built by hand is.
    :returns: a valid frame.
    """
    frame = QVideoFrame(QVideoFrameFormat(QSize(2, 2), QVideoFrameFormat.PixelFormat.Format_RGBX8888))
    if start_ms is not None:
        frame.setStartTime(start_ms * 1000)
    return frame


def start_playing(view: PlayerView, key: str = "01.mp4", *, length_ms: int = LENGTH_MS) -> QMediaPlayer:
    """Play a video of the tutorial and let the player report it: its length, that it plays, and that it buffered.

    :param view: the view.
    :param key: the video to play.
    :param length_ms: how long the player says it is.
    :returns: the player.
    """
    view.jump(key)
    player = player_of(view)
    player.durationChanged.emit(length_ms)
    player.playbackStateChanged.emit(PLAYING)
    player.mediaStatusChanged.emit(BUFFERED)
    return player


def load_paused(view: PlayerView, model: RehuDocumentModel, key: str, *, length_ms: int = LENGTH_MS) -> QMediaPlayer:
    """Show the dock on a video: it is the one watched last, loaded paused, and the player reports it buffered.

    The frame, which lets go of the file, is left to the test.

    :param view: the view.
    :param model: the document, told which video was watched last.
    :param key: the video.
    :param length_ms: how long the player says it is.
    :returns: the player.
    """
    model.last_video.return_value = key  # type: ignore[attr-defined]
    view.load_last()
    player = player_of(view)
    player.durationChanged.emit(length_ms)
    player.playbackStateChanged.emit(PAUSED)
    player.mediaStatusChanged.emit(BUFFERED)
    return player
