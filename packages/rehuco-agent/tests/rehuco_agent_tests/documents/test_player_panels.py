"""Tests for the tree and the notes beside the player's picture, in a real document (#575,
[[plugins#player-maximized]]).

A real tutorial under ``tmp_path`` in a real document widget, so the panels are the ones the document builds and share
what the docks show. What is tested is how they show and hide, what the keys do while one has the keyboard, and what the
stage remembers of them.
"""

# the player's and the stage's own parts are reached through their name-mangled members, as the other player tests do
# astroid reads the sub-docks' name-to-dock dict's values as signals
# pylint: disable=protected-access,no-member

from typing import Final
from unittest.mock import Mock

import cbor2
from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QSplitter, QTreeView, QWidget
from pytest import fixture, mark, param
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import player_stage
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.notes_panel import NotesPanel
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.video_notes_edit import VideoNotesEdit
from rehuco_agent.documents.video_tree_view import VideoTreeView

from .player_view_support import fixture_media  # noqa: F401  # pylint: disable=unused-import
from .test_document_sub_docks_notes import notes_panel as dock_notes_panel
from .test_document_sub_docks_notes import player_of
from .test_document_sub_docks_player import player_dock
from .test_document_sub_docks_tree import tree_view as dock_tree_view
from .video_tree_support import fixture_model  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("real_path_stat")

TIMEOUT: Final = 5000
KEY: Final = "01 Basics/c.mp4"
MISSING: Final = "gone.mp4"
"""A video the tutorial no longer has, whose notes stay (#571)."""


class Stage:
    """A shown document with its player current, and the parts of the stage the tests reach."""

    def __init__(self, widget: DocumentWidget) -> None:
        self.widget = widget
        self.player: PlayerView = player_of(widget)
        self.tree = next(view for view in self.player.findChildren(VideoTreeView))
        self.notes = next(panel for panel in self.player.findChildren(NotesPanel))
        self.picture: QWidget = self.player._PlayerView__ui.surface_stack  # type: ignore[attr-defined]
        self.side: QWidget = self.player._PlayerView__ui.side_splitter  # type: ignore[attr-defined]

    def action(self, name: str) -> QAction:
        """One of the player's actions.

        :param name: its object name.
        :returns: the action.
        """
        found = self.player.findChild(QAction, name)
        assert found is not None
        return found

    def spy(self, name: str) -> Mock:
        """Count the triggers of one of the player's actions.

        :param name: its object name.
        :returns: the mock each trigger calls.
        """
        mock = Mock()
        self.action(name).triggered.connect(mock)
        return mock

    @property
    def editor(self) -> QWidget:
        """The ``N`` panel's editor of the video's notes."""
        return self.notes._NotesPanel__video_edit  # type: ignore[attr-defined]


