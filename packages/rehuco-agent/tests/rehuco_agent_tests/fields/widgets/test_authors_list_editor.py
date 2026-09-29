"""Tests for AuthorsListEditor: the shared list machinery (#231, #97) wearing the ``authors`` columns."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QLineEdit, QToolButton, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import AuthorsListEditor
from rehuco_agent.fields.widgets.authors_table_model import MISSING_NAME_REASON, NAME_COLUMN, URL_COLUMN


# region helpers
@fixture
def editor(qtbot: QtBot) -> AuthorsListEditor:
    """An editor over two entries: one plain name, one record carrying a URL.

    :param qtbot: the widget-owning fixture.
    :returns: the seeded editor.
    """
    widget = AuthorsListEditor()
    qtbot.addWidget(widget)
    widget.set_entries(["Alice", {"name": "Bob", "url": "https://example.com/bob"}])
    return widget


def select(editor: AuthorsListEditor, row: int) -> None:
    """Make ``row`` the current one.

    :param editor: the editor to select in.
    :param row: the row to make current.
    """
    editor.view.setCurrentIndex(editor.model.index(row, NAME_COLUMN))


def leave_for(editor: AuthorsListEditor, row: int, qtbot: QtBot, rows_left: int) -> None:
    """Make ``row`` current and wait for the editor to act on the row that was left.

    :param editor: the editor to move in.
    :param row: the row to make current.
    :param qtbot: the waiting fixture.
    :param rows_left: how many rows the model holds once the left row has been dealt with -- a row is
        abandoned on a later pass through the event loop, so the outcome is waited for.
    """
    select(editor, row)
    qtbot.waitUntil(lambda: editor.model.rowCount() == rows_left)


def open_editor() -> QLineEdit:
    """The in-place editor currently open, as the focused widget.

    :returns: the delegate's editor line edit.
    """
    QApplication.processEvents()
    focused = QApplication.focusWidget()
    assert isinstance(focused, QLineEdit), "no in-place editor is open"
    return focused


def press(key: Qt.Key) -> None:
    """Press ``key`` in the open in-place editor and let the delegate act on it.

    :param key: the key to press.
    """
    QTest.keyClick(open_editor(), key)
    QApplication.processEvents()


def drop_link(editor: AuthorsListEditor, row: int, column: int, url: str) -> bool:
    """Drag a link over one cell and drop it there, as a window system would.

    :param editor: the editor whose cell is targeted.
    :param row: the cell's row.
    :param column: the cell's column.
    :param url: the link being dropped.
    :returns: whether the drop was accepted.
    """
    data = QMimeData()
    data.setUrls([QUrl(url)])
    viewport = editor.view.viewport()
    centre = editor.view.visualRect(editor.model.index(row, column)).center()
    action = Qt.DropAction.CopyAction
    buttons = Qt.MouseButton.LeftButton
    modifiers = Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(viewport, QDragEnterEvent(centre, action, data, buttons, modifiers))
    drop = QDropEvent(QPointF(centre), action, data, buttons, modifiers)
    QApplication.sendEvent(viewport, drop)
    return drop.isAccepted()


@fixture
def shown(editor: AuthorsListEditor, qtbot: QtBot) -> AuthorsListEditor:
    """The seeded editor, shown so its in-place editors take focus and keystrokes.

    :param editor: the seeded editor.
    :param qtbot: the widget-owning fixture.
    :returns: the same editor.
    """
    with qtbot.waitExposed(editor):
        editor.show()
    return editor


# endregion


def test_it_is_the_shared_list_machinery(editor: AuthorsListEditor) -> None:
    """The buttons, the keys and the one-model-call rule are the same ones the settings pages get.

    **Test steps:**

    * verify the editor is an `ItemListEditor` over a row-sized table
    """
    assert isinstance(editor, ItemListEditor)
    assert isinstance(editor.view, ContentSizedTableView)


def test_the_entries_round_trip(editor: AuthorsListEditor) -> None:
    """What is set is what is read back, in canonical minimal form.

    **Test steps:**

    * read the seeded entries
    * verify both came back as they went in
    """
    assert editor.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})


def test_an_edit_is_reported_once(editor: AuthorsListEditor) -> None:
    """The model's own signals are what report an edit -- one path in, one path out.

    **Test steps:**

    * record every ``values_changed`` and commit a name through the model
    * verify exactly one edit was reported, carrying the new entry
    """
    edits: list[int] = []
    editor.values_changed.connect(lambda: edits.append(1))

    editor.model.setData(editor.model.index(0, NAME_COLUMN), "Alicia")

    assert edits == [1]
    assert editor.entries[0] == "Alicia"


def test_the_move_actions_reorder_the_authors(editor: AuthorsListEditor) -> None:
    """Credit order is the data, so the ordering column is shown and does the reordering.

    **Test steps:**

    * make the first author current and move it down
    * verify the two swapped
    """
    select(editor, 0)

    editor.ordering_actions.move_down_action.trigger()

    assert editor.entries[1] == "Alice"


def test_delete_drops_the_current_author(editor: AuthorsListEditor) -> None:
    """The item actions act on the current row, exactly as they do for a string list.

    **Test steps:**

    * make the second author current and delete it
    * verify only the first is left
    """
    select(editor, 1)

    editor.item_actions.delete_action.trigger()

    assert editor.entries == ("Alice",)


def test_the_reset_button_is_hidden(editor: AuthorsListEditor) -> None:
    """A default set of authors would be someone else's authors -- Reset is built (every item column
    carries one, wired to the model's no-op `reset()`) but hidden outright, not merely disabled.

    **Test steps:**

    * read the reset action's visibility and its button's
    * verify both are hidden
    """
    reset_action = editor.item_actions.reset_action
    button = next(
        button for button in editor.item_actions.findChildren(QToolButton) if button.defaultAction() is reset_action
    )

    assert reset_action.isVisible() is False
    assert button.isVisible() is False


def test_the_table_shows_one_author_per_row(editor: AuthorsListEditor) -> None:
    """A row is an author: no row numbers, no grid, and both columns sharing the width.

    **Test steps:**

    * read the table's chrome and column resize modes
    * verify rows are selected whole, the vertical header is gone, and both columns stretch
    """
    table = editor.view
    assert isinstance(table, ContentSizedTableView)

    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.verticalHeader().isVisible() is False
    assert table.showGrid() is False
    header = table.horizontalHeader()
    assert header.sectionResizeMode(NAME_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(URL_COLUMN) == QHeaderView.ResizeMode.Stretch


# region a row can be started from either column


def test_an_insert_given_only_a_url_stays_with_its_name_flagged(shown: AuthorsListEditor, qtbot: QtBot) -> None:
    """Tabbing from the name to the URL cell is not leaving the row, and a URL keeps it.

    **Test steps:**

    * insert below the first row, Tab past the empty name and type a URL
    * move to another row
    * verify the row is still there with the URL, its name flagged, and left out of the entries
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()

    press(Qt.Key.Key_Tab)
    QTest.keyClicks(open_editor(), "https://example.com/carol")
    press(Qt.Key.Key_Return)
    leave_for(shown, 0, qtbot, rows_left=3)
    QTest.qWait(10)  # long enough for a removal that must not happen to have happened

    assert shown.model.rowCount() == 3
    assert shown.model.index(1, URL_COLUMN).data() == "https://example.com/carol"
    assert shown.model.data(shown.model.index(1, NAME_COLUMN), Qt.ItemDataRole.ToolTipRole) == MISSING_NAME_REASON
    assert shown.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})


