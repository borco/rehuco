"""Tests for which engine the player builds, and what changes under libvlc (#319, [[plugins#in-app-player]]).

The Qt Multimedia engine's behaviour is ``test_player_view``'s and ``test_player_view_controls``'s; here the engine
is a mock of :class:`VlcMediaPlayer`, since the engine itself is tested in ``test_vlc_media_player``.
"""

# fixture-heavy tests: a view, its document, its recorder, the library, the engine and the choice
# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Any
from unittest.mock import Mock

import cbor2
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QImage, QPalette
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QLabel
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import player_engine
from rehuco_agent.documents.player_view import INTERLACED_NOTICE, VLC_FALLBACK_TEMPLATE
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.vlc_media_player import VlcEngineError, VlcMediaPlayer
from rehuco_agent.documents.vlc_surface import VlcSurface
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_agent.settings.videos_settings import IN_APP_PLAYER, VLC_PLAYER, shared_videos_settings
from rehuco_core import UNKNOWN_ENTRY, RenameCoordinator, SubtitleChoice, SubtitlePreferences, VideoFormat

from .player_view_support import (  # pylint: disable=unused-import
    Listing,
    action_of,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    make_view,
    notices,
    show_first_frame,
    shown_of,
    still_of,
    subtitle_combo_of,
)


@fixture(name="library")
def fixture_library(mocker: MockerFixture) -> Mock:
    """A loaded python-vlc, as the shared loader answers.

    :param mocker: pytest-mock fixture.
    :returns: the proxy mock.
    """
    library = Mock()
    library.available = True
    library.reason = None
    mocker.patch.object(player_engine, "shared_vlc_library", return_value=library)
    return library


@fixture(name="engine")
def fixture_engine(mocker: MockerFixture) -> Mock:
    """The libvlc engine the view builds, a mock standing in for the class.

    :param mocker: pytest-mock fixture.
    :returns: the mock the class returns.
    """
    engine = Mock(spec=VlcMediaPlayer)
    for name in ("positionChanged", "durationChanged", "playbackStateChanged", "mediaStatusChanged", "errorOccurred"):
        setattr(engine, name, Mock())
    engine.still_ready = Mock()
    engine.still_refreshed = Mock()
    engine.subtitle_chosen = Mock()
    engine.subtitle_menu_changed = Mock()
    engine.position.return_value = 0
    engine.duration.return_value = 0
    mocker.patch.object(player_engine, "VlcMediaPlayer", return_value=engine)
    return engine


@fixture(name="vlc_chosen")
def fixture_vlc_chosen() -> None:
    """Choose VLC on the Videos page."""
    shared_videos_settings().player = VLC_PLAYER


def deliver(engine: Mock, signal: str, *args: Any) -> None:
    """Call what the view connected to one of the engine's signals, as the signal would.

    :param engine: the engine mock.
    :param signal: the signal's name.
    :param args: the signal's arguments.
    """
    slot = getattr(engine, signal).connect.call_args.args[0]
    slot(*args)  # pylint: disable=not-callable  # a Mock's record


def test_vlc_chosen_and_loaded_builds_the_libvlc_engine_on_its_surface(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
    mocker: MockerFixture,
) -> None:
    """**Test steps:**

    * choose VLC, with a loaded library, and play a video
    * verify the engine was built over the library and the libvlc surface, given the file, played, and that the libvlc
      surface is the page shown; no Qt player was made
    """
    del vlc_chosen
    qt_player = mocker.patch.object(player_engine, "QMediaPlayer")
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")

    built = getattr(player_engine, "VlcMediaPlayer")  # noqa: B009  # the patched class
    assert built.call_args.args[0] is library
    assert built.call_args.args[1] is view.findChild(type(shown_of(view)), "vlc_surface")
    engine.setSource.assert_called_once()
    assert engine.setSource.call_args.args[0].isLocalFile()  # pylint: disable=no-member
    engine.play.assert_called_once_with()
    assert shown_of(view).objectName() == "vlc_surface"
    qt_player.assert_not_called()
    assert notices(view) == []


