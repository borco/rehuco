"""Tests for dragging the seek bar's handle under libvlc: the still follows it, and what the release leaves (#613,
[[plugins#in-app-player]]). The engine is a mock, as in ``test_player_view_vlc``, whose fixtures these share; Qt
Multimedia's side is ``test_player_view_scrub``'s."""

# fixture-heavy tests: a view, its document, its recorder, the library, the engine and the choice
# pylint: disable=too-many-arguments,too-many-positional-arguments

from unittest.mock import Mock, call

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QImage
from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import RenameCoordinator

from .player_view_support import (  # pylint: disable=unused-import
    RECORD,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    make_view,
    shown_of,
    slider_of,
    still_of,
)
from .test_player_view_vlc import (  # pylint: disable=unused-import
    deliver,
    fixture_engine,  # noqa: F401
    fixture_library,  # noqa: F401
    fixture_vlc_chosen,  # noqa: F401
)


def scrub(view: PlayerView, position_ms: int) -> None:
    """Press the slider's handle and move it.

    :param view: the view.
    :param position_ms: where to.
    """
    slider = slider_of(view)
    slider.sliderPressed.emit()
    slider.setSliderPosition(position_ms)
    slider.sliderMoved.emit(position_ms)


def let_go(view: PlayerView, position_ms: int) -> None:
    """Let go of the handle.

    :param view: the view.
    :param position_ms: where.
    """
    slider = slider_of(view)
    slider.setValue(position_ms)
    slider.sliderReleased.emit()


def frame_of(color: int) -> QImage:
    """A picture of one color.

    :param color: the color.
    :returns: the picture.
    """
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(color)
    return image


def refresh(engine: Mock, image: QImage) -> None:
    """Have the engine announce the frame a seek gave, to everything connected to it, as the signal would.

    :param engine: the engine mock.
    :param image: the frame.
    """
    for connected in engine.still_refreshed.connect.call_args_list:
        connected.args[0](image)  # pylint: disable=not-callable  # a Mock's record


def still_color(view: PlayerView) -> int:
    """The color of the still shown.

    :param view: the view.
    :returns: its first pixel.
    """
    image = still_of(view).image
    assert image is not None
    return image.pixel(0, 0)


def playing_under_libvlc(view: PlayerView, engine: Mock) -> None:
    """Play a video under libvlc and have it report that it plays, its length known.

    :param view: the view.
    :param engine: the engine mock.
    """
    view.jump("01.mp4")
    deliver(engine, "durationChanged", 100_000)
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "playbackStateChanged", QMediaPlayer.PlaybackState.PlayingState)