@fixture(name="stage")
def fixture_stage(qtbot: QtBot, model: RehuDocumentModel) -> Stage:
    """A shown tutorial document with the player current and its videos listed.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the stage.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    widget.resize(1300, 800)
    widget.show()
    qtbot.waitExposed(widget)
    player_dock(widget).toggleView(True)
    player_dock(widget).setAsCurrentTab()
    qtbot.waitActive(widget)
    return Stage(widget)


def test_the_panels_start_hidden_and_the_picture_has_the_stage(stage: Stage) -> None:
    """**Test steps:**

    * build the stage
    * verify the tree, the notes and the column on the right are hidden, and the player has them as its own
    """
    assert not any(part.isVisibleTo(stage.player) for part in (stage.tree, stage.notes, stage.side))
    assert stage.tree is not dock_tree_view(stage.widget) and stage.notes is not dock_notes_panel(stage.widget)
    assert stage.player.panels.attached


@mark.parametrize(
    ("tree", "notes", "info"),
    [
        param(True, False, False, id="tree"),
        param(False, True, False, id="notes"),
        param(False, False, True, id="info"),
        param(True, True, False, id="tree-and-notes"),
        param(False, True, True, id="notes-and-info"),
        param(True, True, True, id="all"),
    ],
)
def test_each_panel_toggles_on_its_own_and_the_picture_makes_room(
    stage: Stage, qtbot: QtBot, tree: bool, notes: bool, info: bool
) -> None:
    """**Test steps:**

    * show some of the tree, the notes and the info
    * verify exactly those show, the column on the right shows while the notes or the info do, and the picture shrank
    * hide them all and verify the picture has its width back
    """
    before = stage.picture.width()

    for name, shown in (("tree_action", tree), ("notes_action", notes), ("info_action", info)):
        stage.action(name).setChecked(shown)

    qtbot.waitUntil(lambda: stage.picture.width() < before, timeout=TIMEOUT)
    assert stage.tree.isVisibleTo(stage.player) is tree
    assert stage.notes.isVisibleTo(stage.player) is notes
    assert stage.side.isVisibleTo(stage.player) is (notes or info)
    for name in ("tree_action", "notes_action", "info_action"):
        stage.action(name).setChecked(False)
    qtbot.waitUntil(lambda: stage.picture.width() == before, timeout=TIMEOUT)
    assert stage.side.isHidden()


def test_the_panels_go_with_the_stage_when_the_player_is_maximized(stage: Stage) -> None:
    """**Test steps:**

    * show the tree and the notes, and maximize the player
    * verify they are inside the overlay and still show
    * put the player back and verify they are in the player again
    """
    stage.action("tree_action").setChecked(True)
    stage.action("notes_action").setChecked(True)

    stage.player._PlayerView__stage.maximizer.toggle(Qt.KeyboardModifier.NoModifier)  # type: ignore[attr-defined]

    overlay = stage.player._PlayerView__stage.maximizer.overlay  # type: ignore[attr-defined]
    assert overlay is not None and overlay.isAncestorOf(stage.tree) and overlay.isAncestorOf(stage.notes)
    assert stage.tree.isVisibleTo(overlay) and stage.notes.isVisibleTo(overlay)
    stage.player._PlayerView__stage.maximizer.restore()  # type: ignore[attr-defined]
    assert stage.player.isAncestorOf(stage.tree) and stage.player.isAncestorOf(stage.notes)


def test_showing_a_panel_takes_no_keyboard(stage: Stage) -> None:
    """**Test steps:**

    * give the player the keyboard and show the tree and the notes
    * verify the keyboard is still the player's
    """
    stage.player.setFocus()
    before = QApplication.focusWidget()

    stage.action("tree_action").setChecked(True)
    stage.action("notes_action").setChecked(True)

    assert QApplication.focusWidget() is before


def test_a_panel_hidden_while_it_has_the_keyboard_hands_it_to_the_player(stage: Stage) -> None:
    """**Test steps:**

    * show the tree and put the keyboard in it
    * hide it and verify the keyboard is the player's, so its keys still answer
    """
    stage.action("tree_action").setChecked(True)
    tree = stage.tree.findChild(QTreeView, "tree_view")
    assert tree is not None
    tree.setFocus()
    assert QApplication.focusWidget() is tree

    stage.action("tree_action").setChecked(False)

    focused = QApplication.focusWidget()
    assert focused is stage.player or (focused is not None and stage.player.isAncestorOf(focused))
    assert focused is not tree


def test_the_notes_hidden_while_they_have_the_keyboard_hand_it_to_the_player(stage: Stage) -> None:
    """**Test steps:**

    * show the notes, edit them and put the keyboard in the editor
    * hide the notes and verify the keyboard is the player's
    """
    stage.action("notes_action").setChecked(True)
    stage.notes.title_bar_actions[0].setChecked(True)
    QWidget.setFocus(stage.editor)  # type: ignore[call-overload]
    assert QApplication.focusWidget() is stage.editor

    stage.action("notes_action").setChecked(False)

    assert QApplication.focusWidget() is stage.player


def test_hiding_the_notes_writes_what_was_typed(stage: Stage, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * show the notes of a video, edit them and type
    * hide the notes
    * verify what was typed is in the document
    """
    stage.action("notes_action").setChecked(True)
    stage.notes.set_video(KEY)
    stage.notes.title_bar_actions[0].setChecked(True)
    stage.editor.setText("typed")  # type: ignore[attr-defined]

    stage.action("notes_action").setChecked(False)

    assert model.video_notes_of(KEY) == "typed"


def test_the_notes_panel_and_the_dock_show_one_text(stage: Stage) -> None:
    """**Test steps:**

    * edit the same video in the dock and in the player's panel and type in the player's
    * verify the dock's editor holds the same text
    """
    dock = dock_notes_panel(stage.widget)
    dock.set_video(KEY)
    for panel in (dock, stage.notes):
        panel.title_bar_actions[0].setChecked(True)

    stage.editor.setText("typed")  # type: ignore[attr-defined]

    assert VideoNotesEdit.text_of(dock._NotesPanel__video_edit) == "typed"  # type: ignore[attr-defined]
    assert stage.notes.video_key == KEY