def test_an_insert_left_with_both_cells_blank_is_removed(shown: AuthorsListEditor, qtbot: QtBot) -> None:
    """Passing through the URL cell without typing leaves nothing to keep.

    **Test steps:**

    * insert below the first row, Tab to the URL cell and type nothing
    * move to another row
    * verify the list is as it was, and nothing was reported
    """
    edits: list[int] = []
    shown.values_changed.connect(lambda: edits.append(1))
    select(shown, 0)
    shown.item_actions.insert_action.trigger()

    press(Qt.Key.Key_Tab)
    leave_for(shown, 0, qtbot, rows_left=2)

    assert shown.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})
    assert not edits


def test_an_insert_waits_while_focus_stays_in_the_list(shown: AuthorsListEditor) -> None:
    """Leaving the name cell only moves the row's editing along; the row is not abandoned by it.

    **Test steps:**

    * insert below the first row and Tab to the URL cell
    * verify the blank row is still there while its URL editor is open
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()

    press(Qt.Key.Key_Tab)

    assert shown.model.rowCount() == 3


def test_an_insert_left_by_focusing_outside_the_list_is_removed(qtbot: QtBot) -> None:
    """Focus going to something outside the view is leaving, though the current row never changed.

    **Test steps:**

    * put the editor beside another focusable widget, insert a row and Tab to its URL cell
    * focus the other widget
    * verify the blank row is gone
    """
    page = QWidget()
    qtbot.addWidget(page)
    layout = QVBoxLayout(page)
    list_editor = AuthorsListEditor()
    other = QLineEdit()
    layout.addWidget(list_editor)
    layout.addWidget(other)
    list_editor.set_entries(["Alice"])
    with qtbot.waitExposed(page):
        page.show()
    page.activateWindow()
    select(list_editor, 0)
    list_editor.item_actions.insert_action.trigger()
    press(Qt.Key.Key_Tab)
    assert list_editor.model.rowCount() == 2

    other.setFocus()
    qtbot.waitUntil(lambda: list_editor.model.rowCount() == 1)

    assert list_editor.entries == ("Alice",)


def test_tabbing_out_of_the_url_cell_abandons_the_row_and_opens_the_next_rows_name(
    shown: AuthorsListEditor, qtbot: QtBot
) -> None:
    """Leaving the row by Tab from its last cell removes it *after* Qt has opened the next row's editor,
    so that editor lands on the row that was meant, not on whatever shifted into its place.

    **Test steps:**

    * insert below the first row, Tab to the URL cell and Tab again, into Bob's name
    * verify the blank row is gone and the open editor shows Bob
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()
    press(Qt.Key.Key_Tab)

    press(Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: shown.model.rowCount() == 2)

    assert shown.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})
    assert open_editor().text() == "Bob"


