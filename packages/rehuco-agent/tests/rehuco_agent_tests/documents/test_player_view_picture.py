"""Tests for what the player's picture shows across a pause and a resume under Qt: the video widget, holding its last
frame while paused, and handed frames again only from one of where the video is (#574)."""

from typing import Final

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer
from rehuco_agent.documents.player_stage import REVEAL_TIMEOUT_MS
from rehuco_agent.documents.player_view import PlayerView
from rehuco_core import ProgressEntry

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
    widget_frame,
)

PAUSED_MS: Final = 33_000
"""Where the video is paused in these tests."""


def frame_ms(view: PlayerView) -> float:
    """When in the video the frame the video widget holds is from.

    :param view: the view.
    :returns: its time in milliseconds.
    """
    return widget_frame(view).startTime() / 1000


def resume(view: PlayerView, media: Media) -> QMediaPlayer:
    """Play the second video from its start until a frame of 33 s, pause there, press play again and let it buffer.

    :param view: the view.
    :param media: the patched player calls.
    :returns: the player.
    """
    player = start_playing(view, "02.mp4")
    sink_of(view).videoFrameChanged.emit(picture(0))
    player.positionChanged.emit(PAUSED_MS)
    sink_of(view).videoFrameChanged.emit(picture(PAUSED_MS))
    media.position.return_value = PAUSED_MS
    play_pause = action_of(view, "play_pause_action")
    play_pause.trigger()
    play_pause.trigger()
    player.mediaStatusChanged.emit(BUFFERED)
    return player


def test_a_pause_keeps_the_video_widget_on_its_last_frame(view: PlayerView, media: Media) -> None:
    """The same widget draws the paused frame as drew it playing: a still painted by Qt's own scaling shifted the
    picture by about a pixel, and flashed as the native window went (seen by the owner).

    **Test steps:**

    * play a video from its start until a frame of 33 s, then pause
    * verify the video widget is shown, holding that frame
    * give the sink a frame, as clearing the player's source does, and verify the widget still holds the paused one
    """
    player = start_playing(view, "02.mp4")
    sink_of(view).videoFrameChanged.emit(picture(0))
    player.positionChanged.emit(PAUSED_MS)
    sink_of(view).videoFrameChanged.emit(picture(PAUSED_MS))
    media.position.return_value = PAUSED_MS

    action_of(view, "play_pause_action").trigger()

    assert shown_of(view).objectName() == "video_widget"
    assert frame_ms(view) == PAUSED_MS
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert frame_ms(view) == PAUSED_MS


def test_playing_again_holds_the_paused_frame_until_one_of_where_it_was(view: PlayerView, media: Media) -> None:
    """Qt opens a paused video's file again to play it, and frames from before the seek held can come first.

    **Test steps:**

    * resume a video paused at 33 s
    * give a frame from 50 s, before the seek took hold, and verify the widget still holds the paused frame
    * give a frame from 33.5 s and verify the widget holds it, then that a later frame follows
    """
    resume(view, media)

    sink_of(view).videoFrameChanged.emit(picture(50_000))
    assert frame_ms(view) == PAUSED_MS

    sink_of(view).videoFrameChanged.emit(picture(33_500))
    assert frame_ms(view) == 33_500
    sink_of(view).videoFrameChanged.emit(picture(34_000))
    assert frame_ms(view) == 34_000
    assert shown_of(view).objectName() == "video_widget"


def test_a_stale_position_reported_before_the_seek_lands_hands_on_no_frame_of_the_start(
    view: PlayerView, media: Media
) -> None:
    """Regression: the position the player reports is followed as the video's, and one of 0 reported before the seek
    to 33 s held made a frame of the start the one to show -- the flash of the beginning the wait exists to prevent.

    **Test steps:**

    * resume at 33 s, have the player report 0 and give a frame from 0
    * verify the widget still holds the paused frame
    * have the player report 33.2 s and give a frame from 0
    * verify the widget holds it: the seek landed, so the next frame is of it whatever time it carries
    """
    player = resume(view, media)

    player.positionChanged.emit(0)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert frame_ms(view) == PAUSED_MS

    player.positionChanged.emit(33_200)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert frame_ms(view) == 0