def test_a_video_playing_changes_the_tree_and_the_notes_beside_it(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * show the tree and the notes, and select a video in the player
    * verify the tree marks it and the notes show it
    """
    stage.action("tree_action").setChecked(True)
    stage.action("notes_action").setChecked(True)
    qtbot.waitUntil(lambda: stage.tree.tree.rowCount() > 0, timeout=TIMEOUT)

    stage.player.seek(KEY)

    qtbot.waitUntil(lambda: stage.tree.tree.current_key == KEY, timeout=TIMEOUT)
    assert stage.notes.video_key == KEY


# region Keys


def type_into(widget: QWidget, text: str) -> None:
    """Press keys on the focused widget, as the user would, shortcut check included.

    :param widget: the widget.
    :param text: the keys, as `QTest` takes them.
    """
    QTest.keyClicks(widget, text)


def test_typing_in_the_notes_editor_triggers_none_of_the_players_keys(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * select a video, edit the notes in the player's panel with the keyboard in the editor
    * type keys the player binds -- Space, b, i, t, n, brackets -- and an arrow
    * verify none of the player's actions fired, and the editor holds what was typed
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.action("notes_action").setChecked(True)
    stage.notes.title_bar_actions[0].setChecked(True)
    names = ("play_pause_action", "add_note_at_action", "info_action", "tree_action", "notes_action")
    spies = [stage.spy(name) for name in names]
    QWidget.setFocus(stage.editor)
    assert QApplication.focusWidget() is stage.editor

    type_into(stage.editor, "b i t n [] x")
    QTest.keyClick(stage.editor, Qt.Key.Key_Left)

    assert [spy.call_count for spy in spies] == [0] * len(names)
    assert VideoNotesEdit.text_of(stage.editor) == "b i t n [] x"  # type: ignore[arg-type]
    assert stage.action("tree_action").isChecked() is False


def test_the_arrows_in_the_tree_move_its_rows_and_the_other_keys_stay_the_players(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * select a video, show the tree and put the keyboard in it
    * press Down, Left and Up and verify the current row moved and nothing sought or changed the volume
    * press Space and Ctrl+Right and verify each reached the player once
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.action("tree_action").setChecked(True)
    qtbot.waitUntil(lambda: stage.tree.tree.rowCount() > 0, timeout=TIMEOUT)
    tree = stage.tree.findChild(QTreeView, "tree_view")
    assert tree is not None
    tree.setCurrentIndex(stage.tree.tree.index(0, 0, QModelIndex()))
    tree.setFocus()
    seeks = [stage.spy(name) for name in ("back_action", "forward_action", "volume_up_action", "volume_down_action")]
    toggle, next_video = stage.spy("play_pause_action"), stage.spy("next_action")
    before = tree.currentIndex()

    QTest.keyClick(tree, Qt.Key.Key_Down)
    moved = tree.currentIndex()
    QTest.keyClick(tree, Qt.Key.Key_Left)
    QTest.keyClick(tree, Qt.Key.Key_Up)

    assert moved != before
    assert [spy.call_count for spy in seeks] == [0, 0, 0, 0]
    QTest.keyClick(tree, Qt.Key.Key_Space)
    QTest.keyClick(tree, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert toggle.call_count == 1 and next_video.call_count == 1


def test_escape_in_the_editor_gives_the_player_the_keyboard_and_the_next_one_restores_it(stage: Stage) -> None:
    """**Test steps:**

    * maximize the player, show the notes and edit with the keyboard in the editor
    * press Esc and verify the keyboard is in the overlay and the player is still maximized
    * press Esc again and verify the player is back in its dock
    """
    maximizer = stage.player._PlayerView__stage.maximizer  # type: ignore[attr-defined]
    stage.action("notes_action").setChecked(True)
    stage.notes.set_video(KEY)
    stage.notes.title_bar_actions[0].setChecked(True)
    maximizer.toggle(Qt.KeyboardModifier.NoModifier)
    overlay = maximizer.overlay
    assert overlay is not None
    QWidget.setFocus(stage.editor)

    QTest.keyClick(stage.editor, Qt.Key.Key_Escape)

    assert maximizer.overlay is overlay and QApplication.focusWidget() is overlay
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert maximizer.overlay is None


# endregion


def test_f2_starts_editing_the_notes_and_ends_it_though_an_editor_claims_the_players_keys(
    stage: Stage, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """**Test steps:**

    * select a video and press F2 with the notes hidden
    * verify the notes show, edit, and hold the keyboard in their editor
    * type, press F2 in the editor, and verify the editing ended, what was typed was written and the player has
      the keyboard
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.player.setFocus()

    QTest.keyClick(stage.player, Qt.Key.Key_F2)

    assert stage.notes.isVisibleTo(stage.player) and stage.notes.editing
    assert QApplication.focusWidget() is stage.editor
    type_into(stage.editor, "typed")
    QTest.keyClick(stage.editor, Qt.Key.Key_F2)
    assert not stage.notes.editing
    assert model.video_notes_of(KEY) == "typed"
    assert QApplication.focusWidget() is stage.player


def test_hiding_the_notes_ends_the_editing_so_the_next_f2_starts_it(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * start editing with F2, then hide the notes with N
    * verify the editing ended with them
    * press F2 and verify the notes show, editing, with the keyboard in the editor
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.action("edit_notes_action").trigger()
    assert stage.notes.editing

    stage.action("notes_action").setChecked(False)

    assert not stage.notes.editing
    QTest.keyClick(stage.player, Qt.Key.Key_F2)
    assert stage.notes.isVisibleTo(stage.player) and stage.notes.editing
    assert QApplication.focusWidget() is stage.editor


def test_f2_edits_the_notes_of_a_missing_video(stage: Stage, qtbot: QtBot, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * show the notes of a missing video that has some, as a tree click does
    * press F2 and verify its editor is edited and holds them: a note outlives its file (owner)
    """
    model.record_notes(video_notes={MISSING: "kept after the file went"})
    stage.notes.set_video(MISSING)
    qtbot.waitUntil(lambda: not stage.notes.searching, timeout=TIMEOUT)
    stage.player.setFocus()

    QTest.keyClick(stage.player, Qt.Key.Key_F2)

    assert stage.notes.editing and stage.notes.video_key == MISSING
    assert QApplication.focusWidget() is stage.editor and stage.editor.isEnabled()
    assert VideoNotesEdit.text_of(stage.editor) == "kept after the file went"  # type: ignore[arg-type]


def test_escape_in_the_editor_ends_the_editing_too(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * start editing with F2 and press Esc in the editor
    * verify the editing ended and the player has the keyboard
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    stage.action("edit_notes_action").trigger()
    assert stage.notes.editing

    QTest.keyClick(stage.editor, Qt.Key.Key_Escape)

    assert not stage.notes.editing
    assert QApplication.focusWidget() is stage.player


def test_the_stage_state_carries_the_stages_split_alone_and_an_old_one_is_ignored(stage: Stage) -> None:
    """**Test steps:**

    * save the stage's state and verify it names the stage's split alone: the column's divider does not drag
    * restore a state in the old shape, one key for a two-part stage, and verify nothing changed
    * restore the saved state into the stage and verify it is read
    """
    saved = stage.player.save_state()
    assert set(cbor2.loads(saved)) == {"stage_split"}
    splitter = stage.player._PlayerView__ui.stage_splitter  # type: ignore[attr-defined]
    sizes = splitter.sizes()

    stage.player.restore_state(cbor2.dumps({"stage": bytes(splitter.saveState().data())}))
    assert splitter.sizes() == sizes

    stage.player.restore_state(saved)
    assert splitter.sizes() == sizes


# region The info above the notes


def text_height(info: QLabel) -> int:
    """The height its text needs at its width, measured from the font and not asked of the label, whose own answer
    follows the height it is fixed at.

    :param info: the info panel.
    :returns: the height of the wrapped text and the label's margins.
    """
    margin = info.margin() + info.frameWidth()
    rect = QRect(0, 0, info.width() - 2 * margin, 100_000)
    return info.fontMetrics().boundingRect(rect, int(Qt.TextFlag.TextWordWrap), info.text()).height() + 2 * margin


def show_info_and_notes(stage: Stage, qtbot: QtBot) -> tuple[QSplitter, QLabel]:
    """Show the info above the notes, with the layout settled.

    :param stage: the stage.
    :param qtbot: pytest-qt fixture.
    :returns: the column on the right and the info.
    """
    stage.action("info_action").setChecked(True)
    stage.action("notes_action").setChecked(True)
    ui = stage.player._PlayerView__ui  # type: ignore[attr-defined]
    info, side = ui.info_panel, ui.side_splitter
    qtbot.waitUntil(lambda: info.height() == text_height(info) and side.sizes()[1] > 0, timeout=TIMEOUT)
    return side, info


def test_above_the_notes_the_info_is_as_tall_as_its_text_and_the_notes_take_the_rest(
    stage: Stage, qtbot: QtBot
) -> None:
    """**Test steps:**

    * show a video's info above the notes
    * verify the info is as tall as its text at its width, and the notes have the rest of the column
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)

    side, info = show_info_and_notes(stage, qtbot)

    assert info.height() == text_height(info)
    assert side.sizes()[1] == side.height() - info.height() - side.handleWidth()
    assert side.sizes()[1] > info.height()


LONG_INFO: Final = "01 Basics/" + "a video whose name wraps onto several lines of a narrow column " * 12 + ".mp4"


def test_the_info_follows_a_longer_text_and_a_narrower_column(
    stage: Stage, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * show the info above the notes for a video, then give it a long text through the player, as a long name would
    * verify the info grew to the height of its wrapped text
    * narrow the column and verify it grew again to fit
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    side, info = show_info_and_notes(stage, qtbot)
    short = info.height()

    mocker.patch.object(player_stage, "player_info_text", return_value=LONG_INFO)
    stage.player._PlayerView__show_position(0)  # type: ignore[attr-defined]

    assert info.height() == text_height(info) > short
    assert side.sizes()[1] > 0
    wide = info.height()
    splitter = stage.player._PlayerView__ui.stage_splitter  # type: ignore[attr-defined]
    splitter.setSizes([0, 2000, 150])

    qtbot.waitUntil(lambda: info.height() > wide, timeout=TIMEOUT)
    assert info.height() == text_height(info)


def test_the_info_alone_fills_the_column_and_leaves_the_stage_its_height(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * show the info above the notes, note the stage's height, and hide the notes
    * verify the stage kept its height, which a fixed height on the info alone would cap, and the info fills the column
    * show the notes again and verify the info is back to the height of its text
    """
    side, info = show_info_and_notes(stage, qtbot)
    splitter = stage.player._PlayerView__ui.stage_splitter  # type: ignore[attr-defined]
    height = splitter.height()

    stage.action("notes_action").setChecked(False)

    qtbot.waitUntil(lambda: info.height() == side.height(), timeout=TIMEOUT)
    assert splitter.height() == height
    stage.action("notes_action").setChecked(True)
    qtbot.waitUntil(lambda: info.height() == text_height(info), timeout=TIMEOUT)
    assert splitter.height() == height


def test_the_info_and_the_notes_start_at_the_same_place_in_the_column(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * show the info above the notes for a video
    * verify the info's text and the notes' headings start the same distance into the column
    """
    stage.player.seek(KEY)
    qtbot.waitUntil(lambda: stage.player.current_key == KEY, timeout=TIMEOUT)
    side, info = show_info_and_notes(stage, qtbot)
    notes_ui = stage.notes._NotesPanel__ui  # type: ignore[attr-defined]

    info_start = info.mapTo(side, QPoint(0, 0)).x() + info.frameWidth() + info.margin()

    assert info_start == notes_ui.video_label.mapTo(side, QPoint(0, 0)).x()
    assert info_start == notes_ui.tutorial_label.mapTo(side, QPoint(0, 0)).x()


def test_the_info_and_the_two_notes_are_islands_as_the_tree_is_with_bold_titles(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * show the tree, and the info above the notes
    * verify the info and each part of the notes have the tree's frame
    * verify the notes' titles are bold and what they head is not
    """
    stage.action("tree_action").setChecked(True)
    _, info = show_info_and_notes(stage, qtbot)
    notes_ui = stage.notes._NotesPanel__ui  # type: ignore[attr-defined]
    tree = stage.tree.findChild(QTreeView, "tree_view")
    assert tree is not None

    for block in (info, notes_ui.video_part, notes_ui.tutorial_part):
        assert block.frameShape() == tree.frameShape()
    assert notes_ui.video_label.font().bold() and notes_ui.tutorial_label.font().bold()
    assert not notes_ui.video_view.font().bold() and not notes_ui.tutorial_view.font().bold()


def test_the_divider_above_the_notes_shows_and_does_not_drag(stage: Stage, qtbot: QtBot) -> None:
    """**Test steps:**

    * show the info above the notes
    * verify the divider shows with no resize cursor
    * drag it down and verify the column's split did not move
    """
    side, _ = show_info_and_notes(stage, qtbot)
    divider = side.handle(1)
    sizes = side.sizes()
    assert divider.isVisible() and not divider.isEnabled()
    assert divider.cursor().shape() == Qt.CursorShape.ArrowCursor

    QTest.mousePress(divider, Qt.MouseButton.LeftButton, pos=QPoint(5, 1))
    QTest.mouseMove(divider, QPoint(5, 100))
    QTest.mouseRelease(divider, Qt.MouseButton.LeftButton, pos=QPoint(5, 100))

    assert side.sizes() == sizes


# endregion
