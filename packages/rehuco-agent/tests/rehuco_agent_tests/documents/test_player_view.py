"""Tests for the in-app video player: which video it shows, what it holds open and when, and what it records (#317).

The transport, the keys and the notices are ``test_player_view_controls``'. The Qt Multimedia player is a real one with
its playing methods patched (``player_view_support``), so a test emits the signals a real player would.
"""

# which video is shown, when its file is held, and what is recorded are one subject, and every test needs the same
# patched player; a split would only scatter the support
# pylint: disable=too-many-lines

from pathlib import Path
from unittest.mock import Mock, call

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame
from pytest import mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.latest_runner import LatestRunner
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import ProgressEntry, RenameCoordinator, VideoFacts

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    KEYS,
    LENGTH_MS,
    LOADED,
    PLAYING,
    RECORD,
    SHORT_MS,
    STOPPED,
    Listing,
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
    list_runner_of,
    load_paused,
    make_view,
    notices,
    path_of,
    picture,
    player_of,
    shown_of,
    sink_of,
    slider_of,
    start_playing,
    still_of,
)

CLEARED = call(QUrl())
"""What a player is told to let go of its video."""


def let_go(media: Media) -> bool:
    """Whether the player's source was last cleared.

    :param media: the patched calls.
    :returns: whether the last source it was given was none.
    """
    return media.set_source.call_args == CLEARED


# region Showing the dock: the video watched last, loaded paused


def test_the_dock_loads_the_video_watched_last_paused_where_it_was_left(
    view: PlayerView,
    media: Media,
    model: RehuDocumentModel,
    progress: dict[str, ProgressEntry],
) -> None:
    """**Test steps:**

    * keep a partial progress for the second video and make it the one watched last
    * load the last video, as showing the dock does
    * verify the second video was opened and paused, never played, and the bar already shows where it will start
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    model.last_video.return_value = "02.mp4"  # type: ignore[attr-defined]

    view.load_last()

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.pause.assert_called_once_with()
    media.play.assert_not_called()
    assert label_text(view, "title_label") == "02.mp4"
    assert (slider_of(view).value(), slider_of(view).maximum()) == (30_000, LENGTH_MS)
    assert label_text(view, "time_label") == "0:30 / 1:40"


@mark.parametrize(
    "last",
    [param(None, id="none watched"), param("gone.mp4", id="the one watched is gone")],
)
def test_the_dock_loads_the_first_video_when_the_one_watched_last_is_not_there(
    view: PlayerView, media: Media, model: RehuDocumentModel, last: str | None
) -> None:
    """**Test steps:**

    * make the video watched last none, or one the tutorial no longer has
    * load the last video
    * verify the first video was loaded
    """
    model.last_video.return_value = last  # type: ignore[attr-defined]

    view.load_last()

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("01.mp4"))))


def test_showing_the_dock_again_does_not_lose_the_place(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * load the last video, then show the dock again
    * verify nothing was opened a second time
    """
    model.last_video.return_value = "02.mp4"  # type: ignore[attr-defined]
    view.load_last()
    media.set_source.reset_mock()

    view.load_last()

    media.set_source.assert_not_called()


def test_a_dock_shown_while_the_videos_are_still_being_listed_asks_for_no_second_list(
    view: PlayerView, media: Media, mocker: MockerFixture
) -> None:
    """A double-click arriving while the dock is still listing overrides it: the video clicked plays, not the last one.

    **Test steps:**

    * load the last video and show the dock again while nothing has answered, then double-click a video
    * verify the list was asked for once for the dock, and once more for the click
    * let the list answer
    * verify the video clicked was played and nothing else opened
    """
    start = mocker.patch.object(LatestRunner, "start")

    view.load_last()
    view.load_last()
    assert start.call_count == 1
    view.jump("03.mp4")
    assert start.call_count == 2
    list_runner_of(view).read.emit("list", list(KEYS))

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("03.mp4"))))
    media.play.assert_called_once_with()


def test_the_videos_are_listed_from_the_record_with_the_settings(view: PlayerView, listing: Listing) -> None:
    """**Test steps:**

    * load the last video
    * verify the list was read for the record's resource, with the extensions and exclusions of the settings
    """
    view.load_last()

    listing.listed.assert_called_once()
    assert listing.listed.call_args.args == (RECORD,)
    assert set(listing.listed.call_args.kwargs) == {"video_extensions", "excluded_patterns"}


def test_the_list_is_kept_for_the_videos_it_holds_and_read_again_for_one_it_does_not(
    view: PlayerView, listing: Listing
) -> None:
    """**Test steps:**

    * load the last video, then jump to another video of the list
    * verify the list was read once
    * add a video to the tutorial and jump to it
    * verify the list was read again
    """
    view.load_last()
    view.jump("02.mp4")
    assert listing.listed.call_count == 1

    listing.keys.append("04.mp4")
    view.jump("04.mp4")

    assert listing.listed.call_count == 2


def test_a_tutorial_with_no_videos_says_so(view: PlayerView, listing: Listing, media: Media) -> None:
    """**Test steps:**

    * list a tutorial with no videos and load the last
    * verify a notice says there are none and nothing was opened
    """
    listing.keys.clear()

    view.load_last()

    assert notices(view) == ["This tutorial has no videos."]
    media.set_source.assert_not_called()


def test_videos_that_cannot_be_listed_are_explained(view: PlayerView, listing: Listing, media: Media) -> None:
    """**Test steps:**

    * make listing the tutorial's videos raise, and load the last
    * verify a notice says they could not be listed, and why, and nothing was opened
    """
    listing.listed.side_effect = OSError("share gone")

    view.load_last()

    assert notices(view) == ["This tutorial's videos could not be listed. share gone"]
    media.set_source.assert_not_called()