def test_a_video_giving_no_frame_of_its_position_is_handed_on_after_the_timeout(view: PlayerView, media: Media) -> None:
    """A file whose frame times never meet its positions, or that reports no position, must not play behind its paused
    frame for good.

    **Test steps:**

    * resume at 33 s and give a frame from far away
    * verify the widget still holds the paused frame, and the stage's reveal timer runs at the timeout
    * let the timer fire, give the far frame again and verify the widget holds it
    """
    resume(view, media)
    sink_of(view).videoFrameChanged.emit(picture(5_000_000))
    assert frame_ms(view) == PAUSED_MS

    timer = view.findChild(QTimer, "reveal_timer")
    assert isinstance(timer, QTimer)
    assert timer.isActive() and timer.interval() == REVEAL_TIMEOUT_MS
    timer.timeout.emit()
    sink_of(view).videoFrameChanged.emit(picture(5_000_000))

    assert frame_ms(view) == 5_000_000
    assert not timer.isActive()


def test_selecting_another_video_takes_the_widgets_frame_away(view: PlayerView, media: Media) -> None:
    """A frame of the video before must never come up as the next one's picture, once its frames are handed on.

    **Test steps:**

    * play a video from its start until a frame of 33 s and pause
    * load the next video
    * verify the video widget holds no frame and the still page is shown
    """
    resume(view, media)
    assert frame_ms(view) == PAUSED_MS

    action_of(view, "next_action").trigger()

    assert not widget_frame(view).isValid()
    assert shown_of(view).objectName() == "still_widget"


def test_a_pause_before_a_frame_of_the_position_shows_the_newest_frame_decoded(
    view: PlayerView, progress: dict[str, ProgressEntry]
) -> None:
    """Frames before the seek lands are not handed on, so a pause then would show nothing; the newest is a picture.

    **Test steps:**

    * jump to a video left at 30 s, let it buffer, and give a frame from the start
    * verify the widget holds no frame yet
    * pause, and verify the widget shows that frame
    """
    progress["02.mp4"] = ProgressEntry(30.0, 100.0)
    start_playing(view, "02.mp4")
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert not widget_frame(view).isValid()

    action_of(view, "play_pause_action").trigger()

    assert frame_ms(view) == 0
    assert shown_of(view).objectName() == "video_widget"


def test_the_seeks_own_report_of_its_target_lands_nothing(view: PlayerView, media: Media) -> None:
    """Qt reports a seek's target the moment it is asked, before any frame of it; a frame from before the seek could
    still come, and must not be handed on for it.

    **Test steps:**

    * resume at 33 s, have the player report exactly 33 s, as the seek itself does, and give a frame from 0
    * verify the widget still holds the paused frame
    * have the player report 33.05 s, as playback does, and give a frame from 0
    * verify the widget holds it
    """
    player = resume(view, media)

    player.positionChanged.emit(PAUSED_MS)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert frame_ms(view) == PAUSED_MS

    player.positionChanged.emit(PAUSED_MS + 50)
    sink_of(view).videoFrameChanged.emit(picture(0))
    assert frame_ms(view) == 0


def test_an_error_ends_the_wait_for_a_frame(view: PlayerView, media: Media) -> None:
    """No frame of the position will come: the timer that would otherwise hand frames on after it runs out stops.

    **Test steps:**

    * resume at 33 s, and have the player report an error
    * verify the stage's reveal timer is stopped, and a frame given afterwards is not handed on
    """
    player = resume(view, media)
    timer = view.findChild(QTimer, "reveal_timer")
    assert isinstance(timer, QTimer) and timer.isActive()

    player.errorOccurred.emit(QMediaPlayer.Error.ResourceError, "broken")

    assert not timer.isActive()
    sink_of(view).videoFrameChanged.emit(picture(PAUSED_MS))
    assert frame_ms(view) == PAUSED_MS
