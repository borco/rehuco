"""Tests for what the player says about the video it has selected, and for starting one at a given time (#572).

The video tree marks the player's video from ``video_changed`` and plays a bookmark through ``jump(key, position)``;
the player's own loading, holding and recording are ``test_player_view``'s.
"""

from PySide6.QtCore import QUrl
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import ProgressEntry

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    LENGTH_MS,
    PLAYING,
    Media,
    action_of,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    fixture_view,  # noqa: F401
    load_paused,
    path_of,
    player_of,
    slider_of,
    start_playing,
)


def test_the_player_says_which_video_it_selected_and_that_it_selected_none(view: PlayerView, qtbot: QtBot) -> None:
    """**Test steps:**

    * verify no video is current, then jump to one and verify it was reported and is current
    * step to the next and verify that was reported
    * stop and verify none was reported and none is current
    """
    assert view.current_key is None

    with qtbot.waitSignal(view.video_changed) as jumped:
        start_playing(view, "01.mp4")
    assert (jumped.args, view.current_key) == (["01.mp4"], "01.mp4")

    with qtbot.waitSignal(view.video_changed) as stepped:
        action_of(view, "next_action").trigger()
    assert (stepped.args, view.current_key) == (["02.mp4"], "02.mp4")

    with qtbot.waitSignal(view.video_changed) as stopped:
        view.stop()
    assert (stopped.args, view.current_key) == ([None], None)


def test_a_dock_shown_loads_the_last_video_and_says_so(
    view: PlayerView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * show the dock, which loads the video watched last
    * verify it was reported
    """
    with qtbot.waitSignal(view.video_changed) as loaded:
        load_paused(view, model, "02.mp4")

    assert loaded.args == ["02.mp4"]


def test_a_jump_with_a_position_starts_there_instead_of_where_the_video_was_left(
    view: PlayerView, media: Media, progress: dict[str, ProgressEntry]
) -> None:
    """**Test steps:**

    * keep a partial progress for the second video and jump to it at 65 seconds
    * verify it was opened and played, and it was sought to 65 seconds -- not 30 -- once it buffered
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)

    view.jump("02.mp4", 65.0)
    player = player_of(view)
    player.durationChanged.emit(LENGTH_MS)
    player.playbackStateChanged.emit(PLAYING)
    player.mediaStatusChanged.emit(BUFFERED)

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_called_once_with()
    media.set_position.assert_called_once_with(65_000)
    assert slider_of(view).value() == 65_000


def test_a_jump_to_the_video_already_playing_seeks_it_without_opening_it_again(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play the first video, then jump to it at 40 seconds
    * verify the player was sought to 40 seconds, and its source was not set again
    """
    start_playing(view, "01.mp4")
    media.set_position.reset_mock()
    media.set_source.reset_mock()

    view.jump("01.mp4", 40.0)

    media.set_position.assert_called_with(40_000)
    media.set_source.assert_not_called()


def test_a_jump_to_the_video_loaded_paused_plays_it_from_the_time(
    view: PlayerView, model: RehuDocumentModel, media: Media
) -> None:
    """**Test steps:**

    * load the second video paused, then jump to it at 20 seconds
    * verify the bar moved to 20 seconds and the player was told to play
    """
    load_paused(view, model, "02.mp4")
    media.play.reset_mock()

    view.jump("02.mp4", 20.0)

    assert slider_of(view).value() == 20_000
    media.play.assert_called_once_with()
