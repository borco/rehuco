"""Tests for dragging the seek bar's handle under Qt Multimedia: the picture follows it, throttled, and only the release
is recorded (#613, [[plugins#in-app-player]]). libvlc's side is ``test_player_view_vlc``'s."""

from unittest.mock import Mock, call

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import RenameCoordinator

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    LENGTH_MS,
    PAUSED,
    PLAYING,
    RECORD,
    SHORT_MS,
    Media,
    action_of,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    fixture_view,  # noqa: F401
    label_text,
    load_paused,
    make_view,
    path_of,
    picture,
    player_of,
    sink_of,
    slider_of,
    start_playing,
    widget_frame,
)

CLEARED = call(QUrl())
"""What a player is told to let go of its video."""


def press(view: PlayerView) -> None:
    """Press the slider's handle.

    :param view: the view.
    """
    slider_of(view).sliderPressed.emit()


def drag(view: PlayerView, position_ms: int) -> None:
    """Move the held handle.

    :param view: the view.
    :param position_ms: where to.
    """
    slider_of(view).setSliderPosition(position_ms)
    slider_of(view).sliderMoved.emit(position_ms)


def release(view: PlayerView, position_ms: int) -> None:
    """Let go of the handle.

    :param view: the view.
    :param position_ms: where.
    """
    slider_of(view).setValue(position_ms)
    slider_of(view).sliderReleased.emit()


def run_out(view: PlayerView) -> None:
    """Have the interval between two of a drag's reported moves run out.

    :param view: the view.
    """
    timer = view.findChild(QTimer, "scrub_timer")
    assert isinstance(timer, QTimer)
    timer.stop()
    timer.timeout.emit()


def paused_and_let_go(view: PlayerView, model: RehuDocumentModel, media: Media) -> None:
    """Load a video paused and give it its frame, so its file is let go: where a paused video under Qt is.

    :param view: the view.
    :param model: the document.
    :param media: the patched calls, forgotten once it is loaded.
    """
    load_paused(view, model, "01.mp4")
    sink_of(view).videoFrameChanged.emit(picture())
    assert media.set_source.call_args == CLEARED
    media.set_source.reset_mock()
    media.pause.reset_mock()
    media.set_position.reset_mock()


# region The throttle


