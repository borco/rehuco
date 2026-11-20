"""Tests for the in-app video player's continuous-play button (#693).

What a video's end does with it on is ``test_player_view``'s; here it is off, and the button itself.
"""

from unittest.mock import call

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QToolButton
from pytest_mock import MockerFixture
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.videos_settings import shared_videos_settings

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    LENGTH_MS,
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
    path_of,
    show_first_frame,
    shown_of,
    slider_of,
    start_playing,
    still_of,
)


def button_of(view: PlayerView) -> QToolButton:
    """The view's continuous-play button.

    :param view: the view.
    :returns: the button.
    """
    button = view.findChild(QToolButton, "continuous_play_button")
    assert button is not None
    return button


def test_the_button_is_checked_by_default_and_follows_the_setting(view: PlayerView) -> None:
    """**Test steps:**

    * build a player with the default settings
    * verify the button is checkable and checked, and shows its icon
    * turn the setting off and select a video, as another document's player would have left it
    * verify the button is unchecked
    """
    assert not button_of(view).icon().isNull()
    assert button_of(view).isCheckable()
    assert button_of(view).isChecked()

    shared_videos_settings().continuous_play = False
    view.jump("01.mp4")

    assert not button_of(view).isChecked()


def test_toggling_the_button_keeps_the_setting_once_per_change(view: PlayerView, mocker: MockerFixture) -> None:
    """**Test steps:**

    * uncheck the button, then check it again
    * verify the setting followed each time and was saved once for each
    * check the already checked button
    * verify nothing more was saved
    """
    saved = mocker.patch.object(videos_settings.VideosSettings, "save")

    button_of(view).setChecked(False)
    assert shared_videos_settings().continuous_play is False
    button_of(view).setChecked(True)
    assert shared_videos_settings().continuous_play is True
    button_of(view).setChecked(True)

    assert saved.call_count == 2


def end_with_continuous_play_off(view: PlayerView, media: Media) -> QMediaPlayer:
    """Uncheck the button, play the first video with a frame shown, and let it reach its end; forget the calls so far.

    :param view: the view.
    :param media: the patched player calls.
    :returns: the player.
    """
    button_of(view).setChecked(False)
    player = start_playing(view, "01.mp4")
    show_first_frame(view)
    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
    for mock in (media.set_source, media.set_position, media.play):
        mock.reset_mock()
    return player


def test_the_end_of_a_video_stops_it_where_it_is_when_continuous_play_is_off(
    view: PlayerView, media: Media, recorder: WatchProgressRecorder
) -> None:
    """The finished video is recorded as watched all the same, and stays selected: its file let go, its last frame
    shown and the bar at its end, so it can be taken back anywhere in it.

    **Test steps:**

    * uncheck the button, play the first video and let it reach its end
    * verify its whole length was noted and flushed, its file let go and no video played
    * verify it is still the video shown, on its frame, the bar at its end and the transport enabled
    """
    button_of(view).setChecked(False)
    player = start_playing(view, "01.mp4")
    show_first_frame(view)
    recorder.reset_mock()  # type: ignore[attr-defined]
    media.set_source.reset_mock()
    media.play.reset_mock()

    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)

    expected = [call.position("01.mp4", 100.0, 100.0), call.flush()]
    assert recorder.mock_calls[:2] == expected  # type: ignore[attr-defined]
    media.set_source.assert_called_once_with(QUrl())
    media.play.assert_not_called()
    assert label_text(view, "title_label") == "01.mp4"
    assert view.current_key == "01.mp4"
    assert shown_of(view) is not still_of(view)
    assert slider_of(view).value() == LENGTH_MS
    assert action_of(view, "play_pause_action").isEnabled()
    assert action_of(view, "play_pause_action").text() == "Play"
    assert action_of(view, "next_action").isEnabled()


def test_play_on_a_video_stopped_at_its_end_plays_it_again_from_the_start(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * let a video end with continuous play off, and press play
    * verify the same video was opened and played, and not sought to its end once it buffered
    """
    player = end_with_continuous_play_off(view, media)

    action_of(view, "play_pause_action").trigger()
    player.mediaStatusChanged.emit(BUFFERED)

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("01.mp4"))))
    media.play.assert_called_once_with()
    media.set_position.assert_not_called()


def test_a_video_stopped_at_its_end_plays_from_where_it_was_taken_back_to(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * let a video end with continuous play off, jump back five seconds, and press play
    * verify the same video was played and sought to five seconds before its end once it buffered
    """
    player = end_with_continuous_play_off(view, media)

    action_of(view, "back_action").trigger()
    action_of(view, "play_pause_action").trigger()
    player.mediaStatusChanged.emit(BUFFERED)

    media.set_source.assert_called_once_with(QUrl.fromLocalFile(str(path_of("01.mp4"))))
    media.play.assert_called_once_with()
    media.set_position.assert_called_once_with(LENGTH_MS - 5_000)


def test_to_the_end_loads_the_next_video_paused_whatever_the_button_says(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * uncheck the button, play a video and press to-the-end
    * verify the next video was opened and not played
    """
    button_of(view).setChecked(False)
    start_playing(view, "01.mp4")
    media.set_source.reset_mock()
    media.play.reset_mock()

    action_of(view, "to_end_action").trigger()

    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_not_called()