def test_escape_on_the_new_rows_first_editor_removes_it_at_once(shown: AuthorsListEditor) -> None:
    """Cancelling the insert is not a way of leaving the row, it is undoing it.

    **Test steps:**

    * insert below the first row and press Escape in its name editor
    * verify the row is gone immediately
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()

    press(Qt.Key.Key_Escape)

    assert shown.model.rowCount() == 2


def test_a_second_insert_overtakes_a_blank_row_that_was_waiting(shown: AuthorsListEditor, qtbot: QtBot) -> None:
    """Inserting again makes the new row current, which leaves the waiting blank one behind.

    **Test steps:**

    * insert below the first row and Tab to the URL cell, then insert again
    * verify only one blank row remains once the event loop has run
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()
    press(Qt.Key.Key_Tab)

    shown.item_actions.insert_action.trigger()
    qtbot.waitUntil(lambda: shown.model.rowCount() == 3)

    assert shown.model.rowCount() == 3


def test_a_waiting_row_filled_before_a_second_insert_settles_is_kept(shown: AuthorsListEditor) -> None:
    """The sweep of the overtaken row asks again whether it is still blank.

    **Test steps:**

    * insert and Tab to the URL cell, then insert again
    * give the overtaken row a URL before the event loop runs
    * verify both rows are still there afterwards
    """
    select(shown, 0)
    shown.item_actions.insert_action.trigger()
    press(Qt.Key.Key_Tab)
    shown.item_actions.insert_action.trigger()

    shown.model.setData(shown.model.index(1, URL_COLUMN), "https://example.com/kept")
    QApplication.processEvents()
    QTest.qWait(10)

    assert shown.model.rowCount() == 4