def test_vlc_chosen_but_not_loadable_plays_through_qt_and_says_why(
    qtbot: QtBot, model: RehuDocumentModel, recorder: WatchProgressRecorder, library: Mock, vlc_chosen: None
) -> None:
    """**Test steps:**

    * choose VLC, with the library unavailable for a reason, and play a video
    * verify the Qt engine plays it and the banner carries the reason
    """
    del vlc_chosen
    library.available = False
    library.reason = "No VLC is set up on the Tools page."
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")
    show_first_frame(view)

    assert shown_of(view).objectName() == "video_widget"
    assert notices(view) == [VLC_FALLBACK_TEMPLATE.format(reason="No VLC is set up on the Tools page.")]


def test_an_engine_libvlc_refuses_falls_back_the_same_way(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    vlc_chosen: None,
    mocker: MockerFixture,
) -> None:
    """**Test steps:**

    * choose VLC, with a library whose player cannot be made
    * verify Qt plays and the banner says what libvlc refused
    """
    del library, vlc_chosen
    mocker.patch.object(player_engine, "VlcMediaPlayer", side_effect=VlcEngineError("libvlc gave no player."))
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")
    show_first_frame(view)

    assert shown_of(view).objectName() == "video_widget"
    assert notices(view) == [VLC_FALLBACK_TEMPLATE.format(reason="libvlc gave no player.")]


def test_qt_is_built_when_vlc_is_not_chosen_without_asking_for_the_library(
    qtbot: QtBot, model: RehuDocumentModel, recorder: WatchProgressRecorder, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * leave the app's player chosen and play a video
    * verify the library was never loaded
    """
    loader = mocker.patch.object(player_engine, "shared_vlc_library")
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")
    show_first_frame(view)

    loader.assert_not_called()
    assert shown_of(view).objectName() == "video_widget"


def test_no_format_notice_is_made_under_libvlc(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
    listing: Listing,
) -> None:
    """libvlc deinterlaces and decodes AV1 in software, so neither of Qt's explanations applies.

    **Test steps:**

    * play an interlaced video under libvlc
    * verify no notice
    """
    del library, engine, vlc_chosen
    listing.formats.update({"01.mp4": VideoFormat("AVC", interlaced=True)})  # a frozen dataclass's dict
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")

    assert INTERLACED_NOTICE not in notices(view)


def test_a_pause_under_libvlc_keeps_the_file_and_resumes_on_the_same_frame(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """Reopening and seeking landed a few frames off, so under libvlc the player stays paused on its frame.

    **Test steps:**

    * play under libvlc, let it buffer, then pause
    * verify the still was taken and shown, the engine paused rather than stopped, and the source kept
    * press play again and verify the engine resumed without reopening
    """
    del library, vlc_chosen
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    engine.grab_still.return_value = image
    engine.position.return_value = 3000
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "playbackStateChanged", QMediaPlayer.PlaybackState.PlayingState)
    engine.setSource.reset_mock()

    view.findChild(type(view.actions()[0]), "play_pause_action").trigger()  # type: ignore[union-attr]

    engine.grab_still.assert_called_once_with()
    engine.pause.assert_called_once_with()
    engine.stop.assert_not_called()
    engine.setSource.assert_not_called()
    assert still_of(view).image is not None
    assert shown_of(view).objectName() == "still_widget"

    view.findChild(type(view.actions()[0]), "play_pause_action").trigger()  # type: ignore[union-attr]

    assert engine.play.call_count == 2
    engine.setSource.assert_not_called()
    assert shown_of(view).objectName() == "vlc_surface"


def test_a_paused_load_shows_libvlcs_still_and_lets_go(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * load a video paused under libvlc, let it buffer, and have the engine deliver its still
    * verify the engine was asked to pause (the muted play), the still is shown, and the file was let go
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    model.last_video.return_value = "01.mp4"  # type: ignore[attr-defined]
    view.load_last()
    engine.pause.assert_called_once_with()
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0xFF445566)

    deliver(engine, "still_ready", image)

    assert still_of(view).image is not None
    engine.stop.assert_called_once_with()
    engine.setSource.assert_called_with(QUrl())


def test_the_volume_keys_reach_libvlc(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc and lower the volume one step
    * verify the engine got the volume at build and the lowered one after
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    engine.setVolume.assert_called_with(1.0)

    view.findChild(type(view.actions()[0]), "volume_down_action").trigger()  # type: ignore[union-attr]

    assert engine.setVolume.call_args.args[0] < 1.0


def test_a_still_arriving_while_a_video_plays_changes_nothing(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """A still is for a paused load; one delivered late, after play was pressed, must not let the file go.

    **Test steps:**

    * play under libvlc, then deliver a still
    * verify the engine was not stopped and the surface still shows libvlc
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")

    deliver(engine, "still_ready", QImage(4, 3, QImage.Format.Format_RGB32))

    engine.stop.assert_not_called()
    assert shown_of(view).objectName() == "vlc_surface"


def test_a_rename_of_this_resource_lets_a_held_video_go(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
    coordinator: RenameCoordinator,
) -> None:
    """The one case the release exists for: the folder is about to be renamed, so the held file is let go, and the
    video stays paused where it was, to be reopened there on the next play.

    **Test steps:**

    * play under libvlc, buffer, pause (held), then announce a rename of this resource
    * verify the engine was stopped and its source cleared, and the still still shown
    """
    del library, vlc_chosen
    engine.grab_still.return_value = QImage(4, 3, QImage.Format.Format_RGB32)
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "playbackStateChanged", QMediaPlayer.PlaybackState.PlayingState)
    view.findChild(type(view.actions()[0]), "play_pause_action").trigger()  # type: ignore[union-attr]
    engine.stop.assert_not_called()

    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]
    listener(model.path)  # pylint: disable=not-callable  # a Mock's record

    engine.stop.assert_called_once_with()
    engine.setSource.assert_called_with(QUrl())
    assert shown_of(view).objectName() == "still_widget"