def test_dragging_a_video_that_plays_under_libvlc_holds_it_on_the_still_and_it_plays_on_from_the_release(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc and drag the handle
    * verify the last frame is taken as the still and shown, and the engine paused and was sought in place
    * have the engine announce the frame of the seek
    * verify the still shows it and the file is held
    * let go elsewhere
    * verify the engine was sought there and played on with no reopening, on its own surface, and that place recorded
    """
    del library, vlc_chosen
    engine.grab_still.return_value = frame_of(0xFF111111)
    view = make_view(qtbot, model, recorder)
    playing_under_libvlc(view, engine)
    engine.setSource.reset_mock()
    engine.setPosition.reset_mock()
    engine.play.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    scrub(view, 30_000)

    engine.pause.assert_called_once_with()
    engine.setPosition.assert_called_once_with(30_000)
    assert shown_of(view).objectName() == "still_widget"
    assert still_color(view) == 0xFF111111

    refresh(engine, frame_of(0xFF222222))

    assert still_color(view) == 0xFF222222
    engine.stop.assert_not_called()

    let_go(view, 40_000)

    engine.setPosition.assert_called_with(40_000)
    engine.play.assert_called_once_with()
    engine.setSource.assert_not_called()
    assert shown_of(view).objectName() == "vlc_surface"
    assert recorder.mock_calls == [  # type: ignore[attr-defined]
        call.position("01.mp4", 40.0, 100.0),
        call.flush(),
    ]


def test_dragging_a_video_paused_under_libvlc_seeks_in_place_and_it_stays_paused_holding_its_file(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc, pause, and drag the handle
    * verify it was sought in place, not reopened or paused again, and the still follows the frame of the seek
    * let go, and have the frame of that place announced
    * verify the still shows it, the file is still held and nothing played
    * press play
    * verify it resumes with no reopening
    """
    del library, vlc_chosen
    engine.grab_still.return_value = frame_of(0xFF111111)
    view = make_view(qtbot, model, recorder)
    playing_under_libvlc(view, engine)
    play_pause = view.findChild(QAction, "play_pause_action")
    assert isinstance(play_pause, QAction)
    play_pause.trigger()
    engine.setSource.reset_mock()
    engine.setPosition.reset_mock()
    engine.play.reset_mock()
    engine.pause.reset_mock()

    scrub(view, 30_000)
    refresh(engine, frame_of(0xFF222222))

    engine.setPosition.assert_called_once_with(30_000)
    engine.pause.assert_not_called()
    assert still_color(view) == 0xFF222222

    let_go(view, 40_000)
    refresh(engine, frame_of(0xFF333333))

    engine.setPosition.assert_called_with(40_000)
    assert still_color(view) == 0xFF333333
    assert shown_of(view).objectName() == "still_widget"
    engine.stop.assert_not_called()
    engine.play.assert_not_called()

    play_pause.trigger()

    engine.play.assert_called_once_with()
    engine.setSource.assert_not_called()


def test_a_rename_after_a_drag_of_a_video_paused_under_libvlc_lets_go_and_keeps_the_picture(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    coordinator: RenameCoordinator,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """Letting go clears libvlc's surface, so the picture must be the still by then.

    **Test steps:**

    * play under libvlc, pause, drag the handle, let go, and have the frame announced
    * have this resource's rename begin
    * verify the file was let go of and the still of that frame is what shows
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    playing_under_libvlc(view, engine)
    play_pause = view.findChild(QAction, "play_pause_action")
    assert isinstance(play_pause, QAction)
    play_pause.trigger()
    scrub(view, 30_000)
    let_go(view, 30_000)
    refresh(engine, frame_of(0xFF222222))
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(RECORD)  # pylint: disable=not-callable

    engine.stop.assert_called_once_with()
    engine.setSource.assert_called_with(QUrl())
    assert shown_of(view).objectName() == "still_widget"
    assert still_color(view) == 0xFF222222


def test_dragging_a_video_loaded_under_libvlc_opens_it_for_the_drag_and_lets_go_on_the_frame_of_the_release(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * load a video paused under libvlc, give it its still so its file is let go of, and drag the handle
    * verify it was opened once as a paused load, and the seek waits for it to buffer
    * have it buffer, and its still arrive
    * verify it was sought, the still shows, and the file is held for the rest of the drag
    * let go elsewhere, and have the frame of that place announced
    * verify it was sought there, the still shows that frame, the file is let go of, and it never played
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    model.last_video.return_value = "01.mp4"  # type: ignore[attr-defined]
    view.load_last()
    deliver(engine, "durationChanged", 100_000)
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "still_ready", frame_of(0xFF111111))
    engine.setSource.reset_mock()
    engine.pause.reset_mock()
    engine.stop.reset_mock()

    scrub(view, 30_000)

    engine.setSource.assert_called_once()
    engine.pause.assert_called_once_with()
    engine.setPosition.assert_not_called()

    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "still_ready", frame_of(0xFF222222))

    engine.setPosition.assert_called_once_with(30_000)
    assert still_color(view) == 0xFF222222
    engine.stop.assert_not_called()

    let_go(view, 40_000)
    engine.stop.assert_not_called()
    refresh(engine, frame_of(0xFF333333))

    engine.setPosition.assert_called_with(40_000)
    assert still_color(view) == 0xFF333333
    assert shown_of(view).objectName() == "still_widget"
    engine.stop.assert_called_once_with()
    engine.setSource.assert_called_with(QUrl())
    engine.play.assert_not_called()
