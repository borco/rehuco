"""Tests for what each view of a tutorial or a folder remembers across a restart ([[plugins#session-restore]], #576):
the
tree's selected row, the notes shown and their editing, the player's video and panels, the Files sub-dock's folder and
the tables' sort.

A real tutorial under ``tmp_path`` in a real document widget, as ``test_player_panels`` has it.
"""

# the player's and the stage's own parts are reached through their name-mangled members, as the other player tests do
# pylint: disable=protected-access

from typing import Final
from unittest.mock import Mock

import cbor2
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication, QTreeView
from pytest import mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.notes_panel import NotesPanel
from rehuco_agent.documents.player_notices import PlayerNotices
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_tree_model import KIND_ROLE, NodeKind
from rehuco_agent.documents.video_tree_view import VideoTreeView
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings.maximized_view import CURATED_SET, LIGHTBOX_KIND, PLAYER_KIND, MaximizedView

from .player_view_support import fixture_media  # noqa: F401  # pylint: disable=unused-import
from .test_document_sub_docks_notes import notes_panel as dock_notes_panel
from .test_document_sub_docks_player import player_dock
from .test_document_sub_docks_tree import tree_view as dock_tree_view
from .test_player_panels import KEY, Stage, fixture_stage  # noqa: F401  # pylint: disable=unused-import
from .video_tree_support import fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

TIMEOUT: Final = 5000
OTHER: Final = "a.mp4"
BOOKMARK: Final = "- [1:05](rehuco-video:01%20Basics/c.mp4#t=65) the trick"


def tree_widget(view: VideoTreeView) -> QTreeView:
    """The tree widget of a view.

    :param view: the view.
    :returns: its tree.
    """
    return view._VideoTreeView__ui.tree_view  # type: ignore[attr-defined]


def row_of(view: VideoTreeView, kind: NodeKind) -> QModelIndex:
    """The first row of a kind, in a tree whose rows are all open.

    :param view: the view.
    :param kind: the kind.
    :returns: the row.
    """
    pending = [QModelIndex()]
    model = view.tree
    while pending:
        parent = pending.pop()
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if index.data(KIND_ROLE) == kind:
                return index
            pending.append(index)
    raise AssertionError(kind)


def shown_tree(qtbot: QtBot, model: RehuDocumentModel) -> VideoTreeView:
    """A shown tree whose rows are listed.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the view.
    """
    view = VideoTreeView(model)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.tree.rowCount() > 0, timeout=TIMEOUT)
    return view


# region The tree


@mark.parametrize(
    "kind", [param(NodeKind.VIDEO, id="video"), param(NodeKind.FOLDER, id="folder"), param(NodeKind.NOTE, id="note")]
)
def test_the_selected_row_comes_back_once_the_rows_are_listed(
    qtbot: QtBot, model: RehuDocumentModel, kind: NodeKind
) -> None:
    """A video, a folder or a note line is selected again in a tree that starts with no rows, saying nothing.

    **Test steps:**

    * select a row of the kind in a listed tree, and save the state
    * restore it into a hidden tree, which has listed nothing
    * show that tree, and verify the same row is selected and no video was reported clicked
    """
    model.record_notes(video_notes={KEY: BOOKMARK})
    source = shown_tree(qtbot, model)
    index = row_of(source, kind)
    tree_widget(source).setCurrentIndex(index)
    state = source.save_state()

    restored = VideoTreeView(model)
    qtbot.addWidget(restored)
    clicked = Mock()
    restored.video_clicked.connect(clicked)
    restored.restore_state(state)
    restored.show()

    qtbot.waitUntil(lambda: bool(tree_widget(restored).selectionModel().selectedRows()), timeout=TIMEOUT)
    assert tree_widget(restored).selectionModel().selectedRows()[0].data() == index.data()
    clicked.assert_not_called()