def test_a_video_the_tutorial_no_longer_has_is_explained(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * jump to a video that is not in the tutorial
    * verify a notice says it is gone and nothing was opened
    """
    view.jump("gone.mp4")

    assert notices(view) == ["That video is no longer in this tutorial."]
    media.set_source.assert_not_called()


def test_a_document_with_no_file_loads_nothing(
    view: PlayerView, media: Media, model: RehuDocumentModel, listing: Listing
) -> None:
    """**Test steps:**

    * give the document no path and load the last video
    * verify nothing was listed or opened
    """
    model.path = None

    view.load_last()

    listing.listed.assert_not_called()
    media.set_source.assert_not_called()


# endregion

# region Where a video starts


@mark.parametrize(
    ("entry", "start_ms", "clock"),
    [
        param(None, 0, "0:00"),
        param(ProgressEntry(42.5, 100.0), 42_500, "0:42 / 1:40"),
        param(ProgressEntry(99.5, 100.0, viewed=True), 0, "0:00 / 1:40"),
        param(ProgressEntry(10.0, 100.0, viewed=True), 0, "0:00 / 1:40"),
        param(ProgressEntry(99.5, 100.0), 0, "0:00 / 1:40"),
        param(ProgressEntry(30.0, None), 30_000, "0:30"),
    ],
    ids=["never opened", "partly watched", "watched to the end", "viewed by hand", "left at the end", "length unknown"],
)
def test_the_bar_shows_where_playback_will_start_before_anything_opens(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    view: PlayerView,
    model: RehuDocumentModel,
    progress: dict[str, ProgressEntry],
    entry: ProgressEntry | None,
    start_ms: int,
    clock: str,
) -> None:
    """A video watched to the end -- viewed, or left within the end's tolerance of its length -- starts at 0, so it can
    be watched again without dragging the slider back; one with no known length shows its position alone.

    **Test steps:**

    * keep a progress for the video, and load it
    * verify the slider and the clock already show where it will start
    """
    if entry is not None:
        progress["01.mp4"] = entry
    model.last_video.return_value = "01.mp4"  # type: ignore[attr-defined]

    view.load_last()

    assert slider_of(view).value() == (start_ms if "/" in clock else 0)
    assert label_text(view, "time_label") == clock


def test_a_length_the_document_measured_is_the_one_the_bar_shows(
    view: PlayerView, model: RehuDocumentModel, progress: dict[str, ProgressEntry]
) -> None:
    """**Test steps:**

    * keep a progress that saw one length, for a video measured to be another, and load it
    * verify the slider is fitted to the measured one
    """
    progress["01.mp4"] = ProgressEntry(30.0, 100.0)
    model.measured_videos.return_value = {"01.mp4": VideoFacts(50.0)}  # type: ignore[attr-defined]

    view.load_last()

    assert slider_of(view).maximum() == 50_000


# endregion

# region Holding the file: only a video that plays is open


def test_a_video_loaded_paused_is_opened_for_a_frame_and_let_go_of(
    view: PlayerView, media: Media, model: RehuDocumentModel, progress: dict[str, ProgressEntry]
) -> None:
    """The file is open for as long as it takes to buffer and give one frame, then the source is cleared: a loaded video
    holds nothing, so the folder can be renamed (the OS refuses while a video is open in it).

    **Test steps:**

    * keep a partial progress, and load the video as the dock does
    * verify it is open, was sought to where it was left once it buffered, and is still held
    * give the frame at that position
    * verify the player was stopped and its source cleared, the frame is shown, and the bar is unchanged
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    player = load_paused(view, model, "02.mp4")
    media.set_position.assert_called_once_with(30_000)
    assert not let_go(media)

    sink_of(view).videoFrameChanged.emit(picture(30_000))

    assert let_go(media)
    media.stop.assert_called_once_with()
    assert still_of(view).image is not None
    assert shown_of(view) is still_of(view)
    assert slider_of(view).value() == 30_000
    assert player_of(view) is player


def test_a_frame_from_somewhere_else_in_the_video_is_not_the_one_to_show(
    view: PlayerView, media: Media, model: RehuDocumentModel, progress: dict[str, ProgressEntry]
) -> None:
    """The player may give a first frame from before the seek lands: the frame shown is the one at the position.

    **Test steps:**

    * load a video left at 30 s, and give a frame from 0, then one from 30 s
    * verify only the second let the video go
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    load_paused(view, model, "02.mp4")

    sink_of(view).videoFrameChanged.emit(picture(0))
    assert not let_go(media)
    sink_of(view).videoFrameChanged.emit(picture(30_500))

    assert let_go(media)


@mark.parametrize("frame", [param(QVideoFrame(), id="an empty frame"), param(None, id="a frame before it buffered")])
def test_a_load_waits_for_a_real_frame_of_a_buffered_video(
    view: PlayerView, media: Media, model: RehuDocumentModel, frame: QVideoFrame | None
) -> None:
    """**Test steps:**

    * load a video, and give the sink an empty frame, or a good one before the video buffered
    * verify the video was not let go
    """
    if frame is None:
        model.last_video.return_value = "01.mp4"  # type: ignore[attr-defined]
        view.load_last()
        frame = picture()
    else:
        load_paused(view, model, "01.mp4")

    sink_of(view).videoFrameChanged.emit(frame)

    assert not let_go(media)


def test_a_load_that_gives_no_frame_is_let_go_of_all_the_same(
    qtbot: QtBot, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """A video that cannot show a frame -- AV1 with nothing to decode it -- must not be held open for ever.

    **Test steps:**

    * load a video with a short time allowed, and let it buffer but give no frame
    * verify its source was cleared once the time was up
    """
    view = make_view(qtbot, model, recorder, grab_ms=SHORT_MS)
    load_paused(view, model, "01.mp4")

    qtbot.waitUntil(lambda: let_go(media), timeout=2000)


def test_a_video_loaded_for_a_frame_records_nothing_and_does_not_move_the_bar(
    view: PlayerView, model: RehuDocumentModel, recorder: WatchProgressRecorder, progress: dict[str, ProgressEntry]
) -> None:
    """Looking at where a video is must not say it was watched: it leaves progress, and the video watched last, as they
    were.

    **Test steps:**

    * load a video left at 30 s and let the player report positions while it is held for the frame
    * give the frame
    * verify nothing was noted for the recorder and the bar stayed where the video was left
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    player = load_paused(view, model, "02.mp4")
    player.positionChanged.emit(0)
    player.positionChanged.emit(12_000)
    sink_of(view).videoFrameChanged.emit(picture(30_000))
    player.positionChanged.emit(0)

    recorder.position.assert_not_called()  # type: ignore[attr-defined]
    assert slider_of(view).value() == 30_000


def test_stepping_through_the_videos_records_nothing(
    view: PlayerView, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video and step to the next, then back, then to the next
    * verify nothing was ever noted for the recorder
    """
    load_paused(view, model, "02.mp4")
    for name in ("next_action", "previous_action", "next_action"):
        action_of(view, name).trigger()

    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_pausing_lets_go_of_the_file_and_keeps_a_frame_and_the_position(
    view: PlayerView,
    media: Media,
    recorder: WatchProgressRecorder,
) -> None:
    """A paused video holds nothing: where it is is recorded, a frame of it stays on the surface, and the source is
    cleared.

    **Test steps:**

    * play a video, with the player at 33 s and a frame on the sink, and press play/pause
    * verify the position was noted and flushed, the player stopped and its source cleared
    * verify the frame is shown, the bar reads 33 s, and the button offers play
    """
    start_playing(view, "02.mp4")
    sink_of(view).setVideoFrame(picture())
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, "play_pause_action").trigger()

    assert recorder.mock_calls == [call.position("02.mp4", 33.0, 100.0), call.flush()]  # type: ignore[attr-defined]
    assert let_go(media)
    media.stop.assert_called_once_with()
    assert shown_of(view) is still_of(view)
    assert still_of(view).image is not None
    assert (slider_of(view).value(), label_text(view, "time_label")) == (33_000, "0:33 / 1:40")
    assert action_of(view, "play_pause_action").text() == "Play"


def test_playing_again_opens_the_video_where_it_was_paused(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video, pause it at 33 s, and press play
    * verify the video was opened again and played, and sought to 33 s once it buffered, and the video is shown
    """
    player = start_playing(view, "02.mp4")
    media.position.return_value = 33_000
    action_of(view, "play_pause_action").trigger()
    media.set_source.reset_mock()
    media.set_position.reset_mock()
    media.play.reset_mock()

    action_of(view, "play_pause_action").trigger()
    player.mediaStatusChanged.emit(BUFFERED)

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_called_once_with()
    media.set_position.assert_called_once_with(33_000)
    assert shown_of(view) is not still_of(view)
    assert action_of(view, "play_pause_action").text() == "Play"


def test_playing_a_video_still_held_for_its_frame_carries_on_without_opening_it_again(
    view: PlayerView, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video, held for its frame, and press play before the frame came
    * verify it was played without being opened a second time, the video is shown, and its positions are now recorded
    """
    player = load_paused(view, model, "02.mp4")

    action_of(view, "play_pause_action").trigger()
    player.playbackStateChanged.emit(PLAYING)
    player.positionChanged.emit(5_000)

    media.set_source.assert_called_once()
    media.play.assert_called_once_with()
    assert shown_of(view) is not still_of(view)
    recorder.position.assert_called_once_with("02.mp4", 5.0, 100.0)  # type: ignore[attr-defined]


def test_a_frame_arriving_after_play_was_pressed_does_not_let_the_video_go(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * load a video, press play, and give the frame a load waits for
    * verify the video was not let go
    """
    load_paused(view, model, "01.mp4")
    action_of(view, "play_pause_action").trigger()

    sink_of(view).videoFrameChanged.emit(picture())

    assert not let_go(media)


def test_playing_a_video_that_was_let_go_of_opens_it_from_the_records_path_as_it_is_now(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """A rename moves the folder under a video that is paused: pressing play opens it at its new place.

    **Test steps:**

    * load a video and let it go, then move the document to another folder
    * press play
    * verify the video was opened under the new folder
    """
    load_paused(view, model, "02.mp4")
    sink_of(view).videoFrameChanged.emit(picture())
    model.path = Path.cwd() / "fake" / "renamed" / "info.rehu"

    action_of(view, "play_pause_action").trigger()

    media.set_source.assert_called_with(QUrl.fromLocalFile(str(Path.cwd() / "fake" / "renamed" / "02.mp4")))


# endregion

# region Playing a video


def test_jumping_to_a_video_plays_it_from_where_it_was_left(
    view: PlayerView, media: Media, progress: dict[str, ProgressEntry]
) -> None:
    """**Test steps:**

    * keep a partial progress for the second video and jump to it, as a double-click does
    * verify it was opened and played, the video is shown, and it is sought to where it was left once it buffers
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)

    player = start_playing(view, "02.mp4")

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_called_once_with()
    media.pause.assert_not_called()
    media.set_position.assert_called_once_with(30_000)
    assert shown_of(view) is not still_of(view)
    assert label_text(view, "title_label") == "02.mp4"
    assert player_of(view) is player


def test_the_player_is_built_on_the_first_video_and_reused_by_the_next(view: PlayerView) -> None:
    """Opening a tutorial must not load FFmpeg, and a second video is the same player pointed elsewhere.

    **Test steps:**

    * look for a player before anything is selected
    * jump to a video, then to another
    * verify there was none, and then exactly one
    """
    assert view.findChild(QMediaPlayer) is None

    view.jump("01.mp4")
    first = player_of(view)
    view.jump("02.mp4")

    assert view.findChildren(QMediaPlayer) == [first]


def test_a_double_click_gives_the_player_the_keyboard(view: PlayerView, mocker: MockerFixture) -> None:
    """The keys are armed by focus inside the player, so a video started from the Files dock must hand it the keyboard.

    **Test steps:**

    * jump to a video
    * verify the player was given the focus
    """
    set_focus = mocker.patch.object(PlayerView, "setFocus")

    view.jump("01.mp4")

    set_focus.assert_called_once()


def test_a_position_is_recorded_with_the_length_while_a_video_plays(
    view: PlayerView, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video and report a position
    * verify the recorder got the video's key, the position in seconds and the length in seconds
    """
    player = start_playing(view, "02.mp4")

    player.positionChanged.emit(12_500)

    recorder.position.assert_called_once_with("02.mp4", 12.5, 100.0)  # type: ignore[attr-defined]


def test_a_position_is_recorded_with_no_length_while_the_length_is_not_known(
    view: PlayerView, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video the player never reports a length for, and report a position
    * verify the recorder was given no length rather than 0
    """
    player = start_playing(view, "01.mp4", length_ms=0)

    player.positionChanged.emit(2_000)

    recorder.position.assert_called_once_with("01.mp4", 2.0, None)  # type: ignore[attr-defined]


def test_the_length_is_read_as_the_video_buffers_when_the_player_reports_no_change(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """Found by opening a video a second time: the player reports no ``durationChanged`` for a source as long as the one
    before it, so a length taken only from that signal was lost and the video recorded with none.

    **Test steps:**

    * play a video whose length the player knows once it buffers, without ever reporting a change
    * report a position
    * verify the recorder was given the length, and the slider was fitted to it
    """
    media.duration.return_value = LENGTH_MS
    view.jump("01.mp4")
    player = player_of(view)
    player.playbackStateChanged.emit(PLAYING)
    player.mediaStatusChanged.emit(BUFFERED)

    player.positionChanged.emit(2_000)

    recorder.position.assert_called_once_with("01.mp4", 2.0, 100.0)  # type: ignore[attr-defined]
    assert slider_of(view).maximum() == LENGTH_MS


def test_a_position_before_the_video_has_buffered_is_no_progress(
    view: PlayerView, recorder: WatchProgressRecorder
) -> None:
    """A player reports 0 as it starts a new source: written, that would erase the resume point before it is applied.

    **Test steps:**

    * play a video that has not buffered and report position 0
    * verify nothing was noted for the recorder
    """
    view.jump("01.mp4")

    player_of(view).positionChanged.emit(0)

    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_a_position_after_the_player_stopped_is_no_progress(view: PlayerView, recorder: WatchProgressRecorder) -> None:
    """A stop, or the end of a video, resets the position: reported afterwards it must not overwrite where the reader
    got to.

    **Test steps:**

    * play a video, and let the player stop
    * report position 0
    * verify nothing was noted for the recorder
    """
    player = start_playing(view)
    player.playbackStateChanged.emit(STOPPED)
    recorder.reset_mock()  # type: ignore[attr-defined]

    player.positionChanged.emit(0)

    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_a_status_left_over_from_the_video_a_source_replaces_is_not_the_new_video_being_ready(
    view: PlayerView, media: Media, progress: dict[str, ProgressEntry], recorder: WatchProgressRecorder
) -> None:
    """Found by playing real clips: replacing a source makes the player report ``LoadedMedia`` from inside
    ``setSource``, for the video it is replacing. A resume seek made on that, or a position taken for the new video's,
    is lost or wrong.

    **Test steps:**

    * keep a partial progress, and play a video whose ``setSource`` reports ``LoadedMedia`` as Qt does
    * verify nothing was sought, and a position the player reports is not recorded
    * let the video buffer
    * verify it was sought once, after it was told to play
    """
    progress["01.mp4"] = ProgressEntry(30.0, 100.0)
    calls = Mock()
    calls.attach_mock(media.play, "play")
    calls.attach_mock(media.set_position, "set_position")
    media.set_source.side_effect = lambda _url: player_of(view).mediaStatusChanged.emit(LOADED)

    view.jump("01.mp4")
    player = player_of(view)
    player.playbackStateChanged.emit(PLAYING)
    player.positionChanged.emit(0)

    media.set_position.assert_not_called()
    recorder.position.assert_not_called()  # type: ignore[attr-defined]

    player.mediaStatusChanged.emit(BUFFERED)
    player.mediaStatusChanged.emit(BUFFERED)

    assert calls.mock_calls == [call.play(), call.set_position(30_000)]


def test_the_slider_and_the_clock_follow_the_position(view: PlayerView) -> None:
    """**Test steps:**

    * play a video of 100 s and report a position
    * verify the slider ranges over the length and sits at the position, and the clock reads both
    """
    player = start_playing(view)

    player.positionChanged.emit(65_000)

    assert (slider_of(view).minimum(), slider_of(view).maximum()) == (0, LENGTH_MS)
    assert slider_of(view).value() == 65_000
    assert label_text(view, "time_label") == "1:05 / 1:40"


def test_the_clock_spells_hours_once_a_video_is_that_long(view: PlayerView) -> None:
    """**Test steps:**

    * play a video of two hours and report a position of one hour, two minutes, five seconds
    * verify the clock carries hours
    """
    player = start_playing(view, length_ms=7_200_000)

    player.positionChanged.emit(3_725_000)

    assert label_text(view, "time_label") == "1:02:05 / 2:00:00"


def test_the_play_button_shows_what_pressing_it_does(view: PlayerView) -> None:
    """**Test steps:**

    * read the play action's text with nothing playing, while a video plays, and after it was paused
    * verify it says *Play*, *Pause*, *Play*
    """
    action = action_of(view, "play_pause_action")
    assert action.text() == "Play"

    start_playing(view)
    assert action.text() == "Pause"

    action.trigger()
    assert action.text() == "Play"


def test_pressing_play_on_a_video_that_is_loading_pauses_it(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * jump to a video that has not started playing and press play/pause
    * verify it was let go of rather than left opening
    """
    view.jump("01.mp4")

    action_of(view, "play_pause_action").trigger()

    assert let_go(media)


# endregion

# region Stepping: previous and next load paused


def test_previous_and_next_load_the_neighbour_paused_where_it_was_left_or_at_the_start(
    view: PlayerView, media: Media, progress: dict[str, ProgressEntry]
) -> None:
    """**Test steps:**

    * keep a partial progress for the second video and a viewed one for the third
    * play the first, and step to the second, the third, and back to the second
    * verify each was opened and paused, never played, the second at its position, the third at the start
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    progress["03.mp4"] = ProgressEntry(95.0, 100.0, viewed=True)
    start_playing(view, "01.mp4")
    media.play.reset_mock()
    media.pause.reset_mock()

    action_of(view, "next_action").trigger()
    assert (slider_of(view).value(), label_text(view, "title_label")) == (30_000, "02.mp4")
    action_of(view, "next_action").trigger()
    assert (slider_of(view).value(), label_text(view, "title_label")) == (0, "03.mp4")
    action_of(view, "previous_action").trigger()
    assert (slider_of(view).value(), label_text(view, "title_label")) == (30_000, "02.mp4")

    media.play.assert_not_called()
    assert media.pause.call_count == 3
    assert media.set_source.call_args == call(QUrl.fromLocalFile(str(path_of("02.mp4"))))


def test_stepping_off_a_video_that_plays_records_where_it_was_first(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play the first video with the player at 33 s, and step to the next
    * verify the first's position was noted and flushed before the next was made the source
    """
    start_playing(view, "01.mp4")
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()

    action_of(view, "next_action").trigger()

    expected = [call.position("01.mp4", 33.0, 100.0), call.flush()]
    assert recorder.mock_calls[:2] == expected  # type: ignore[attr-defined]
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))


def test_the_actions_wait_for_a_video_and_follow_the_ends_of_the_playlist(view: PlayerView) -> None:
    """Prev and next stop at both ends, so at an end the action is off and its key does nothing.

    **Test steps:**

    * look at the actions with nothing selected
    * select the middle video, then the first, then the last
    * verify all are off at first, all on in the middle, no previous at the first and no next at the last
    """
    names = (
        "play_pause_action",
        "back_action",
        "forward_action",
        "previous_action",
        "next_action",
        "to_start_action",
        "to_end_action",
    )
    assert [action_of(view, name).isEnabled() for name in names] == [False] * 7

    view.jump("02.mp4")
    assert [action_of(view, name).isEnabled() for name in names] == [True] * 7

    view.jump("01.mp4")
    assert action_of(view, "previous_action").isEnabled() is False
    assert action_of(view, "next_action").isEnabled() is True

    view.jump("03.mp4")
    assert action_of(view, "previous_action").isEnabled() is True
    assert action_of(view, "next_action").isEnabled() is False


def test_stepping_off_the_ends_does_nothing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * select the last video and ask for the next, as the end of the list leaves nothing to step to
    * verify nothing was opened
    """
    view.jump("03.mp4")
    media.set_source.reset_mock()

    action_of(view, "next_action").trigger()

    media.set_source.assert_not_called()


# endregion

# region The end of a video, to the start, to the end


def test_reaching_the_end_records_the_whole_video_and_loads_the_next_paused(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """The full length is what makes the recorder mark the video viewed; the next video is loaded, not played.

    **Test steps:**

    * play the first video and let it reach its end
    * verify its whole length was noted and flushed, and the second was opened and paused, not played
    """
    player = start_playing(view, "01.mp4")
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()
    media.play.reset_mock()

    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    expected = [call.position("01.mp4", 100.0, 100.0), call.flush()]
    assert recorder.mock_calls[:2] == expected  # type: ignore[attr-defined]
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_not_called()
    media.pause.assert_called()
    assert label_text(view, "title_label") == "02.mp4"


def test_the_last_video_ending_stops_the_playback_and_lets_go_of_its_file(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """The last video is the end of the list: nothing wraps round to the first, and with nothing left to play the file
    is let go, so the folder can be renamed (the OS refuses while a video is open in it).

    **Test steps:**

    * play the last video and let it reach its end
    * verify it was recorded as watched, with no position of the reset the stop reports
    * verify the source was cleared and the player shows nothing
    """
    player = start_playing(view, "03.mp4")
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()

    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    expected = [call.position("03.mp4", 100.0, 100.0), call.flush(), call.flush()]
    assert recorder.mock_calls == expected  # type: ignore[attr-defined]
    media.set_source.assert_called_once_with(QUrl())
    assert label_text(view, "title_label") == ""
    assert action_of(view, "play_pause_action").isEnabled() is False


def test_an_end_of_a_video_of_unknown_length_claims_nothing(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """With no length there is no position that is the end, so nothing is claimed; the next video still loads.

    **Test steps:**

    * play a video the player never reported a length for, and let it end
    * verify no position was noted, and the next video was opened
    """
    player = start_playing(view, "01.mp4", length_ms=0)
    media.set_source.reset_mock()

    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    recorder.position.assert_not_called()  # type: ignore[attr-defined]
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))


def test_the_end_of_a_video_that_is_only_loaded_is_not_the_end_of_anything(
    view: PlayerView, model: RehuDocumentModel, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video paused and have the player report an end of media
    * verify nothing was recorded and nothing else opened
    """
    player = load_paused(view, model, "01.mp4")
    media.set_source.reset_mock()

    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    recorder.position.assert_not_called()  # type: ignore[attr-defined]
    media.set_source.assert_not_called()


def test_a_status_that_is_neither_buffered_nor_the_end_changes_nothing(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video and let the player report that it is stalled
    * verify nothing was sought, noted or played
    """
    view.jump("03.mp4")
    media.set_source.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    player_of(view).mediaStatusChanged.emit(QMediaPlayer.MediaStatus.StalledMedia)

    assert recorder.mock_calls == []  # type: ignore[attr-defined]
    media.set_position.assert_not_called()
    media.set_source.assert_not_called()


def test_to_the_end_finishes_a_video_that_was_only_looked_at(
    view: PlayerView, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """A key that jumps to the end marks a video watched even if it never played, and moves on.

    **Test steps:**

    * load a video paused, let it go, and press to-the-end
    * verify its whole length was noted and flushed, and the next video was loaded paused
    """
    load_paused(view, model, "01.mp4")
    sink_of(view).videoFrameChanged.emit(picture())
    media.set_source.reset_mock()
    media.play.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, "to_end_action").trigger()

    expected = [call.position("01.mp4", 100.0, 100.0), call.flush()]
    assert recorder.mock_calls[:2] == expected  # type: ignore[attr-defined]
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_not_called()


def test_to_the_start_moves_a_playing_video_to_0_and_records_it(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video and press to-the-start
    * verify the player was sought to 0 and the position noted and flushed
    """
    start_playing(view)
    media.set_position.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, "to_start_action").trigger()

    media.set_position.assert_called_once_with(0)
    assert recorder.mock_calls == [call.position("01.mp4", 0.0, 100.0), call.flush()]  # type: ignore[attr-defined]


def test_to_the_start_of_a_video_not_playing_moves_the_bar_and_opens_nothing(
    view: PlayerView,
    media: Media,
    model: RehuDocumentModel,
    progress: dict[str, ProgressEntry],
    recorder: WatchProgressRecorder,
) -> None:
    """**Test steps:**

    * load a video left at 30 s, let it go, and press to-the-start
    * verify the bar reads 0, the player was not asked to seek, and nothing was recorded
    """
    progress["01.mp4"] = ProgressEntry(30.0, 100.0)
    load_paused(view, model, "01.mp4")
    sink_of(view).videoFrameChanged.emit(picture(30_000))
    media.set_position.reset_mock()

    action_of(view, "to_start_action").trigger()

    assert slider_of(view).value() == 0
    media.set_position.assert_not_called()
    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_pressing_play_on_a_video_held_for_its_frame_before_it_buffers_waits_for_the_buffer(
    view: PlayerView, media: Media, model: RehuDocumentModel, progress: dict[str, ProgressEntry]
) -> None:
    """**Test steps:**

    * load a video left at 30 s, and press play before it buffered
    * verify it was played without being sought yet
    * let it buffer
    * verify it was sought to where it was left
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    model.last_video.return_value = "02.mp4"  # type: ignore[attr-defined]
    view.load_last()
    action_of(view, "play_pause_action").trigger()
    media.play.assert_called_once_with()
    media.set_position.assert_not_called()

    player_of(view).mediaStatusChanged.emit(BUFFERED)

    media.set_position.assert_called_once_with(30_000)


def test_a_second_frame_of_a_playing_video_changes_nothing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video and give two frames
    * verify the video was not let go
    """
    start_playing(view)

    sink_of(view).videoFrameChanged.emit(picture())
    sink_of(view).videoFrameChanged.emit(picture())

    assert not let_go(media)


def test_a_length_reported_after_the_view_stopped_is_ignored(view: PlayerView) -> None:
    """**Test steps:**

    * play a video, stop the view, and have the player report a length
    * verify the slider was not fitted to it
    """
    player = start_playing(view)
    view.stop()

    player.durationChanged.emit(50_000)

    assert slider_of(view).maximum() == 0


# endregion

# region Seeking


@mark.parametrize(
    ("name", "start", "expected"),
    [
        param("back_action", 20_000, 15_000, id="back"),
        param("forward_action", 20_000, 25_000, id="forward"),
        param("back_action", 2_000, 0, id="back stops at the start"),
        param("forward_action", 98_000, LENGTH_MS, id="forward stops at the end"),
    ],
)
def test_back_and_forward_jump_five_seconds_within_the_video_and_record_it_at_once(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    view: PlayerView, media: Media, recorder: WatchProgressRecorder, name: str, start: int, expected: int
) -> None:
    """**Test steps:**

    * play a video of 100 s with the player at a position and trigger back or forward
    * verify the player was moved five seconds, held within the video, and the new position was noted and flushed
    """
    start_playing(view)
    media.position.return_value = start
    media.set_position.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, name).trigger()

    media.set_position.assert_called_once_with(expected)
    noted = [call.position("01.mp4", expected / 1000, 100.0), call.flush()]
    assert recorder.mock_calls == noted  # type: ignore[attr-defined]


def test_a_seek_in_a_video_of_unknown_length_is_not_held_to_an_end(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video the player never reported a length for, and jump five seconds forward
    * verify the player was sought there, and the position noted with no length
    """
    start_playing(view, length_ms=0)
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, "forward_action").trigger()

    media.set_position.assert_called_with(5_000)
    assert recorder.mock_calls[0] == call.position("01.mp4", 5.0, None)  # type: ignore[attr-defined]


def test_seeking_a_video_not_playing_moves_the_bar_alone(
    view: PlayerView,
    media: Media,
    model: RehuDocumentModel,
    progress: dict[str, ProgressEntry],
    recorder: WatchProgressRecorder,
) -> None:
    """Nothing is opened to seek: playing starts from wherever the bar was left.

    **Test steps:**

    * load a video left at 30 s, let it go, and jump five seconds forward
    * verify the bar reads 35 s, the player was not asked to seek, and nothing was recorded
    """
    progress["01.mp4"] = ProgressEntry(30.0, 100.0)
    load_paused(view, model, "01.mp4")
    sink_of(view).videoFrameChanged.emit(picture(30_000))
    media.set_position.reset_mock()

    action_of(view, "forward_action").trigger()

    assert slider_of(view).value() == 35_000
    media.set_position.assert_not_called()
    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_seeking_a_video_that_has_played_records_the_new_position_though_it_is_paused(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """A reader who pauses and then drags the bar expects the video to come back where they left the bar.

    **Test steps:**

    * play a video, pause it at 33 s, and jump five seconds forward
    * verify the new position was noted and flushed, and the player was not asked to seek
    """
    start_playing(view)
    media.position.return_value = 33_000
    action_of(view, "play_pause_action").trigger()
    media.set_position.reset_mock()
    recorder.reset_mock()  # type: ignore[attr-defined]

    action_of(view, "forward_action").trigger()

    assert recorder.mock_calls == [call.position("01.mp4", 38.0, 100.0), call.flush()]  # type: ignore[attr-defined]
    media.set_position.assert_not_called()


def test_dragging_the_slider_seeks_only_when_it_is_let_go(view: PlayerView, media: Media) -> None:
    """While it is held the slider is the reader's and must not jump back to the playing position.

    **Test steps:**

    * play a video, press the slider, move it, and report a position meanwhile
    * verify the slider kept the reader's place and nothing was sought
    * release it
    * verify the player was sought to where it was let go
    """
    player = start_playing(view)
    slider = slider_of(view)
    media.set_position.reset_mock()

    slider.sliderPressed.emit()
    slider.setSliderPosition(60_000)
    player.positionChanged.emit(10_000)
    assert slider.sliderPosition() == 60_000
    media.set_position.assert_not_called()

    slider.setValue(60_000)
    slider.sliderReleased.emit()

    media.set_position.assert_called_once_with(60_000)


def test_a_click_on_the_slider_groove_seeks(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video and page the slider on, as a click beside its handle does
    * verify the player was sought to the new position
    """
    start_playing(view)
    media.set_position.reset_mock()

    slider_of(view).triggerAction(slider_of(view).SliderAction.SliderPageStepAdd)

    media.set_position.assert_called_once_with(30_000)


def test_a_seek_with_nothing_selected_does_nothing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * release the slider of a view with nothing selected
    * verify nothing was sought
    """
    slider_of(view).sliderReleased.emit()

    media.set_position.assert_not_called()


# endregion

# region Pausing for a rename


def test_a_video_held_open_listens_for_a_rename_and_stops_when_it_is_let_go(
    view: PlayerView, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * play a video, then press pause
    * verify the player asked to be told of renames once, and stopped asking once the file was let go
    """
    start_playing(view)
    coordinator.add_before_rename_listener.assert_called_once()  # type: ignore[attr-defined]
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]
    coordinator.remove_before_rename_listener.assert_not_called()  # type: ignore[attr-defined]

    action_of(view, "play_pause_action").trigger()

    coordinator.remove_before_rename_listener.assert_called_once_with(listener)  # type: ignore[attr-defined]


def test_playing_a_video_held_for_its_frame_does_not_ask_twice(
    view: PlayerView, model: RehuDocumentModel, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * load a video held for a frame, then press play
    * verify the player asked to be told of renames once
    """
    load_paused(view, model, "01.mp4")

    action_of(view, "play_pause_action").trigger()

    coordinator.add_before_rename_listener.assert_called_once()  # type: ignore[attr-defined]


def test_a_rename_of_this_resource_pauses_a_playing_video_first(
    view: PlayerView, media: Media, coordinator: RenameCoordinator, recorder: WatchProgressRecorder
) -> None:
    """The OS refuses to rename a folder with a video open in it: the video is paused, which lets go of its file, and
    stays paused where it was.

    **Test steps:**

    * play a video at 33 s, and have the coordinator say this resource is about to be renamed
    * verify the position was recorded, the file let go of, and the bar still reads 33 s
    """
    start_playing(view, "02.mp4")
    sink_of(view).setVideoFrame(picture())
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(RECORD)  # pylint: disable=not-callable

    assert recorder.mock_calls == [call.position("02.mp4", 33.0, 100.0), call.flush()]  # type: ignore[attr-defined]
    assert let_go(media)
    assert shown_of(view) is still_of(view)
    assert slider_of(view).value() == 33_000


def test_a_rename_of_another_resource_leaves_the_video_playing(
    view: PlayerView, media: Media, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * play a video, and have the coordinator say another resource is about to be renamed
    * verify the video was not let go of
    """
    start_playing(view)
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(Path.cwd() / "fake" / "other" / "info.rehu")  # pylint: disable=not-callable

    assert not let_go(media)


def test_a_rename_of_this_resource_lets_go_of_a_video_held_only_for_its_frame(
    view: PlayerView, media: Media, model: RehuDocumentModel, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * load a video held for a frame, and have the coordinator say this resource is about to be renamed
    * verify the file was let go of, and the video is still the one selected
    """
    load_paused(view, model, "02.mp4")
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]

    listener(RECORD)  # pylint: disable=not-callable

    assert let_go(media)
    assert label_text(view, "title_label") == "02.mp4"


def test_a_rename_with_nothing_held_does_nothing(
    view: PlayerView, media: Media, model: RehuDocumentModel, coordinator: RenameCoordinator
) -> None:
    """**Test steps:**

    * load a video and let it go, then have the coordinator report a rename of this resource to a held listener
    * verify nothing was opened or cleared again
    """
    load_paused(view, model, "02.mp4")
    sink_of(view).videoFrameChanged.emit(picture())
    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]
    media.set_source.reset_mock()

    listener(RECORD)  # pylint: disable=not-callable

    media.set_source.assert_not_called()


def test_a_document_renamed_without_a_coordinator_plays_all_the_same(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * give the document no coordinator and play a video, then pause it
    * verify it played, and nothing raised
    """
    model.rename_coordinator = None  # type: ignore[assignment]

    start_playing(view)
    action_of(view, "play_pause_action").trigger()

    media.play.assert_called_once_with()


# endregion

# region Stopping


def test_stopping_records_where_the_video_was_lets_go_of_its_file_and_shows_nothing(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """The OS refuses to rename a folder with a video open in it, and even a stopped player holds its source: found by
    renaming a folder under a stopped player. Stopping clears the source and returns the view to showing nothing.

    **Test steps:**

    * play a video with the player at 33 s, and stop the view
    * verify the position was noted and flushed, the source was cleared, and the title, the clock and every action are
      gone
    """
    start_playing(view, "02.mp4")
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]

    view.stop()

    assert recorder.mock_calls == [call.position("02.mp4", 33.0, 100.0), call.flush()]  # type: ignore[attr-defined]
    assert let_go(media)
    media.stop.assert_called_once_with()
    assert label_text(view, "title_label") == ""
    assert label_text(view, "time_label") == "0:00"
    assert notices(view) == []
    names = ("play_pause_action", "back_action", "forward_action", "previous_action", "next_action")
    assert [action_of(view, name).isEnabled() for name in names] == [False] * 5
    assert (slider_of(view).minimum(), slider_of(view).maximum()) == (0, 0)


def test_the_position_a_stop_resets_to_is_no_progress_even_when_it_is_reported_first(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """Qt reports the position it resets to (0) from inside ``stop()``, **ahead of** the state it ends in -- found by
    playing a real clip and stopping it: that 0 was recorded as where the reader got to, and written over it.

    **Test steps:**

    * play a video with the player at 33 s, and make the player's ``stop`` report as Qt does: position 0, then the
      stopped state
    * stop the view
    * verify the recorder was given the 33 s and flushes, and never a position of 0
    """
    player = start_playing(view, "02.mp4")
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]

    def stop_as_qt_does() -> None:
        player.positionChanged.emit(0)
        player.playbackStateChanged.emit(STOPPED)

    media.stop.side_effect = stop_as_qt_does

    view.stop()

    expected = [call.position("02.mp4", 33.0, 100.0), call.flush()]
    assert recorder.mock_calls == expected  # type: ignore[attr-defined]


def test_stopping_a_view_that_never_played_only_flushes(view: PlayerView, recorder: WatchProgressRecorder) -> None:
    """**Test steps:**

    * stop a view that has opened nothing
    * verify only a flush reached the recorder
    """
    view.stop()

    assert recorder.mock_calls == [call.flush()]  # type: ignore[attr-defined]


def test_stopping_lets_go_of_a_video_held_for_its_frame(
    view: PlayerView, media: Media, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * load a video held for a frame, and stop the view
    * verify the source was cleared and nothing was recorded
    """
    load_paused(view, model, "01.mp4")

    view.stop()

    assert let_go(media)
    recorder.position.assert_not_called()  # type: ignore[attr-defined]


def test_after_stopping_the_dock_shown_again_loads_the_video_watched_last(
    view: PlayerView, media: Media, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * load the last video, stop the view, and load the last video again
    * verify it was opened a second time
    """
    model.last_video.return_value = "02.mp4"  # type: ignore[attr-defined]
    view.load_last()
    view.stop()
    media.set_source.reset_mock()

    view.load_last()

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))


def test_a_list_that_arrives_after_the_player_stopped_selects_nothing(
    view: PlayerView, media: Media, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * ask for the last video while nothing answers, stop the view, and let the list arrive late
    * verify no video was opened
    """
    mocker.patch.object(LatestRunner, "start")
    view.load_last()
    view.stop()

    list_runner_of(view).read.emit("list", list(KEYS))

    media.set_source.assert_not_called()


def test_a_stopped_player_is_stopped_before_it_is_told(view: PlayerView) -> None:
    """**Test steps:**

    * play a video, stop the view, and have the player report a position after
    * verify the position is not shown
    """
    player = start_playing(view)
    view.stop()

    player.positionChanged.emit(50_000)

    assert slider_of(view).value() == 0


# endregion

# region Switching video while one plays


def test_switching_video_records_the_one_left_before_the_next_is_opened(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play a video with the player at 33 s, and jump to another
    * verify the first's position was noted and flushed before the second was made the source
    """
    start_playing(view, "01.mp4")
    media.position.return_value = 33_000
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()

    view.jump("03.mp4")

    assert recorder.mock_calls[:2] == [call.position("01.mp4", 33.0, 100.0), call.flush()]  # type: ignore[attr-defined]
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("03.mp4"))))


# endregion


def _unused(_: QAction) -> None:  # pragma: no cover
    """Keep an import the helpers share from reading as unused."""