def test_a_changed_choice_rebuilds_the_engine_at_the_next_video(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    mocker: MockerFixture,
) -> None:
    """The Videos page's choice applies to the next video selected, in a document already open: Qt to libvlc, and
    libvlc back to Qt, each engine dropped as the other is built.

    **Test steps:**

    * with the app's player chosen, play a video, and verify Qt's engine shows
    * choose VLC and play the next video; verify the libvlc engine was built, its surface shows, and the Qt player was
      let go
    * choose the app's player again and play; verify libvlc was let go and a new Qt player built
    """
    del library
    qt_players: list[Mock] = []
    real_qt = getattr(player_engine, "QMediaPlayer")  # noqa: B009  # the real class, before it is patched

    def build_qt(*args: Any) -> Any:
        qt_players.append(mocker.Mock(wraps=real_qt(*args)))
        return qt_players[-1]

    mocker.patch.object(player_engine, "QMediaPlayer", side_effect=build_qt)
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    show_first_frame(view, qt_players[0])
    assert shown_of(view).objectName() == "video_widget"
    assert len(qt_players) == 1

    shared_videos_settings().player = VLC_PLAYER
    view.jump("02.mp4")

    engine.setSource.assert_called_once()
    engine.play.assert_called_once_with()
    assert shown_of(view).objectName() == "vlc_surface"
    qt_players[0].deleteLater.assert_called_once_with()

    shared_videos_settings().player = IN_APP_PLAYER
    view.jump("01.mp4")

    engine.deleteLater.assert_called_once_with()
    assert len(qt_players) == 2
    show_first_frame(view, qt_players[1])
    assert shown_of(view).objectName() == "video_widget"


def test_a_rename_of_this_resource_lets_a_playing_video_go_under_libvlc(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
    coordinator: RenameCoordinator,
) -> None:
    """A rename while the video plays pauses it and, under libvlc, releases the file the pause would have held.

    **Test steps:**

    * play under libvlc, buffer, then announce a rename of this resource while it plays
    * verify the engine was stopped and its source cleared, with a still shown
    """
    del library, vlc_chosen
    engine.grab_still.return_value = QImage(4, 3, QImage.Format.Format_RGB32)
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    deliver(engine, "playbackStateChanged", QMediaPlayer.PlaybackState.PlayingState)

    listener = coordinator.add_before_rename_listener.call_args.args[0]  # type: ignore[attr-defined]
    listener(model.path)  # pylint: disable=not-callable  # a Mock's record

    engine.stop.assert_called_once_with()
    engine.setSource.assert_called_with(QUrl())
    assert shown_of(view).objectName() == "still_widget"


