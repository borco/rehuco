"""Tests for which page the player's picture shows as a video starts to play under Qt: the still, until the video
widget has a frame of where the video is (#574)."""

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer
from rehuco_agent.documents.player_stage import REVEAL_TIMEOUT_MS
from rehuco_agent.documents.player_view import PlayerView

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    Media,
    action_of,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    fixture_view,  # noqa: F401
    picture,
    shown_of,
    sink_of,
    start_playing,
    still_of,
)


def test_playing_again_under_qt_keeps_the_still_up_until_a_frame_of_where_it_was(
    view: PlayerView, media: Media
) -> None:
    """Qt opens a paused video's file again to play it, and its widget is black until the first frame: the still
    stays up meanwhile, rather than flashing black (#574).

    **Test steps:**

    * play a video, pause it at 33 s, press play, and let it buffer
    * verify the still is shown
    * give a frame from 50 s, before the seek took hold, and verify the still is shown
    * give a frame from 33 s and verify the video is shown
    """
    player = start_playing(view, "02.mp4")
    media.position.return_value = 33_000
    play_pause = action_of(view, "play_pause_action")
    play_pause.trigger()
    play_pause.trigger()
    player.mediaStatusChanged.emit(BUFFERED)
    assert shown_of(view) is still_of(view)

    sink_of(view).videoFrameChanged.emit(picture(50_000))
    assert shown_of(view) is still_of(view)

    sink_of(view).videoFrameChanged.emit(picture(33_000))
    assert shown_of(view).objectName() == "video_widget"


def resume_at(view: PlayerView, media: Media, position_ms: int) -> QMediaPlayer:
    """Play the second video, pause it at a position, press play again and let it buffer: the still is up, waiting.

    :param view: the view.
    :param media: the patched player calls.
    :param position_ms: where it is paused.
    :returns: the player.
    """
    player = start_playing(view, "02.mp4")
    media.position.return_value = position_ms
    play_pause = action_of(view, "play_pause_action")
    play_pause.trigger()
    play_pause.trigger()
    player.mediaStatusChanged.emit(BUFFERED)
    assert shown_of(view) is still_of(view)
    return player


def test_a_stale_position_reported_before_the_seek_lands_reveals_no_frame_of_the_start(
    view: PlayerView, media: Media
) -> None:
    """Regression: the position the player reports is followed as the video's, and one of 0 reported before the seek
    to 33 s held made a frame of the start the one to show -- the flash of the beginning the wait exists to prevent.

    **Test steps:**

    * resume at 33 s, have the player report 0 and give a frame from 0
    * verify the still is still shown
    * have the player report 33.2 s and give a frame from 0
    * verify the video is shown: the seek landed, so the next frame is of it whatever time it carries
    """
    player = resume_at(view, media, 33_000)

    player.positionChanged.emit(0)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert shown_of(view) is still_of(view)

    player.positionChanged.emit(33_200)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert shown_of(view).objectName() == "video_widget"


def test_a_video_giving_no_frame_of_its_position_is_shown_after_the_timeout(view: PlayerView, media: Media) -> None:
    """A file whose frame times never meet its positions, or that reports no position, must not play behind a still
    for good.

    **Test steps:**

    * resume at 33 s and give a frame from far away
    * verify the still is still shown, and the stage's reveal timer runs at the timeout
    * let the timer fire and verify the video is shown
    """
    resume_at(view, media, 33_000)
    sink_of(view).videoFrameChanged.emit(picture(5_000_000))
    assert shown_of(view) is still_of(view)

    timer = view.findChild(QTimer, "reveal_timer")
    assert isinstance(timer, QTimer)
    assert timer.isActive() and timer.interval() == REVEAL_TIMEOUT_MS
    timer.timeout.emit()

    assert shown_of(view).objectName() == "video_widget"
    assert not timer.isActive()
