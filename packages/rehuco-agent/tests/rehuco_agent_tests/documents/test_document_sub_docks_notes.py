"""Tests for a tutorial's notes dock in its document's sub-docks: where it sits, how it follows the player, what a link
in it does, how the player's *Add note* reaches it, and when it writes (#573, [[plugins#video-notes-dock]])."""

# astroid reads the sub-docks' name-to-dock dict's values as signals, and every call on a dock then fails
# pylint: disable=no-member

from unittest.mock import PropertyMock

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.theming import themed_svg_icon
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import VIEWER_DESCRIPTION_TAB
from rehuco_agent.documents.document_sub_docks import (
    NOTES_DOCK_MIN_HEIGHT,
    NOTES_DOCK_NAME,
    NOTES_DOCK_TITLE,
    NOTES_ICON_RESOURCE,
)
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.files_view import FilesView
from rehuco_agent.documents.notes_panel import NotesPanel
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_still import VideoStill
from rehuco_agent.settings.videos_settings import shared_videos_settings
from rehuco_core import RehuDocument

from .test_document_sub_docks_player import fixture_pack, player_dock  # noqa: F401  # pylint: disable=unused-import
from .test_document_sub_docks_tree import tree_dock, tree_view
from .test_document_widget import entry_widget_state, layout_dock_entries, saved_dock_entries


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a tutorial.

    :returns: the model.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}))


@fixture(name="widget")
def fixture_widget(qtbot: QtBot, model: RehuDocumentModel) -> DocumentWidget:
    """A tutorial's document widget.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the widget.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    return widget


def notes_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """A document's notes dock.

    :param widget: the document's widget.
    :returns: the dock.
    """
    dock = widget.sub_docks._DocumentSubDocks__type_docks[NOTES_DOCK_NAME]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert dock is not None
    return dock


def notes_panel(widget: DocumentWidget) -> NotesPanel:
    """A document's notes panel.

    :param widget: the document's widget.
    :returns: the panel.
    """
    panel = notes_dock(widget).widget()
    assert isinstance(panel, NotesPanel)
    return panel


def player_of(widget: DocumentWidget) -> PlayerView:
    """A document's player.

    :param widget: the document's widget.
    :returns: the player.
    """
    player = player_dock(widget).widget()
    assert isinstance(player, PlayerView)
    return player


def test_a_tutorial_has_a_notes_dock_that_starts_hidden(widget: DocumentWidget) -> None:
    """**Test steps:**

    * build a tutorial's widget
    * verify the dock hosts a `NotesPanel`, is named and titled, its toggle is unchecked, and it has a floor
    """
    dock = notes_dock(widget)

    assert isinstance(dock.widget(), NotesPanel)
    assert dock.objectName() == NOTES_DOCK_NAME
    assert dock.windowTitle() == NOTES_DOCK_TITLE
    assert dock.toggleViewAction().isChecked() is False
    assert dock.minimumSizeHint().height() == NOTES_DOCK_MIN_HEIGHT


def test_the_notes_toggle_follows_the_trees_with_its_own_icon(widget: DocumentWidget) -> None:
    """**Test steps:**

    * verify the toolbar carries the notes' toggle right after the tree's
    * verify the toggle's icon was built from the notes' own icon
    """
    action = notes_dock(widget).toggleViewAction()
    actions = widget.findChildren(QToolBar)[0].actions()

    assert actions.index(action) == actions.index(tree_dock(widget).toggleViewAction()) + 1
    assert action.icon().cacheKey() == themed_svg_icon(NOTES_ICON_RESOURCE).cacheKey()


def test_the_edit_action_is_on_the_notes_title_bar(widget: DocumentWidget) -> None:
    """**Test steps:**

    * verify the dock's title-bar actions are the panel's
    """
    assert notes_dock(widget).titleBarActions() == notes_panel(widget).title_bar_actions


def test_a_reference_pack_has_no_notes_dock(
    widget: DocumentWidget,
    pack: DocumentWidget,  # noqa: F811
) -> None:
    """**Test steps:**

    * build a tutorial's and a reference pack's widgets
    * verify only the tutorial built a notes panel
    """
    assert isinstance(notes_panel(widget), NotesPanel)
    assert pack.sub_docks._DocumentSubDocks__notes_panel is None  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_the_notes_follow_the_video_the_player_selects(widget: DocumentWidget) -> None:
    """**Test steps:**

    * have the player report a selected video, then none
    * verify the panel's video follows
    """
    player = player_of(widget)
    panel = notes_panel(widget)

    player.video_changed.emit("a.mp4")
    assert panel.video_key == "a.mp4"

    player.video_changed.emit(None)
    assert panel.video_key is None


def test_a_link_in_the_notes_takes_the_player_to_the_time_and_shows_it(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * have the panel report a link to a video, with a time and then without
    * verify the player was asked to seek each, and its dock was shown and made current
    """
    seek = mocker.patch.object(PlayerView, "seek")
    dock = player_dock(widget)

    notes_panel(widget).video_link_activated.emit("02.mp4", 65.0)
    notes_panel(widget).video_link_activated.emit("03.mp4", None)

    assert dock.toggleViewAction().isChecked() is True
    assert dock.isCurrentTab() is True  # type: ignore[attr-defined]
    assert [tuple(item.args) for item in seek.call_args_list] == [("02.mp4", 65.0), ("03.mp4", None)]