# endregion

# region a link dropped on a cell


def test_a_link_dropped_on_the_url_cell_sets_it_whether_or_not_the_row_has_a_name(shown: AuthorsListEditor) -> None:
    """A drop aimed at a URL cell is a plain URL for that cell, with no name required.

    **Test steps:**

    * insert a blank row through the model and drop a link on its URL cell
    * move to another row
    * verify the URL landed and the row stayed, pending a name
    """
    shown.model.insertRows(1, 1)
    accepted = drop_link(shown, 1, URL_COLUMN, "https://example.com/dropped")
    select(shown, 0)

    assert accepted
    assert shown.model.rowCount() == 3
    assert shown.model.index(1, URL_COLUMN).data() == "https://example.com/dropped"


def test_a_drop_that_carries_no_link_is_left_alone(shown: AuthorsListEditor) -> None:
    """Plain text over a URL cell is not a link, so the cell is not touched.

    **Test steps:**

    * drop plain text on the URL cell of the first row
    * verify the drop was not taken and the row is unchanged
    """
    data = QMimeData()
    data.setText("just some words")
    viewport = shown.view.viewport()
    centre = shown.view.visualRect(shown.model.index(0, URL_COLUMN)).center()
    args = (Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, QDragEnterEvent(centre, *args))
    drop = QDropEvent(QPointF(centre), *args)

    QApplication.sendEvent(viewport, drop)

    assert not drop.isAccepted()
    assert shown.entries[0] == "Alice"


class DropHost(QWidget):
    """A widget around the editor that accepts drops, like the Main Editor dock, and records the ones it got."""

    def __init__(self) -> None:
        super().__init__()
        self.dropped = False
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt override)
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt override)
        self.dropped = True
        event.acceptProposedAction()


@fixture
def hosted(qtbot: QtBot) -> tuple[AuthorsListEditor, DropHost]:
    """An editor with one author, inside a widget that accepts drops.

    :param qtbot: the widget-owning fixture.
    :returns: the editor and its host, shown.
    """
    host = DropHost()
    qtbot.addWidget(host)
    list_editor = AuthorsListEditor()
    QVBoxLayout(host).addWidget(list_editor)
    list_editor.set_entries(["Alice"])
    with qtbot.waitExposed(host):
        host.show()
    return list_editor, host


def test_a_link_dropped_on_the_name_cell_is_left_to_the_host(hosted: tuple[AuthorsListEditor, DropHost]) -> None:
    """A drop that is not on a URL cell is nobody's here, and reaches the widget that takes drops around it.

    **Test steps:**

    * drop a link on a name cell
    * verify the host got it and the list is unchanged
    """
    list_editor, host = hosted

    drop_link(list_editor, 0, NAME_COLUMN, "https://example.com/x")

    assert host.dropped
    assert list_editor.entries == ("Alice",)


def test_a_link_dropped_on_a_url_cell_is_not_left_to_the_host(hosted: tuple[AuthorsListEditor, DropHost]) -> None:
    """A drop aimed at a cell wins over the widget around the editor that would take it for the whole.

    **Test steps:**

    * drop a link on the URL cell of the only row
    * verify the URL was set and the host never saw the drop
    """
    list_editor, host = hosted

    drop_link(list_editor, 0, URL_COLUMN, "https://example.com/x")

    assert not host.dropped
    assert list_editor.entries == ({"name": "Alice", "url": "https://example.com/x"},)


# endregion
