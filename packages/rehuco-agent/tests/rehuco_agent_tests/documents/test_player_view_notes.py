"""Tests for what the player does for the notes: going to a time a link names, and asking for a note (#573).

The notes panel and the dock that joins it to the player are ``test_notes_panel``'s and
``test_document_sub_docks_notes``'s; the player's own loading, holding and recording are ``test_player_view``'s.
"""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QToolButton
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
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
    load_paused,
    path_of,
    player_of,
    slider_of,
    start_playing,
)


def test_a_seek_on_the_video_that_plays_goes_to_the_time_and_leaves_it_playing(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play the first video and seek it to 40 seconds
    * verify the player went to 40 seconds, was not opened again and was not told to play or pause
    """
    start_playing(view, "01.mp4")
    for call in (media.set_position, media.set_source, media.play, media.pause):
        call.reset_mock()

    view.seek("01.mp4", 40.0)

    media.set_position.assert_called_once_with(40_000)
    media.set_source.assert_not_called()
    media.play.assert_not_called()
    media.pause.assert_not_called()


def test_a_seek_on_the_video_loaded_paused_goes_to_the_time_and_leaves_it_paused(
    view: PlayerView, model: RehuDocumentModel, media: Media
) -> None:
    """**Test steps:**

    * load the second video paused and seek it to 20 seconds
    * verify the bar moved to 20 seconds and nothing was told to play
    """
    load_paused(view, model, "02.mp4")
    media.play.reset_mock()

    view.seek("02.mp4", 20.0)

    assert slider_of(view).value() == 20_000
    media.play.assert_not_called()


def test_a_seek_with_no_time_on_the_video_already_loaded_does_nothing(
    view: PlayerView, model: RehuDocumentModel, media: Media
) -> None:
    """**Test steps:**

    * load a video and seek it with no time
    * verify the player was not moved
    """
    load_paused(view, model, "02.mp4")
    media.set_position.reset_mock()

    view.seek("02.mp4", None)

    media.set_position.assert_not_called()


def test_a_seek_to_another_video_loads_it_paused_at_the_time(view: PlayerView, media: Media) -> None:
    """**Test steps:**

    * play the first video and seek to a time of the second
    * verify the second is the video selected, its file the last source set, and nothing told to play
    * verify it starts at the time once it buffers
    """
    start_playing(view, "01.mp4")
    for call in (media.set_position, media.set_source, media.play):
        call.reset_mock()

    view.seek("02.mp4", 65.0)
    player = player_of(view)
    player.durationChanged.emit(LENGTH_MS)
    player.mediaStatusChanged.emit(BUFFERED)

    assert view.current_key == "02.mp4"
    media.set_source.assert_called_with(QUrl.fromLocalFile(str(path_of("02.mp4"))))
    media.play.assert_not_called()
    assert slider_of(view).value() == 65_000


def test_adding_a_note_at_the_time_pauses_a_playing_video_and_names_the_time(
    view: PlayerView, media: Media, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play a video that has reached 42 seconds
    * trigger *Add note at*
    * verify the video key and the time were reported, and the play action offers to play again
    """
    start_playing(view, "01.mp4")
    media.position.return_value = 42_000

    with qtbot.waitSignal(view.note_requested) as requested:
        action_of(view, "add_note_at_action").trigger()

    assert requested.args == ["01.mp4", 42.0]
    assert action_of(view, "play_pause_action").text() == "Play"


def test_adding_a_note_at_the_time_of_a_paused_video_names_where_it_is(
    view: PlayerView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * load a video paused and move it to 20 seconds
    * trigger *Add note at*
    * verify the time reported is 20 seconds
    """
    load_paused(view, model, "02.mp4")
    view.seek("02.mp4", 20.0)

    with qtbot.waitSignal(view.note_requested) as requested:
        action_of(view, "add_note_at_action").trigger()

    assert requested.args == ["02.mp4", 20.0]


def test_the_note_action_is_enabled_only_with_a_video(view: PlayerView, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * verify *Add note at* is disabled with no video
    * load a video and verify it is enabled
    * stop and verify it is disabled again
    """
    action = action_of(view, "add_note_at_action")
    assert not action.isEnabled()

    load_paused(view, model, "02.mp4")
    assert action.isEnabled()

    view.stop()
    assert not action.isEnabled()


def test_the_note_action_names_the_time_it_would_add_the_note_at(view: PlayerView, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * load a video and move it to 65 seconds
    * verify the action's text and tooltip name 1:05
    """
    load_paused(view, model, "02.mp4")

    view.seek("02.mp4", 65.0)

    action = action_of(view, "add_note_at_action")
    assert action.text() == "Add note at 1:05"
    assert "1:05" in action.toolTip()


def test_adding_a_note_without_the_pause_leaves_the_video_playing_and_names_where_it_is(
    view: PlayerView, media: Media, qtbot: QtBot
) -> None:
    """**Test steps:**

    * switch the pause off, play a video that has reached 42 seconds
    * trigger *Add note at*
    * verify the time was reported and the video was not paused
    """
    shared_videos_settings().add_note_edits = False
    start_playing(view, "01.mp4")
    media.position.return_value = 42_000
    media.pause.reset_mock()

    with qtbot.waitSignal(view.note_requested) as requested:
        action_of(view, "add_note_at_action").trigger()

    assert requested.args == ["01.mp4", 42.0]
    assert action_of(view, "play_pause_action").text() == "Pause"
    media.pause.assert_not_called()


def test_the_slider_marks_the_bookmarks_of_the_video_selected(
    view: PlayerView, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * give the first video a bookmark of its own, one for another video and a plain line
    * play it and verify only its own bookmark is marked
    * let the notes change and verify the marks follow, then stop and verify none remain
    """
    notes = {"01.mp4": "- [0:20](rehuco-video:01.mp4#t=20) a\n- [0:50](rehuco-video:02.mp4#t=50) b\nplain"}
    model.video_notes_of.side_effect = lambda key: notes.get(key, "")  # type: ignore[attr-defined]
    slider = slider_of(view)

    start_playing(view, "01.mp4")
    assert slider.marks == (20_000,)  # type: ignore[attr-defined]

    notes["01.mp4"] += "\n- [1:00](rehuco-video:01.mp4#t=60) c"
    view_notes_changed = model.notes_changed.connect.call_args.args[0]  # type: ignore[attr-defined]
    view_notes_changed()  # pylint: disable=not-callable
    assert slider.marks == (20_000, 60_000)  # type: ignore[attr-defined]

    view.stop()
    assert slider.marks == ()  # type: ignore[attr-defined]
    del qtbot


@mark.parametrize(
    ("button_name", "action_name"),
    [
        ("previous_button", "previous_action"),
        ("back_button", "back_action"),
        ("play_pause_button", "play_pause_action"),
        ("forward_button", "forward_action"),
        ("next_button", "next_action"),
        ("add_note_button", "add_note_at_action"),
    ],
)
def test_a_transport_button_presses_and_shows_its_action_without_holding_it(
    view: PlayerView, model: RehuDocumentModel, button_name: str, action_name: str
) -> None:
    """A button's default action is applied again, with a new connection, whenever it changes; made on the GUI thread
    while Qt Multimedia destroyed its renderer, that connection deadlocked the app (#573).

    **Test steps:**

    * load a video, so every transport action is enabled
    * verify the button holds no default action and shows the action's text and enabled state
    * change the action's text, tooltip and icon and disable it, and verify the button follows
    * enable it again, click the button, and verify the action was triggered
    """
    load_paused(view, model, "02.mp4")
    button = view.findChild(QToolButton, button_name)
    action = action_of(view, action_name)
    assert isinstance(button, QToolButton)

    assert button.defaultAction() is None
    assert (button.text(), button.isEnabled()) == (action.text(), action.isEnabled())

    action.setText("changed")
    action.setToolTip("why")
    action.setIcon(QIcon(QPixmap(4, 4)))
    action.setEnabled(False)
    assert (button.text(), button.toolTip(), button.isEnabled()) == ("changed", "why", False)
    assert button.icon().cacheKey() == action.icon().cacheKey()

    action.setEnabled(True)
    triggered = []
    action.triggered.connect(lambda: triggered.append(True))
    button.click()
    assert triggered == [True]