def test_a_tree_not_yet_listed_saves_the_row_it_was_given(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Quitting before a hidden tree has listed anything does not cost it the selected row.

    **Test steps:**

    * save the state of a listed tree with a selected row
    * restore it into a hidden tree, and save that one's state
    * verify the two name the same row
    """
    source = shown_tree(qtbot, model)
    tree_widget(source).setCurrentIndex(row_of(source, NodeKind.VIDEO))
    state = source.save_state()

    hidden = VideoTreeView(model)
    qtbot.addWidget(hidden)
    hidden.restore_state(state)

    assert cbor2.loads(hidden.save_state())["selected"] == cbor2.loads(state)["selected"]


def test_a_row_no_longer_there_selects_nothing_and_is_let_go(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A video gone since restores nothing, and is not held for ever.

    **Test steps:**

    * restore a state naming a video no longer in the tree, then list it
    * verify nothing is selected and the state names nothing
    """
    view = VideoTreeView(model)
    qtbot.addWidget(view)
    view.restore_state(cbor2.dumps({"selected": ["video", "gone.mp4", None], "closed": []}))

    view.show()
    qtbot.waitUntil(lambda: view.tree.rowCount() > 0, timeout=TIMEOUT)

    assert not tree_widget(view).selectionModel().selectedRows()
    assert cbor2.loads(view.save_state())["selected"] is None


def test_the_closed_rows_stay_closed(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A folder the reader closed is closed again in a tree restored after its rows were listed.

    **Test steps:**

    * close a folder of a listed tree, and save the state
    * restore it into another listed tree
    * verify that folder is closed there
    """
    source = shown_tree(qtbot, model)
    folder = row_of(source, NodeKind.FOLDER)
    tree_widget(source).collapse(folder)
    state = source.save_state()

    restored = shown_tree(qtbot, model)
    assert tree_widget(restored).isExpanded(row_of(restored, NodeKind.FOLDER))

    restored.restore_state(state)

    assert not tree_widget(restored).isExpanded(row_of(restored, NodeKind.FOLDER))


@mark.parametrize("state", [b"", b"not cbor", cbor2.dumps(["a list"]), cbor2.dumps({"selected": ["only", "two"]})])
def test_a_tree_state_it_cannot_read_changes_nothing(qtbot: QtBot, model: RehuDocumentModel, state: bytes) -> None:
    """A state of another shape costs the tree nothing.

    **Test steps:**

    * restore it into a listed tree
    * verify nothing is selected or closed
    """
    view = shown_tree(qtbot, model)

    view.restore_state(state)

    assert not tree_widget(view).selectionModel().selectedRows()
    assert tree_widget(view).isExpanded(row_of(view, NodeKind.FOLDER))


# endregion


# region The notes


def test_the_note_shown_and_its_editing_come_back_without_taking_the_keyboard(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A panel comes back on the same video's notes, in the editors, and the keyboard stays where it is.

    **Test steps:**

    * show a video's notes in a panel, edit them, and save its state
    * restore it into another panel with its own notes
    * verify that panel shows the video and edits it, and its editor holds no focus
    """
    source = NotesPanel(model)
    qtbot.addWidget(source)
    source.set_video(KEY)
    source.set_editing(True)
    state = source.save_state()

    restored = NotesPanel(model)
    qtbot.addWidget(restored)
    restored.show()
    restored.restore_state(state)

    assert restored.video_key == KEY
    assert restored.editing is True
    focused = QApplication.focusWidget()
    assert focused is None or not restored.isAncestorOf(focused)


def test_the_player_loading_its_video_does_not_take_a_restored_note_away(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A note picked from the tree need not be the player's video, and survives the player's own load; after that the
    notes follow the player as ever.

    **Test steps:**

    * restore a panel on one video's notes
    * report the player selecting another, and verify the note stays
    * report it selecting another again, and verify the note follows
    """
    source = NotesPanel(model)
    qtbot.addWidget(source)
    source.set_video(KEY)
    state = source.save_state()
    restored = NotesPanel(model)
    qtbot.addWidget(restored)
    restored.restore_state(state)

    restored.follow_player(OTHER)
    assert restored.video_key == KEY

    restored.follow_player(OTHER)
    assert restored.video_key == OTHER


def test_a_note_the_reader_picks_overtakes_the_one_restored(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A note picked before the player loads is the reader's, and the player's load follows as ever.

    **Test steps:**

    * restore a panel on one video's notes, then show another's
    * report the player selecting a third, and verify the notes follow it
    """
    source = NotesPanel(model)
    qtbot.addWidget(source)
    source.set_video(KEY)
    state = source.save_state()
    restored = NotesPanel(model)
    qtbot.addWidget(restored)
    restored.restore_state(state)

    restored.set_video(OTHER)
    restored.follow_player("01 Basics/b.mp4")

    assert restored.video_key == "01 Basics/b.mp4"


@mark.parametrize(
    "state", [b"", b"raw splitter bytes", cbor2.dumps(["a list"]), cbor2.dumps({"video": 3, "editing": "x"})]
)
def test_a_notes_state_it_cannot_read_changes_nothing(qtbot: QtBot, model: RehuDocumentModel, state: bytes) -> None:
    """A state of another shape, one an older build wrote among them, costs the panel nothing.

    **Test steps:**

    * restore it into a panel
    * verify it shows no video and is not editing
    """
    panel = NotesPanel(model)
    qtbot.addWidget(panel)

    panel.restore_state(state)

    assert panel.video_key is None
    assert panel.editing is False


# endregion


# region The player


def test_the_video_and_the_panels_come_back_with_the_document(stage: Stage, qtbot: QtBot) -> None:
    """The document's state holds the player's video and which panels show, the tree's row and the note's editing.

    **Test steps:**

    * load a video, show the three panels, select a row in the player's tree and edit the player's notes
    * save the document's state, then undo all of it
    * restore the state, and verify each is back
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    for name in ("info_action", "tree_action", "notes_action"):
        stage.action(name).setChecked(True)
    stage.notes.set_editing(True)
    tree = tree_widget(stage.tree)
    qtbot.waitUntil(lambda: stage.tree.tree.rowCount() > 0, timeout=TIMEOUT)
    row = row_of(stage.tree, NodeKind.VIDEO)
    tree.setCurrentIndex(row)
    selected = row.data()
    state = stage.widget.save_state()

    tree.clearSelection()
    stage.notes.set_editing(False)
    for name in ("info_action", "tree_action", "notes_action"):
        stage.action(name).setChecked(False)
    stage.player.seek(OTHER)
    qtbot.waitUntil(lambda: stage.player.current_key == OTHER, timeout=TIMEOUT)

    stage.widget.restore_state(state)

    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    for name in ("info_action", "tree_action", "notes_action"):
        assert stage.action(name).isChecked()
    assert stage.notes.editing is True
    assert tree.selectionModel().selectedRows()[0].data() == selected


def test_a_restored_video_loads_paused(stage: Stage, qtbot: QtBot) -> None:
    """Coming back never starts a video playing.

    **Test steps:**

    * ask the player to load a video the way a session does
    * verify it is selected, and the play action does not read as playing
    """
    stage.player.stop()

    stage.player.load_video(KEY)

    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    assert stage.player._PlayerView__session.name != "PLAY"  # type: ignore[attr-defined]


def test_a_video_gone_since_is_no_news_and_the_player_loads_what_it_would_have(
    stage: Stage, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A session's video no longer in the tutorial reports nothing: the player falls back on the one watched last.

    **Test steps:**

    * restore a state naming a video no longer there, and load
    * verify a video of the tutorial is selected, and no notice is shown
    """
    stage.player.stop()
    state = cbor2.loads(stage.player.save_state())
    state["video"] = "gone.mp4"
    stage.player.restore_state(cbor2.dumps(state))
    notice = mocker.spy(PlayerNotices, "add")

    stage.player.load_last()

    qtbot.waitUntil(lambda: stage.player.current_key is not None, timeout=TIMEOUT)
    assert stage.player.current_key != "gone.mp4"
    notice.assert_not_called()


def test_quitting_before_the_video_loads_keeps_it(stage: Stage) -> None:
    """A player whose dock was never shown has not loaded the session's video, and saves it again.

    **Test steps:**

    * stop the player, and restore a state naming a video
    * save the state, and verify it still names that video
    """
    stage.player.stop()
    state = cbor2.loads(stage.player.save_state())
    state["video"] = KEY
    stage.player.restore_state(cbor2.dumps(state))

    assert cbor2.loads(stage.player.save_state())["video"] == KEY


def test_capturing_a_maximized_player_says_so_and_puts_it_back(stage: Stage, qtbot: QtBot) -> None:
    """What is captured is what was maximized, with the stage back in the dock for the state walk to find.

    **Test steps:**

    * load a video and maximize the player over the document
    * capture, and verify the view names the video and the surface and the player is back in its dock
    * save the document's state, and verify the player's own tree was found in the dock
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.maximize(OverlayMode.DOCUMENT_OVERLAY)
    assert stage.player.overlay is not None

    view = stage.widget.capture_maximized()

    assert view is not None
    assert (view.kind, view.key, view.mode) == ("player", KEY, OverlayMode.DOCUMENT_OVERLAY.value)
    assert stage.player.overlay is None
    assert stage.player.maximized_mode is None
    entries = stage.widget.sub_docks._DocumentSubDocks__stateful_widgets_of(  # type: ignore[attr-defined]
        player_dock(stage.widget)
    )
    assert "stage_tree" in entries and "stage_notes" in entries


def test_a_maximized_player_comes_back_on_its_video(stage: Stage, qtbot: QtBot) -> None:
    """A session's player view selects its video and maximizes over the surface it was on, saying it did.

    **Test steps:**

    * capture a player maximized over the document, and stop it
    * restore the view
    * verify it is maximized on the video, paused, and the overlay was reported
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.maximize(OverlayMode.DOCUMENT_OVERLAY)
    view = stage.widget.capture_maximized()
    assert view is not None
    stage.player.stop()
    reported = Mock()
    stage.widget.maximized_restored.connect(reported)

    stage.widget.restore_maximized(view)

    qtbot.waitUntil(lambda: stage.player.maximized_mode is OverlayMode.DOCUMENT_OVERLAY, timeout=TIMEOUT)
    assert stage.player.current_key == KEY
    reported.assert_called_once_with(stage.player.overlay)


def test_a_maximized_player_whose_video_is_gone_restores_nothing(stage: Stage, qtbot: QtBot) -> None:
    """A key no longer in the tutorial does not maximize whatever the player falls back on.

    **Test steps:**

    * stop the player, and restore a view naming a video no longer there
    * verify the player falls back on another, and is not maximized, and nothing is held
    """
    stage.player.stop()

    stage.widget.restore_maximized(MaximizedView(PLAYER_KIND, "gone.mp4", OverlayMode.DOCUMENT_OVERLAY.value))

    qtbot.waitUntil(lambda: stage.player.current_key is not None, timeout=TIMEOUT)
    assert stage.player.maximized_mode is None
    assert stage.widget.capture_maximized() is None


# endregion


def test_each_of_the_views_keeps_its_own_state_in_the_docks_entry(stage: Stage) -> None:
    """The docks' own tree and notes and the player's are told apart: state is kept by object name.

    **Test steps:**

    * edit in the dock's notes only, and select in the dock's tree only
    * save and restore the document's state
    * verify the dock's panel is the one editing, and the player's is not
    """
    dock_panel = dock_notes_panel(stage.widget)
    dock_tree = dock_tree_view(stage.widget)
    dock_panel.set_editing(True)
    assert stage.notes.editing is False
    state = stage.widget.save_state()

    dock_panel.set_editing(False)
    stage.widget.restore_state(state)

    assert dock_panel.editing is True
    assert stage.notes.editing is False
    assert dock_tree.objectName() != stage.tree.objectName()


def test_a_maximized_player_takes_the_keyboard_when_its_document_does(stage: Stage, qtbot: QtBot) -> None:
    """Becoming the current document hands the keyboard to the view covering it, the player as much as a lightbox.

    **Test steps:**

    * load a video and maximize the player, and move the keyboard away from it
    * have the document take the focus, and verify the overlay holds it
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.maximize(OverlayMode.DOCUMENT_OVERLAY)
    overlay = stage.player.overlay
    assert overlay is not None
    overlay.clearFocus()

    stage.widget.take_focus()

    assert overlay.hasFocus()


def test_a_view_remembered_is_said_over_a_player_maximized_since(
    stage: Stage, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A view still waiting is the one to remember, and whatever is up is put back all the same.

    **Test steps:**

    * hold a lightbox view for a set that is not there, and maximize the player over a video
    * capture, and verify the view held is what is said, and the player is back in its dock
    """
    del mocker
    view = MaximizedView(LIGHTBOX_KIND, "shot.png", OverlayMode.DOCUMENT_OVERLAY.value, CURATED_SET)
    stage.widget.sub_docks._DocumentSubDocks__on_curated_images_changed([])  # type: ignore[attr-defined]
    stage.widget.restore_maximized(view)
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.maximize(OverlayMode.DOCUMENT_OVERLAY)

    assert stage.widget.capture_maximized() == view
    assert stage.player.overlay is None


def test_a_second_maximize_while_maximized_does_nothing(stage: Stage, qtbot: QtBot) -> None:
    """A restore landing while the reader has already maximized the player does not lift its parts a second time.

    **Test steps:**

    * maximize the player, then ask again on another surface
    * verify the one overlay stands, on the first surface
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.maximize(OverlayMode.DOCUMENT_OVERLAY)
    overlay = stage.player.overlay

    stage.player.maximize(OverlayMode.FULL_SCREEN)

    assert stage.player.overlay is overlay
    assert stage.player.maximized_mode is OverlayMode.DOCUMENT_OVERLAY