def test_a_drag_seeks_at_most_once_per_interval_to_the_latest_place(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video and drag the handle three times without the interval running out
    * verify only the first move sought
    * let the interval run out
    * verify the player was sought to the latest place, skipping the one between
    * let it run out with the handle still
    * verify nothing more was sought
    """
    start_playing(view)
    media.set_position.reset_mock()
    press(view)

    drag(view, 10_000)
    drag(view, 20_000)
    drag(view, 30_000)
    assert media.set_position.mock_calls == [call(10_000)]

    run_out(view)
    assert media.set_position.mock_calls == [call(10_000), call(30_000)]

    run_out(view)
    assert media.set_position.mock_calls == [call(10_000), call(30_000)]


def test_the_release_forgets_a_move_still_waiting_for_its_interval(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video, drag the handle twice, and let go elsewhere
    * let the interval run out
    * verify the player went to the first move and the release, never to the move left waiting
    """
    start_playing(view)
    media.set_position.reset_mock()
    press(view)
    drag(view, 10_000)
    drag(view, 20_000)

    release(view, 30_000)
    run_out(view)

    assert media.set_position.mock_calls == [call(10_000), call(30_000)]


# endregion

# region A video that plays


def test_dragging_a_video_that_plays_holds_it_and_shows_the_frame_with_the_clock_at_the_handle(
    view: PlayerView, media: Media
) -> None:
    """**Test steps:**

    * play a video and drag the handle
    * verify the player paused and was sought there, and the clock reads the handle's time
    * have the pause reported, and a frame arrive from far from the handle, as a quick drag's does
    * verify the frame is shown and the play button still offers to pause
    """
    player = start_playing(view)
    media.set_position.reset_mock()
    press(view)

    drag(view, 60_000)

    media.pause.assert_called_once_with()
    media.set_position.assert_called_once_with(60_000)
    assert label_text(view, "time_label") == "1:00 / 1:40"

    player.playbackStateChanged.emit(PAUSED)
    sink_of(view).videoFrameChanged.emit(picture(5_000))

    assert widget_frame(view).startTime() == 5_000_000
    assert action_of(view, "play_pause_action").text() == "Pause"


def test_nothing_a_held_video_reports_is_recorded_or_ends_it(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video and drag the handle, forgetting what was recorded so far
    * have the player report a position, a pause, and the end of the video
    * verify nothing was recorded and no other video was opened
    """
    player = start_playing(view)
    press(view)
    drag(view, 60_000)
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()

    player.positionChanged.emit(60_000)
    player.playbackStateChanged.emit(PAUSED)
    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    assert recorder.mock_calls == []  # type: ignore[attr-defined]
    media.set_source.assert_not_called()


def test_letting_go_of_a_video_that_played_seeks_then_plays_on_recording_only_there(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video, drag the handle, and let go elsewhere, watching the order of the calls
    * verify the player was sought there and then played, and that place alone was recorded and written
    * have playing reported, with a position
    * verify it is recorded again, and the button offers to pause
    """
    player = start_playing(view)
    press(view)
    drag(view, 60_000)
    player.playbackStateChanged.emit(PAUSED)
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.play.reset_mock()
    media.set_position.reset_mock()
    order = Mock()
    order.attach_mock(media.set_position, "seek")
    order.attach_mock(media.play, "play")

    release(view, 70_000)

    assert order.mock_calls == [call.seek(70_000), call.play()]
    assert recorder.mock_calls == [  # type: ignore[attr-defined]
        call.position("01.mp4", 70.0, 100.0),
        call.flush(),
    ]

    player.playbackStateChanged.emit(PLAYING)
    recorder.reset_mock()  # type: ignore[attr-defined]
    player.positionChanged.emit(70_500)

    assert recorder.mock_calls == [call.position("01.mp4", 70.5, 100.0)]  # type: ignore[attr-defined]
    assert action_of(view, "play_pause_action").text() == "Pause"


def test_a_video_let_go_of_while_playing_keeps_its_last_frame_until_one_of_the_new_place(view: PlayerView) -> None:
    """A frame from before the seek must not flash up over the frame the reader chose.

    **Test steps:**

    * play a video, drag the handle, show a frame of it, and let go there
    * have a frame from far before arrive
    * verify the frame of the drag is still shown
    * have a frame of the place arrive
    * verify it is shown
    """
    start_playing(view)
    press(view)
    drag(view, 60_000)
    sink_of(view).videoFrameChanged.emit(picture(60_000))
    release(view, 60_000)

    sink_of(view).videoFrameChanged.emit(picture(5_000))
    assert widget_frame(view).startTime() == 60_000_000

    sink_of(view).videoFrameChanged.emit(picture(60_033))
    assert widget_frame(view).startTime() == 60_033_000


def test_a_video_not_yet_buffered_is_left_to_play_and_the_release_seeks(view: PlayerView, media: Media) -> None:
    """Pausing then means a paused load to libvlc; the wait for the buffer is a moment.

    **Test steps:**

    * start a video that has not buffered, and drag the handle
    * verify it was neither paused nor sought
    * let go, and have it buffer
    * verify it went to where it was let go, and was never paused
    """
    view.jump("01.mp4")
    player_of(view).durationChanged.emit(LENGTH_MS)
    media.pause.assert_not_called()
    press(view)

    drag(view, 30_000)

    media.pause.assert_not_called()
    media.set_position.assert_not_called()

    release(view, 40_000)
    player_of(view).mediaStatusChanged.emit(BUFFERED)

    media.set_position.assert_called_once_with(40_000)
    media.pause.assert_not_called()


# endregion

# region A paused video, whose file Qt has let go of


def test_dragging_a_paused_video_opens_its_file_once_for_frames_and_records_nothing(
    view: PlayerView, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video, whose file is let go of, and drag the handle twice
    * verify the file was opened once, paused, never played, and the second move waited for it to buffer
    * have it buffer
    * verify it went to the latest place
    * have a frame arrive, and drag on
    * verify the frame shows, the player is sought in place, and nothing was recorded
    """
    paused_and_let_go(view, model, media)
    press(view)

    drag(view, 10_000)
    run_out(view)
    drag(view, 30_000)

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("01.mp4"))))
    media.pause.assert_called_once_with()
    media.play.assert_not_called()
    media.set_position.assert_not_called()

    player_of(view).mediaStatusChanged.emit(BUFFERED)
    media.set_position.assert_called_once_with(30_000)

    sink_of(view).videoFrameChanged.emit(picture(30_000))
    run_out(view)
    drag(view, 50_000)

    assert widget_frame(view).startTime() == 30_000_000
    media.set_position.assert_called_with(50_000)
    media.set_source.assert_called_once()
    assert recorder.position.mock_calls == []  # type: ignore[attr-defined]


def test_a_paused_video_let_go_of_lets_go_of_its_file_on_the_frame_of_that_place_and_stays_paused(
    view: PlayerView, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video whose file is let go of, drag the handle, have it buffer, and let go elsewhere
    * verify it was sought there and still holds its file
    * have a frame from far before arrive
    * verify it still holds its file
    * have a frame of the place arrive
    * verify that frame shows, the file is let go of, it never played, nothing was recorded, and the clock stays there
    """
    paused_and_let_go(view, model, media)
    press(view)
    drag(view, 10_000)
    player_of(view).mediaStatusChanged.emit(BUFFERED)

    release(view, 40_000)

    media.set_position.assert_called_with(40_000)
    assert media.set_source.call_args != CLEARED

    sink_of(view).videoFrameChanged.emit(picture(10_000))
    assert media.set_source.call_args != CLEARED

    sink_of(view).videoFrameChanged.emit(picture(40_000))

    assert widget_frame(view).startTime() == 40_000_000
    assert media.set_source.call_args == CLEARED
    media.play.assert_not_called()
    assert recorder.position.mock_calls == []  # type: ignore[attr-defined]
    assert label_text(view, "time_label") == "0:40 / 1:40"
    assert action_of(view, "play_pause_action").text() == "Play"


def test_a_paused_video_that_played_records_where_it_is_let_go_only(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video and pause it, and drag the handle
    * verify nothing was recorded
    * let go
    * verify that place was recorded and written, as a click on the groove would have
    """
    start_playing(view)
    action_of(view, "play_pause_action").trigger()
    assert media.set_source.call_args == CLEARED
    recorder.reset_mock()  # type: ignore[attr-defined]
    press(view)

    drag(view, 30_000)
    assert recorder.mock_calls == []  # type: ignore[attr-defined]

    release(view, 40_000)

    assert recorder.mock_calls == [  # type: ignore[attr-defined]
        call.position("01.mp4", 40.0, 100.0),
        call.flush(),
    ]


def test_a_long_drag_outlasts_the_wait_for_a_frame_and_the_release_starts_it_again(
    qtbot: QtBot, model: RehuDocumentModel, recorder: WatchProgressRecorder, media: Media
) -> None:
    """A file that gives no frame is let go of, but only once the reader has let go of it.

    **Test steps:**

    * load a video with a short wait for its frame, none having come, and drag the handle
    * sit out several waits
    * verify the file is still held
    * let go, and sit out another with no frame
    * verify the file is let go of
    """
    view = make_view(qtbot, model, recorder, grab_ms=SHORT_MS)
    load_paused(view, model, "01.mp4")
    press(view)
    drag(view, 30_000)

    qtbot.wait(SHORT_MS * 5)
    assert media.set_source.call_args != CLEARED

    release(view, 30_000)

    qtbot.waitUntil(lambda: media.set_source.call_args == CLEARED)


# endregion

# region What else can happen


def test_a_press_with_no_move_opens_nothing_and_the_release_is_a_plain_seek(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * load a video whose file is let go of, press the handle and let go without moving it
    * verify nothing was opened and the bar is at the place
    """
    paused_and_let_go(view, model, media)
    press(view)

    release(view, 50_000)

    media.set_source.assert_not_called()
    assert slider_of(view).value() == 50_000


def test_a_rename_during_a_drag_lets_go_of_the_file_and_the_drag_does_not_open_it_again(
    view: PlayerView, media: Media, model: RehuDocumentModel, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * load a video whose file is let go of, drag the handle, and have this resource's rename begin
    * verify the file was let go of
    * drag on, and let go
    * verify nothing opened it again, nothing was sought, and the bar is where it was let go
    """
    paused_and_let_go(view, model, media)
    press(view)
    drag(view, 10_000)
    player_of(view).mediaStatusChanged.emit(BUFFERED)
    media.set_position.reset_mock()
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(RECORD)  # pylint: disable=not-callable
    assert media.set_source.call_args == CLEARED
    media.set_source.reset_mock()

    run_out(view)
    drag(view, 20_000)
    release(view, 30_000)

    media.set_source.assert_not_called()
    media.set_position.assert_not_called()
    assert slider_of(view).value() == 30_000


def test_a_rename_during_a_drag_of_a_video_that_played_leaves_it_paused(
    view: PlayerView, media: Media, coordinator: RenameCoordinator, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video, drag the handle, and have this resource's rename begin
    * let go
    * verify it did not play again, the button offers to play, and where it was let go was recorded
    """
    player = start_playing(view)
    press(view)
    drag(view, 10_000)
    media.play.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(RECORD)  # pylint: disable=not-callable
    player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.StoppedState)
    release(view, 30_000)

    media.play.assert_not_called()
    assert action_of(view, "play_pause_action").text() == "Play"
    assert recorder.mock_calls[-2:] == [  # type: ignore[attr-defined]
        call.position("01.mp4", 30.0, 100.0),
        call.flush(),
    ]


def test_stepping_to_another_video_during_a_drag_leaves_the_release_a_plain_seek(
    view: PlayerView, media: Media
) -> None:
    """**Test steps:**

    * play a video, drag the handle, and load the next video
    * drag on, and let go
    * verify the next video was opened once and is not played
    """
    start_playing(view)
    press(view)
    drag(view, 10_000)
    media.play.reset_mock()
    media.set_source.reset_mock()

    action_of(view, "next_action").trigger()
    run_out(view)
    drag(view, 20_000)
    release(view, 30_000)

    assert media.set_source.mock_calls == [CLEARED, call(QUrl.fromLocalFile(str(path_of("02.mp4"))))]
    media.play.assert_not_called()


def test_stopping_during_a_drag_leaves_the_rest_of_it_doing_nothing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video, drag the handle, and stop, as closing the dock does
    * drag on, and let go
    * verify nothing was opened or sought
    """
    start_playing(view)
    press(view)
    drag(view, 10_000)

    view.stop()
    media.set_source.reset_mock()
    media.set_position.reset_mock()
    run_out(view)
    drag(view, 20_000)
    release(view, 0)

    media.set_source.assert_not_called()
    media.set_position.assert_not_called()


def test_play_or_pause_does_nothing_during_a_drag(view: PlayerView, media: Media) -> None:
    """The drag already decides what happens when it ends.

    **Test steps:**

    * play a video, drag the handle, and press play or pause
    * verify the player was neither played nor paused again
    """
    start_playing(view)
    press(view)
    drag(view, 10_000)
    media.play.reset_mock()
    media.pause.reset_mock()

    action_of(view, "play_pause_action").trigger()

    media.play.assert_not_called()
    media.pause.assert_not_called()


def test_a_drag_with_nothing_selected_does_nothing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * drag the handle of a view with nothing selected, and let go
    * verify nothing was opened or sought
    """
    press(view)

    drag(view, 10_000)
    release(view, 10_000)

    media.set_source.assert_not_called()
    media.set_position.assert_not_called()


# endregion