def test_a_vlc_set_up_after_the_fallback_is_taken_at_the_next_video(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * choose VLC with the library unavailable and play: Qt plays, with the reason
    * make the library available and play the next video: verify the libvlc engine is built and the notice gone
    """
    del vlc_chosen
    library.available = False
    library.reason = "No VLC is set up on the Tools page."
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    show_first_frame(view)
    assert shown_of(view).objectName() == "video_widget"

    library.available = True
    library.reason = None
    view.jump("02.mp4")

    engine.play.assert_called_once_with()
    assert shown_of(view).objectName() == "vlc_surface"
    assert notices(view) == []


def test_stopping_the_view_closes_the_libvlc_engine(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """The dock closed, or the document: libvlc's threads and audio output go with it.

    **Test steps:**

    * play under libvlc, then stop the view
    * verify the engine was closed and let go; play again and verify a new engine was built
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")

    view.stop()

    engine.close.assert_called_once_with()
    engine.deleteLater.assert_called_once_with()
    built = getattr(player_engine, "VlcMediaPlayer")  # noqa: B009  # the patched class
    view.jump("01.mp4")
    assert built.call_count == 2


def test_stopping_a_view_that_built_no_engine_drops_nothing(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * stop a view before any video was selected
    * verify no engine was built or closed
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)

    view.stop()

    engine.close.assert_not_called()
    built = getattr(player_engine, "VlcMediaPlayer")  # noqa: B009  # the patched class
    built.assert_not_called()


def test_the_info_under_libvlc_reads_the_size_off_the_frame_it_shows(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """With no size from a Measure, the info panel names the size of the frame libvlc painted, and none before one is
    painted (#574).

    **Test steps:**

    * choose VLC, show the info, play a video with no frame painted yet
    * verify the panel says the size is unknown
    * paint a 640x360 frame on the libvlc surface and move the video, and verify the panel names that size
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.findChild(QAction, "info_action").trigger()  # type: ignore[union-attr]
    view.jump("01.mp4")
    deliver(engine, "durationChanged", 100_000)
    deliver(engine, "mediaStatusChanged", QMediaPlayer.MediaStatus.BufferedMedia)
    panel = view.findChild(QLabel, "info_panel")
    assert isinstance(panel, QLabel)
    assert "size unknown" in panel.text()

    surface = view.findChild(VlcSurface, "vlc_surface")
    assert isinstance(surface, VlcSurface)
    surface.set_frame(QImage(640, 360, QImage.Format.Format_RGB32))
    view.seek("01.mp4", 10.0)

    assert "640 × 360 px" in panel.text()


# region Subtitles


@mark.parametrize(
    ("action", "method"),
    [
        param("subtitle_next_action", "next_subtitle", id="next"),
        param("subtitle_previous_action", "previous_subtitle", id="previous"),
        param("subtitle_toggle_action", "toggle_subtitles", id="on or off"),
    ],
)
def test_the_subtitle_actions_are_enabled_under_libvlc_and_reach_it(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
    action: str,
    method: str,
) -> None:
    """**Test steps:**

    * build a player, and verify the action is disabled while no engine is built
    * play a video under libvlc, and verify the action is enabled
    * trigger it and verify the engine was asked for its subtitle call, once
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    assert not action_of(view, action).isEnabled()
    view.jump("01.mp4")
    assert action_of(view, action).isEnabled()

    action_of(view, action).trigger()

    getattr(engine, method).assert_called_once_with()


def test_the_subtitle_actions_are_disabled_again_when_the_player_lets_libvlc_go(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play a video under libvlc, then stop the player
    * verify the actions are disabled and a trigger reaches no engine
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")

    view.stop()
    action_of(view, "subtitle_next_action").trigger()

    assert not action_of(view, "subtitle_next_action").isEnabled()
    engine.next_subtitle.assert_not_called()


def test_the_picture_a_paused_change_made_replaces_the_still(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc and pause, which shows a still
    * have the engine deliver the frame a subtitle change made
    * verify the still shows that frame
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    action_of(view, "play_pause_action").trigger()
    refreshed = QImage(4, 3, QImage.Format.Format_RGB32)
    refreshed.fill(0xFF112233)

    deliver(engine, "still_refreshed", refreshed)

    assert still_of(view).image is refreshed or still_of(view).image == refreshed


def test_the_engine_is_handed_the_settings_list_and_default_before_a_video_opens(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * set the Videos page's subtitles to off, Romanian then Unknown, only selected
    * play a video under libvlc
    * verify the engine was given that list, and the choice of no subtitles, which a rehu with none chosen starts at
    """
    del library, vlc_chosen
    settings = shared_videos_settings()
    settings.subtitles_on = False
    settings.subtitle_languages = ("Romanian", UNKNOWN_ENTRY)
    settings.subtitles_show_all = False
    view = make_view(qtbot, model, recorder)

    view.jump("01.mp4")

    engine.set_subtitle_preferences.assert_called_once_with(
        SubtitlePreferences(("Romanian", UNKNOWN_ENTRY), show_all=False)
    )
    engine.set_subtitle_choice.assert_called_once_with(SubtitleChoice(shown=False))


def test_what_the_reader_chose_is_handed_on_with_the_next_video_and_saved_with_the_layout(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play a video, and have the engine say the reader chose Romanian
    * play another, and verify the engine was given that choice for it
    * save the player's state, restore it into a second player, and verify that one hands the same choice on
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    choice = SubtitleChoice(True, "Romanian", False)
    deliver(engine, "subtitle_chosen", choice)
    deliver(engine, "subtitle_chosen", "not a choice")  # what is not one is ignored

    view.jump("02.mp4")
    assert engine.set_subtitle_choice.call_args.args == (choice,)

    other = make_view(qtbot, model, recorder)
    other.restore_state(view.save_state())
    other.jump("01.mp4")

    assert engine.set_subtitle_choice.call_args.args == (choice,)


def test_a_player_state_with_no_choice_leaves_the_default(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * save the state of a player where nothing was chosen, and restore it, and a blob that is not a state, and a list
    * play a video and verify the engine was given the settings' default
    """
    del library, vlc_chosen
    shared_videos_settings().subtitles_on = True
    view = make_view(qtbot, model, recorder)

    view.restore_state(view.save_state())
    view.restore_state(b"not cbor")
    view.restore_state(cbor2.dumps([1]))
    view.jump("01.mp4")

    assert engine.set_subtitle_choice.call_args.args == (SubtitleChoice(shown=True),)


# endregion


def test_the_transport_bar_offers_the_subtitles_while_the_engine_is_libvlc(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc: verify the menu is there but disabled, reading that the tracks are not known yet
    * have the engine offer none, English and French with English on and only it visited, and verify the menu lists
      them, shows English, and gives the entry the keys skip the disabled colour and the others the default
    * have it offer nothing, and verify the menu is disabled and pending again
    * have it offer the one entry that says there are none, and verify the menu is disabled
    * offer them again and stop the player, and verify the menu is hidden
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    combo = subtitle_combo_of(view)
    assert (combo.isHidden(), combo.isEnabled(), combo.currentText()) == (False, False, "Subs: …")

    deliver(engine, "subtitle_menu_changed", ["Subs: off", "Subs: English", "Subs: French"], 1, 1)
    assert combo.isEnabled()
    assert [combo.itemText(row) for row in range(combo.count())] == ["Subs: off", "Subs: English", "Subs: French"]
    assert (combo.currentText(), combo.isHidden()) == ("Subs: English", False)
    role = Qt.ItemDataRole.ForegroundRole
    assert [combo.itemData(row, role) is None for row in range(3)] == [True, True, False]
    assert combo.itemData(2, role) == combo.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

    deliver(engine, "subtitle_menu_changed", [], 0, 0)
    assert (combo.currentText(), combo.isEnabled()) == ("Subs: …", False)

    deliver(engine, "subtitle_menu_changed", ["Subs: none"], 0, 0)
    assert (combo.currentText(), combo.isEnabled()) == ("Subs: none", False)

    deliver(engine, "subtitle_menu_changed", ["Subs: off", "Subs: English"], 1, 1)
    view.stop()
    assert combo.isHidden()


def test_picking_an_entry_of_the_menu_reaches_libvlc_and_a_new_menu_does_not(
    qtbot: QtBot,
    model: RehuDocumentModel,
    recorder: WatchProgressRecorder,
    library: Mock,
    engine: Mock,
    vlc_chosen: None,
) -> None:
    """**Test steps:**

    * play under libvlc and have the engine offer a menu
    * pick the last entry as the reader would, and verify the engine was asked to show it
    * have the engine offer another menu, and verify that picked nothing
    """
    del library, vlc_chosen
    view = make_view(qtbot, model, recorder)
    view.jump("01.mp4")
    combo = subtitle_combo_of(view)
    deliver(engine, "subtitle_menu_changed", ["Subs: off", "Subs: English", "Subs: Romanian"], 0, 2)

    combo.activated.emit(2)
    deliver(engine, "subtitle_menu_changed", ["Subs: off", "Subs: English"], 1, 1)

    engine.select_subtitle.assert_called_once_with(2)
