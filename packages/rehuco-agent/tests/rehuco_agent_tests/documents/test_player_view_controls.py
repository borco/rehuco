"""Tests for the in-app video player's keys, volume, speed and notices (#317).

Which video it shows and what it holds open is ``test_player_view``'s. The Qt Multimedia player is a real one with its
playing methods patched (``player_view_support``).
"""

from borco_pyside.shortcuts import Command
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.commands import (
    PLAYER_BACK,
    PLAYER_FORWARD,
    PLAYER_NEXT,
    PLAYER_PLAY_PAUSE,
    PLAYER_PREVIOUS,
    PLAYER_SPEED_DOWN,
    PLAYER_SPEED_UP,
    PLAYER_TO_END,
    PLAYER_TO_START,
    PLAYER_VOLUME_DOWN,
    PLAYER_VOLUME_UP,
)
from rehuco_agent.documents.player_view import (
    AV1_NOTICE,
    ERROR_NOTICE,
    INTERLACED_NOTICE,
    SPEEDS,
    VOLUME_STEP,
    PlayerView,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import VideoFormat

from .player_view_support import (  # pylint: disable=unused-import
    BUFFERED,
    SHORT_MS,
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
    format_runner_of,
    make_view,
    notices,
    picture,
    player_of,
    sink_of,
    speed_combo_of,
    start_playing,
)

# region The keys


@mark.parametrize(
    ("name", "command"),
    [
        param("play_pause_action", PLAYER_PLAY_PAUSE, id="play or pause"),
        param("back_action", PLAYER_BACK, id="back"),
        param("forward_action", PLAYER_FORWARD, id="forward"),
        param("previous_action", PLAYER_PREVIOUS, id="previous"),
        param("next_action", PLAYER_NEXT, id="next"),
        param("to_start_action", PLAYER_TO_START, id="to the start"),
        param("to_end_action", PLAYER_TO_END, id="to the end"),
        param("volume_up_action", PLAYER_VOLUME_UP, id="volume up"),
        param("volume_down_action", PLAYER_VOLUME_DOWN, id="volume down"),
        param("speed_up_action", PLAYER_SPEED_UP, id="speed up"),
        param("speed_down_action", PLAYER_SPEED_DOWN, id="speed down"),
    ],
)
def test_every_action_is_on_the_player_with_the_key_of_its_command(
    view: PlayerView, name: str, command: Command
) -> None:
    """The player's keys are commands of the shortcut manager, so the Shortcuts page lists them and they can be rebound.

    **Test steps:**

    * build a player
    * verify each action is on the player, and has its command's default key
    """
    action = action_of(view, name)

    assert action in view.actions()
    assert [key.toString() for key in action.shortcuts()] == list(command.default_keys)


def test_the_new_keys_are_control_home_and_control_end() -> None:
    """**Test steps:**

    * read the default keys of the two commands
    * verify they are Ctrl+Home and Ctrl+End
    """
    assert PLAYER_TO_START.default_keys == ("Ctrl+Home",)
    assert PLAYER_TO_END.default_keys == ("Ctrl+End",)


# endregion

# region Volume and speed


def test_the_volume_steps_within_its_scale_and_reaches_the_audio_output(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video, and raise the volume to the top and past it
    * verify the audio output was set, never over 1
    * lower it to the bottom and past it
    * verify it was set, never under 0
    """
    start_playing(view)
    media.set_volume.reset_mock()

    for _ in range(int(1 / VOLUME_STEP) + 2):
        action_of(view, "volume_up_action").trigger()
    assert media.set_volume.call_args.args == (1.0,)
    for _ in range(int(1 / VOLUME_STEP) + 2):
        action_of(view, "volume_down_action").trigger()

    assert media.set_volume.call_args.args == (0.0,)
    assert all(0.0 <= call.args[0] <= 1.0 for call in media.set_volume.call_args_list)


def test_a_volume_changed_before_any_video_plays_asks_no_audio_output(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * lower the volume with nothing selected
    * verify no audio output was set, since none exists yet
    """
    action_of(view, "volume_down_action").trigger()

    media.set_volume.assert_not_called()


def test_the_speed_combo_steps_within_its_range_and_reaches_the_player(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play a video, and step the speed up past the fastest
    * verify the player was given the fastest rate
    * step it down past the slowest
    * verify the player was given the slowest rate
    """
    start_playing(view)

    for _ in SPEEDS:
        action_of(view, "speed_up_action").trigger()
    assert media.set_rate.call_args.args == (SPEEDS[-1],)
    for _ in SPEEDS:
        action_of(view, "speed_down_action").trigger()

    assert media.set_rate.call_args.args == (SPEEDS[0],)
    assert speed_combo_of(view).currentIndex() == 0


def test_a_speed_chosen_before_any_video_plays_asks_no_player(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * step the speed with nothing selected
    * verify the combo moved and no rate was set on a player, since none exists yet
    """
    action_of(view, "speed_up_action").trigger()

    assert speed_combo_of(view).currentIndex() == SPEEDS.index(1.25)
    media.set_rate.assert_not_called()


# endregion

# region Notices


def test_a_failure_of_the_player_is_said_with_its_reason(view: PlayerView) -> None:
    """**Test steps:**

    * play a video and have the player report an error
    * verify a notice says it could not be played, and why
    """
    player = start_playing(view)

    player.errorOccurred.emit(player.Error.ResourceError, "no codec")

    assert notices(view) == [f"{ERROR_NOTICE} no codec"]


def test_the_same_notice_is_not_said_twice(view: PlayerView) -> None:
    """**Test steps:**

    * have the player report the same error twice
    * verify one notice
    """
    player = start_playing(view)

    player.errorOccurred.emit(player.Error.ResourceError, "no codec")
    player.errorOccurred.emit(player.Error.ResourceError, "no codec")

    assert len(notices(view)) == 1


def test_an_interlaced_video_is_noted_once_its_format_is_read(view: PlayerView, listing: Listing) -> None:
    """**Test steps:**

    * play an interlaced video
    * verify a notice says so
    """
    listing.formats["01.mp4"] = VideoFormat("AVC", interlaced=True)

    view.jump("01.mp4")

    assert notices(view) == [INTERLACED_NOTICE]


def test_a_format_that_cannot_be_read_or_is_of_another_video_is_no_notice(view: PlayerView) -> None:
    """**Test steps:**

    * play a video, then have the runner answer for another video, and with the error reading this one ended in
    * verify no notice
    """
    view.jump("01.mp4")
    runner = format_runner_of(view)

    runner.read.emit("02.mp4", VideoFormat("AVC", interlaced=True))
    runner.read.emit("01.mp4", OSError("gone"))

    assert notices(view) == []


def test_an_av1_video_that_shows_no_picture_is_explained(
    qtbot: QtBot, listing: Listing, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play an AV1 video that buffers and plays, but gives no frame within the time allowed
    * verify a notice explains why it shows nothing
    """
    listing.formats["01.mp4"] = VideoFormat("AV1", interlaced=False)
    view = make_view(qtbot, model, recorder, no_frame_ms=SHORT_MS)
    start_playing(view)

    qtbot.waitUntil(lambda: notices(view) == [AV1_NOTICE], timeout=2000)


def test_an_av1_video_that_shows_a_picture_needs_no_explaining(
    qtbot: QtBot, listing: Listing, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play an AV1 video that gives a frame as soon as it buffers
    * verify no notice is made once the time allowed is up
    """
    listing.formats["01.mp4"] = VideoFormat("AV1", interlaced=False)
    view = make_view(qtbot, model, recorder, no_frame_ms=SHORT_MS)
    start_playing(view)
    sink_of(view).videoFrameChanged.emit(picture())

    qtbot.wait(5 * SHORT_MS)

    assert notices(view) == []


def test_an_av1_video_paused_before_the_time_is_up_is_not_blamed(
    qtbot: QtBot, listing: Listing, model: RehuDocumentModel, recorder: WatchProgressRecorder
) -> None:
    """**Test steps:**

    * play an AV1 video that gives no frame, and pause it before the time allowed is up
    * verify no notice is made
    """
    listing.formats["01.mp4"] = VideoFormat("AV1", interlaced=False)
    view = make_view(qtbot, model, recorder, no_frame_ms=SHORT_MS)
    start_playing(view)
    action_of(view, "play_pause_action").trigger()

    qtbot.wait(5 * SHORT_MS)

    assert notices(view) == []


def test_a_video_loaded_paused_waits_for_no_picture_to_blame_its_format(
    view: PlayerView, listing: Listing, model: RehuDocumentModel, media: Media
) -> None:
    """**Test steps:**

    * load an AV1 video paused, and let it buffer
    * verify no notice is made and nothing played, since nothing is to be seen yet
    """
    listing.formats["01.mp4"] = VideoFormat("AV1", interlaced=False)
    model.last_video.return_value = "01.mp4"  # type: ignore[attr-defined]
    view.load_last()
    player_of(view).mediaStatusChanged.emit(BUFFERED)

    assert notices(view) == []
    media.play.assert_not_called()


# endregion
