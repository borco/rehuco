"""Tests for ItemListEditor's optional proxy, and its abandoned-insert rule on a row of several cells.

The rest of the widget -- the two columns, the shortcuts, the one-column abandoned-insert rule -- is
covered through `StringListEditor`, which is the unfiltered, single-cell case. What is here is what only a
proxy or a second cell can reach: which row space a caller and the action columns speak in, and when a
row that can be filled in any order is abandoned.
"""

from typing import Any, override

from borco_pyside.widgets import ContentSizedListView, ContentSizedTableView, ItemListEditor, StringItemListModel
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot

ENTRIES = ("alpha", "beta", "gamma", "delta")
"""Four entries, two of which the filter below keeps -- so a source row and a view row genuinely differ."""


class EvenRowsProxy(QSortFilterProxyModel):
    """Shows every other source row, so view row ``1`` is source row ``2``."""

    def filterAcceptsRow(  # noqa: N802  (Qt API name)
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        del source_parent
        return source_row % 2 == 0


@fixture
def editor(qtbot: QtBot) -> ItemListEditor:
    """An editor over :data:`ENTRIES`, seen through :class:`EvenRowsProxy`.

    :param qtbot: the widget-owning fixture.
    :returns: the editor, shown so its view is real.
    """
    model = StringItemListModel()
    widget = ItemListEditor(ContentSizedListView(), model, proxy=EvenRowsProxy())
    qtbot.addWidget(widget)
    model.set_entries(ENTRIES)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def test_the_view_shows_the_proxy_and_the_editor_still_holds_the_model(editor: ItemListEditor) -> None:
    """One model, one view onto part of it: a filtered list is not a second code path.

    **Test steps:**

    * verify the view is looking at the proxy, which shows half the rows
    * verify the editor's own ``model`` is still the unfiltered one
    """
    view_model = editor.view.model()
    assert isinstance(view_model, EvenRowsProxy)
    assert view_model.rowCount() == 2
    assert editor.model.rowCount() == len(ENTRIES)


def test_the_current_index_is_a_source_row(editor: ItemListEditor) -> None:
    """``current_index`` is stated in **source** rows -- the space every model call is already in, so the
    action columns hand it straight to the model without knowing a filter exists.

    **Test steps:**

    * make the second *visible* row current
    * verify the reported index is its source row, not its position on screen
    """
    editor.view.setCurrentIndex(editor.view.model().index(1, 0))

    assert editor.current_index == 2


def test_setting_the_current_index_takes_a_source_row(editor: ItemListEditor) -> None:
    """The setter is in the same space as the getter, so a model method's return value can be handed
    straight back -- which is exactly what the two action columns do.

    **Test steps:**

    * select source row ``2``
    * verify the view landed on the row showing that entry, and the getter agrees
    """
    editor.set_current_index(2)

    assert editor.view.currentIndex().data() == "gamma"
    assert editor.current_index == 2


def test_selecting_a_filtered_out_row_selects_nothing(editor: ItemListEditor) -> None:
    """A row the proxy does not show maps to an invalid index, which selects nothing -- the honest answer
    for a row that is not on screen to be current *on*.

    **Test steps:**

    * select a source row the filter hides
    * verify nothing is current
    """
    editor.set_current_index(1)

    assert editor.current_index == -1


def test_a_negative_row_still_selects_nothing(editor: ItemListEditor) -> None:
    """The select-none case is unchanged by a proxy: it never reaches the mapping at all.

    **Test steps:**

    * select a visible row, then a negative one
    * verify nothing is current
    """
    editor.set_current_index(0)

    editor.set_current_index(-1)

    assert editor.current_index == -1


# region Sample classes

type ModelIndex = QModelIndex | QPersistentModelIndex


class PairModel(QAbstractTableModel):
    """Rows of two typed cells and a third derived from them, the shape of a multi-field list.

    The third cell always shows text and is not editable, standing in for a checkbox or a computed
    column: it must not count as something the user entered.
    """

    count_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__rows: list[tuple[str, str]] = []
        self.rowsInserted.connect(self.count_changed)
        self.rowsRemoved.connect(self.count_changed)
        self.modelReset.connect(self.count_changed)

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """Every row's two typed cells."""
        return tuple(self.__rows)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        """Replace every row.

        :param rows: the rows to show.
        """
        self.beginResetModel()
        self.__rows = list(rows)
        self.endResetModel()

    @property
    def count(self) -> int:
        """How many rows there are."""
        return len(self.__rows)

    def insert(self, at: int) -> int:
        """Insert a blank row after ``at``, or at the end.

        :param at: the row to insert after.
        :returns: the new row.
        """
        target = at + 1 if at >= 0 else len(self.__rows)
        self.insertRow(target)
        return target

    def duplicate(self, at: int) -> int:
        """Not offered here.

        :param at: the current row.
        :returns: ``at``.
        """
        return at

    def delete(self, at: int) -> None:
        """Drop one row.

        :param at: the row to drop.
        """
        if at >= 0:
            self.removeRow(at)

    def reset(self) -> None:
        """No defaults here."""

    def move_to_top(self, at: int) -> int:
        """Not offered here.

        :param at: the current row.
        :returns: ``at``.
        """
        return at

    move_up = move_down = move_to_bottom = move_to_top

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 3

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return base if index.column() == 2 else base | Qt.ItemFlag.ItemIsEditable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        first, second = self.__rows[index.row()]
        return (first, second, f"{len(first) + len(second)} characters")[index.column()]

    @override
    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or index.column() == 2 or role != Qt.ItemDataRole.EditRole:
            return False
        first, second = self.__rows[index.row()]
        text = str(value).strip()
        replacement = (text, second) if index.column() == 0 else (first, text)
        if replacement == (first, second):
            return False
        self.__rows[index.row()] = replacement  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        return True

    @override
    def insertRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        del parent
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        self.__rows[row:row] = [("", "")] * count  # pylint: disable=unsupported-assignment-operation
        self.endInsertRows()
        return True

    @override
    def removeRows(self, row: int, count: int, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802
        del parent
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        del self.__rows[row : row + count]  # pylint: disable=unsupported-delete-operation
        self.endRemoveRows()
        return True


# endregion

# region a row of several cells


@fixture
def pairs(qtbot: QtBot) -> ItemListEditor:
    """An editor over two filled rows of :class:`PairModel`, shown so its cell editors take keys.

    :param qtbot: the widget-owning fixture.
    :returns: the editor.
    """
    model = PairModel()
    widget = ItemListEditor(ContentSizedTableView(), model)
    qtbot.addWidget(widget)
    model.set_rows([("a", "1"), ("b", "2")])
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def pair_model(editor: ItemListEditor) -> PairModel:
    """The editor's model, at its concrete type.

    :param editor: the editor to reach into.
    :returns: its pair model.
    """
    model = editor.model
    assert isinstance(model, PairModel)
    return model


def open_cell_editor() -> QLineEdit:
    """The in-place editor currently open, as the focused widget.

    :returns: the delegate's line edit.
    """
    QApplication.processEvents()
    focused = QApplication.focusWidget()
    assert isinstance(focused, QLineEdit), "no in-place editor is open"
    return focused


def press(key: Qt.Key) -> None:
    """Press ``key`` in the open in-place editor and let the delegate act on it.

    :param key: the key to press.
    """
    QTest.keyClick(open_cell_editor(), key)
    QApplication.processEvents()


def leave_for(editor: ItemListEditor, row: int, qtbot: QtBot, rows_left: int) -> None:
    """Make ``row`` current and wait for the editor to act on the row that was left.

    :param editor: the editor to move in.
    :param row: the row to make current.
    :param qtbot: the waiting fixture.
    :param rows_left: how many rows the model holds once the left row has been dealt with -- a row is
        abandoned on a later pass through the event loop, never from inside the signal that reported
        the leaving, so the outcome is waited for rather than assumed after one pass.
    """
    editor.set_current_index(row)
    qtbot.waitUntil(lambda: editor.model.rowCount() == rows_left)


def insert_and_tab_to_the_second_cell(editor: ItemListEditor) -> None:
    """Insert below the first row and move from its first cell to its second, typing nothing.

    :param editor: the editor to insert in.
    """
    editor.set_current_index(0)
    editor.item_actions.insert_action.trigger()
    press(Qt.Key.Key_Tab)


def test_moving_from_the_first_cell_to_the_second_keeps_the_insert(pairs: ItemListEditor) -> None:
    """Going on to another cell of the same row is not leaving it.

    **Test steps:**

    * insert and Tab to the second cell with nothing typed
    * verify the blank row is still there
    """
    insert_and_tab_to_the_second_cell(pairs)

    assert pair_model(pairs).rows == (("a", "1"), ("", ""), ("b", "2"))


def test_an_insert_left_for_another_row_with_nothing_typed_is_removed(pairs: ItemListEditor, qtbot: QtBot) -> None:
    """Leaving the row blank abandons it, silently.

    **Test steps:**

    * insert and Tab to the second cell with nothing typed, then make another row current
    * verify the list is as it was and nothing was reported
    """
    changes: list[None] = []
    pairs.values_changed.connect(lambda: changes.append(None))
    insert_and_tab_to_the_second_cell(pairs)

    leave_for(pairs, 0, qtbot, rows_left=2)

    assert pair_model(pairs).rows == (("a", "1"), ("b", "2"))
    assert not changes


def test_an_insert_whose_second_cell_is_filled_first_stays(pairs: ItemListEditor, qtbot: QtBot) -> None:
    """Text in any editable cell keeps the row, whatever order the cells are filled in.

    **Test steps:**

    * insert, Tab to the second cell and type into it, then make another row current
    * verify the row stayed with its first cell empty, reported as one edit
    """
    changes: list[None] = []
    pairs.values_changed.connect(lambda: changes.append(None))
    insert_and_tab_to_the_second_cell(pairs)
    QTest.keyClicks(open_cell_editor(), "9")
    press(Qt.Key.Key_Return)

    leave_for(pairs, 0, qtbot, rows_left=3)
    QTest.qWait(10)  # long enough for a removal that must not happen to have happened

    assert pair_model(pairs).rows == (("a", "1"), ("", "9"), ("b", "2"))
    assert len(changes) == 1


def test_a_cell_the_user_cannot_type_into_does_not_keep_a_blank_row(pairs: ItemListEditor, qtbot: QtBot) -> None:
    """The derived cell always shows text, but nothing was entered, so the row is still blank.

    **Test steps:**

    * verify the new row's derived cell shows text
    * leave the row and verify it was removed anyway
    """
    insert_and_tab_to_the_second_cell(pairs)
    assert pair_model(pairs).index(1, 2).data() == "0 characters"

    leave_for(pairs, 0, qtbot, rows_left=2)

    assert pair_model(pairs).count == 2


def test_escape_on_the_first_cell_removes_the_insert_at_once(pairs: ItemListEditor) -> None:
    """Cancelling is undoing the insert, not leaving it for later.

    **Test steps:**

    * insert and press Escape in the first cell's editor
    * verify the row is gone without the current row moving
    """
    pairs.set_current_index(0)
    pairs.item_actions.insert_action.trigger()

    press(Qt.Key.Key_Escape)

    assert pair_model(pairs).count == 2


def test_focus_leaving_the_list_abandons_a_waiting_insert(qtbot: QtBot) -> None:
    """Focus going to a widget outside the view is leaving the row, though the current row never moved.

    **Test steps:**

    * put the editor beside a line edit, insert and Tab to the second cell
    * focus the line edit
    * verify the blank row is gone
    """
    page = QWidget()
    qtbot.addWidget(page)
    model = PairModel()
    editor = ItemListEditor(ContentSizedTableView(), model)
    other = QLineEdit()
    layout = QVBoxLayout(page)
    layout.addWidget(editor)
    layout.addWidget(other)
    model.set_rows([("a", "1")])
    with qtbot.waitExposed(page):
        page.show()
    page.activateWindow()
    insert_and_tab_to_the_second_cell(editor)
    assert model.count == 2

    other.setFocus()
    qtbot.waitUntil(lambda: model.count == 1)

    assert model.rows == (("a", "1"),)


def test_tabbing_through_the_rows_own_cells_is_not_leaving_but_into_the_next_row_is(
    pairs: ItemListEditor, qtbot: QtBot
) -> None:
    """A cell the user cannot type into is still the row's own: reaching it is not leaving. The next
    row is.

    **Test steps:**

    * insert, Tab to the second cell, and Tab again -- onto the row's derived third cell
    * verify the row waits on, then Tab once more on the view, into the next row
    * verify the blank row is gone
    """
    insert_and_tab_to_the_second_cell(pairs)

    press(Qt.Key.Key_Tab)
    QTest.qWait(10)  # long enough for a removal that must not happen to have happened
    assert pair_model(pairs).count == 3
    assert pairs.current_index == 1

    QTest.keyClick(pairs.view, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: pair_model(pairs).count == 2)

    assert pair_model(pairs).rows == (("a", "1"), ("b", "2"))


def test_deleting_a_waiting_insert_removes_only_it_and_reports_nothing(pairs: ItemListEditor) -> None:
    """Delete on a blank insert is the insert abandoned: one row goes, silently.

    Guards a nested removal: the view moves the current row off the doomed row from inside the
    removal, which read as leaving the blank row -- abandoning it *inside* the outer removal, which then
    took the row that had shifted into its slot as well.

    **Test steps:**

    * insert, Tab to the second cell and commit it empty, then trigger Delete
    * verify exactly the blank row went and nothing was reported
    """
    changes: list[None] = []
    pairs.values_changed.connect(lambda: changes.append(None))
    insert_and_tab_to_the_second_cell(pairs)
    press(Qt.Key.Key_Return)

    pairs.item_actions.delete_action.trigger()
    QTest.qWait(10)  # long enough for a second removal that must not happen to have happened

    assert pair_model(pairs).rows == (("a", "1"), ("b", "2"))
    assert not changes


def test_another_row_edited_while_an_insert_waits_is_reported(pairs: ItemListEditor) -> None:
    """Only the blank insert itself is held back; an edit anywhere else is an edit.

    **Test steps:**

    * insert and Tab to the second cell, then retype the last row through the model
    * verify that edit was reported, and the blank row still waits
    """
    changes: list[None] = []
    pairs.values_changed.connect(lambda: changes.append(None))
    insert_and_tab_to_the_second_cell(pairs)
    model = pair_model(pairs)

    model.setData(model.index(2, 0), "c")

    assert changes == [None]
    assert model.rows == (("a", "1"), ("", ""), ("c", "2"))


# endregion