def test_a_note_asked_for_at_the_player_opens_the_notes_dock_in_edit(widget: DocumentWidget) -> None:
    """**Test steps:**

    * have the player ask for a note at a time
    * verify the notes dock was shown and made current, in edit, holding the bookmark line for that video
    """
    player_of(widget).note_requested.emit("02.mp4", 65.0)

    dock = notes_dock(widget)
    panel = notes_panel(widget)
    assert dock.toggleViewAction().isChecked() is True
    assert dock.isCurrentTab() is True  # type: ignore[attr-defined]
    assert panel.editing is True
    assert panel.video_key == "02.mp4"


def test_closing_the_notes_dock_writes_what_was_typed(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """**Test steps:**

    * show the dock and close it
    * verify the panel was flushed
    """
    flush = mocker.patch.object(NotesPanel, "flush")
    dock = notes_dock(widget)
    dock.toggleView(True)
    flush.reset_mock()

    dock.toggleView(False)

    flush.assert_called_once_with()


def test_stopping_playback_writes_what_was_typed_once(
    widget: DocumentWidget, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """What closing a document, switching the preview and quitting all do first.

    **Test steps:**

    * edit the tutorial's notes and type
    * stop the document's playback
    * verify the text was written, once
    """
    record = mocker.patch.object(model, "record_notes")
    panel = notes_panel(widget)
    panel.title_bar_actions[0].setChecked(True)
    panel._NotesPanel__tutorial_edit.setText("typed")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    widget.sub_docks.stop_playback()

    record.assert_called_once_with(notes="typed", video_notes=None)


def test_detaching_the_document_detaches_the_panel(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """**Test steps:**

    * detach the document
    * verify the panel was detached
    """
    detach = mocker.patch.object(NotesPanel, "detach")

    widget.sub_docks.detach()

    detach.assert_called_once_with()


def test_the_split_rides_in_the_notes_dock_entry_of_the_layout(widget: DocumentWidget) -> None:
    """**Test steps:**

    * save the widget's state
    * verify the notes dock's entry carries the panel's state under its object name
    """
    entry = saved_dock_entries(widget.save_state())[NOTES_DOCK_NAME]

    assert entry_widget_state(entry)["NotesPanel"] == notes_panel(widget).save_state()


def test_a_layout_that_never_names_the_notes_puts_them_back_hidden(widget: DocumentWidget) -> None:
    """**Test steps:**

    * save the widget's state with the notes open, then drop their entry from the layout
    * restore it
    * verify it restored, the notes are hidden, and they sit in the Description View's area
    """
    notes_dock(widget).toggleView(True)
    payload = cbor2.loads(widget.save_state())
    for entry in layout_dock_entries(payload["dock_manager"]):
        if entry["name"] == NOTES_DOCK_NAME:
            entry["name"] = "no such dock"

    assert widget.restore_state(cbor2.dumps(payload)) is True

    description = widget.sub_docks._DocumentSubDocks__viewer_docks[VIEWER_DESCRIPTION_TAB]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert notes_dock(widget).toggleViewAction().isChecked() is False
    assert notes_dock(widget).dockAreaWidget() is description.dockAreaWidget()


def test_a_type_switch_away_takes_the_notes_with_it(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * switch the tutorial to a reference pack
    * verify the panel and its toggle are gone
    * switch back and verify a new panel was built, hidden
    """
    toggle = notes_dock(widget).toggleViewAction()

    model.resource_type = "reference_images"

    assert widget.sub_docks._DocumentSubDocks__notes_panel is None  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert toggle not in widget.findChildren(QToolBar)[0].actions()

    model.resource_type = "tutorial"

    assert notes_dock(widget).toggleViewAction().isChecked() is False
    assert isinstance(notes_dock(widget).widget(), NotesPanel)


def files_view_of(widget: DocumentWidget) -> FilesView:
    """A document's Files view.

    :param widget: the document's widget.
    :returns: the view.
    """
    view = widget.sub_docks._DocumentSubDocks__files_dock.widget()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert isinstance(view, FilesView)
    return view


def test_a_video_clicked_in_the_tree_or_the_files_shows_its_notes_without_loading_it(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * click a video in the tree, then another in the Files dock
    * verify the panel shows each in turn and the player was neither jumped nor sought
    """
    jump = mocker.patch.object(PlayerView, "jump")
    seek = mocker.patch.object(PlayerView, "seek")

    tree_view(widget).video_clicked.emit("02.mp4")
    assert notes_panel(widget).video_key == "02.mp4"

    files_view_of(widget).video_clicked.emit("03.mp4")
    assert notes_panel(widget).video_key == "03.mp4"

    jump.assert_not_called()
    seek.assert_not_called()


def test_a_click_on_the_picture_shows_the_notes_of_the_video_loaded(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * show another video's notes while the player has a video loaded
    * click the player's picture
    * verify the panel shows the loaded video
    """
    mocker.patch.object(PlayerView, "current_key", new_callable=PropertyMock, return_value="a.mp4")
    notes_panel(widget).set_video("02.mp4")

    player_of(widget).surface_clicked.emit()

    assert notes_panel(widget).video_key == "a.mp4"


def test_a_press_on_the_player_surface_is_reported_as_a_click(widget: DocumentWidget, qtbot: QtBot) -> None:
    """**Test steps:**

    * press the left mouse button on the player's still picture
    * verify the click was reported
    * press the right button and verify it was not
    """
    still = player_of(widget).findChild(VideoStill)
    assert still is not None

    with qtbot.waitSignal(player_of(widget).surface_clicked):
        qtbot.mouseClick(still, Qt.MouseButton.LeftButton)
    with qtbot.assertNotEmitted(player_of(widget).surface_clicked):
        qtbot.mouseClick(still, Qt.MouseButton.RightButton)


def test_a_video_activated_or_linked_shows_that_videos_notes(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """**Test steps:**

    * activate a video from the tree, then follow a link to another in the notes
    * verify the panel shows each, whether or not the player's video changed
    """
    mocker.patch.object(PlayerView, "jump")
    mocker.patch.object(PlayerView, "seek")

    tree_view(widget).video_activated.emit("02.mp4", 65.0)
    assert notes_panel(widget).video_key == "02.mp4"

    notes_panel(widget).video_link_activated.emit("03.mp4", None)
    assert notes_panel(widget).video_key == "03.mp4"


def test_a_note_asked_for_with_the_choice_off_neither_shows_the_dock_nor_edits(widget: DocumentWidget) -> None:
    """**Test steps:**

    * switch the choice off and have the player ask for a note at a time
    * verify the notes dock stays hidden, nothing is being edited, and the note is in the video's notes
    """
    shared_videos_settings().add_note_edits = False

    player_of(widget).note_requested.emit("02.mp4", 65.0)

    assert notes_dock(widget).toggleViewAction().isChecked() is False
    assert notes_panel(widget).editing is False
    assert "t=65" in widget.sub_docks._DocumentSubDocks__model.video_notes_of("02.mp4")  # type: ignore[attr-defined]  # pylint: disable=protected-access
