"""Tests for the License dock's list of licenses (#705, [[assets#licenses]]): its buttons and grips shown only while it
edits, the grip painted and dragged, and the id cell offering the known ids.

The document is a ``Mock(spec=...)``, and the grip's drag mechanics are the shared filter's, tested with the Roots view
(:mod:`~rehuco_agent_tests.rehuco.test_roots_grip`); what is here is what the license list adds.
"""

# the delegate's and the filter's own hooks are reached by their mangled or protected names
# pylint: disable=protected-access

from typing import Any, Final, cast
from unittest.mock import Mock

from borco_pyside.widgets import ReorderDrag
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QMouseEvent, QPainter, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemDelegate, QApplication, QLineEdit, QStyle, QStyleOptionViewItem, QTableView
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.licenses_list_editor import (
    CUSTOM_CHOICE,
    LicensesGripFilter,
    LicensesListEditor,
    LicensesRowDelegate,
)
from rehuco_agent.documents.licenses_table_model import LICENSE_COLUMN, LICENSE_MIME_TYPE, URL_COLUMN
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets.editable_choice_combo_box import EditableChoiceComboBox
from rehuco_agent.grip_reorder import GRIP_WIDTH
from rehuco_core import ASSET_LICENSES, AssetLicense

FIRST: Final = AssetLicense("fab-standard")
SECOND: Final = AssetLicense("fab-uefn-reference-only")
THIRD: Final = AssetLicense("cc-by-4.0")


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> LicensesListEditor:
    """A shown list of three licenses that edits.

    :param qtbot: pytest-qt fixture.
    :returns: the list.
    """
    editor = LicensesListEditor(Mock(spec=RehuDocumentModel))
    qtbot.addWidget(editor)
    editor.licenses.set_entries([FIRST, SECOND, THIRD])
    editor.set_editable(True)
    editor.resize(500, 200)
    editor.show()
    qtbot.waitExposed(editor)
    return editor


def drag_of(editor: LicensesListEditor) -> ReorderDrag:
    """The drag the list's delegate paints from.

    :param editor: the list.
    :returns: its drag.
    """
    return editor.view.itemDelegate()._LicensesRowDelegate__drag  # type: ignore[attr-defined]


def option_for(editor: LicensesListEditor, row: int, column: int) -> QStyleOptionViewItem:
    """The option a cell is painted with.

    :param editor: the list.
    :param row: the row.
    :param column: the column.
    :returns: the option.
    """
    view = editor.view
    option = QStyleOptionViewItem()
    option.initFrom(view.viewport())
    option.rect = view.visualRect(view.model().index(row, column))
    option.widget = view
    return option


def paint_every_cell(editor: LicensesListEditor) -> None:
    """Paint each cell of the list's three rows through its delegate, onto an image.

    :param editor: the list.
    """
    view = editor.view
    image = QImage(view.viewport().size(), QImage.Format.Format_RGB32)
    painter = QPainter(image)
    for row in range(3):
        for column in range(2):
            view.itemDelegate().paint(painter, option_for(editor, row, column), view.model().index(row, column))
    painter.end()


def painted_cells(drawn: Mock) -> set[tuple[int, int, QStyle.StateFlag]]:
    """Which cell each call of a spied ``paint`` drew, and in what state.

    :param drawn: the spy.
    :returns: each cell's row, column and state.
    """
    cells = set()
    for call in drawn.call_args_list:
        _delegate, _painter, option, index = call.args
        cells.add((index.row(), index.column(), QStyleOptionViewItem(option).state))
    return cells


def send_drop(editor: LicensesListEditor, kind: QEvent.Type, point: QPoint, mime: QMimeData) -> bool:
    """Send a drag event to the list.

    :param editor: the list.
    :param kind: ``DragEnter`` or ``Drop``.
    :param point: where the pointer is, in the viewport's coordinates.
    :param mime: what is dragged.
    :returns: whether the list accepted it.
    """
    event: Any
    if kind == QEvent.Type.Drop:
        event = QDropEvent(
            QPointF(point), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
    else:
        event = QDragEnterEvent(
            point, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
    event.ignore()
    QApplication.sendEvent(editor.view.viewport(), event)
    return bool(event.isAccepted())


# region reading and editing


def test_only_add_and_delete_show_and_only_while_editing(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * verify the move buttons, duplicate, edit and reset are hidden, and add and delete shown, while editing
    * stop editing and verify the button column is hidden
    """
    actions = editor.item_actions

    assert editor.ordering_actions.isHidden()
    assert [action.isVisible() for action in (actions.insert_action, actions.delete_action)] == [True, True]
    assert not any(
        action.isVisible() for action in (actions.duplicate_action, actions.edit_action, actions.reset_action)
    )
    assert actions.edit_action not in editor.view.actions()
    editor.set_editable(False)
    assert actions.isHidden()


def test_the_list_selects_one_whole_row_and_never_scrolls(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * verify the selection is single and by row, with no row numbers and no scroll bar either way
    """
    view = editor.view
    assert isinstance(view, QTableView)

    assert view.selectionBehavior() == view.SelectionBehavior.SelectRows
    assert view.selectionMode() == view.SelectionMode.SingleSelection
    assert view.verticalHeader().isHidden()
    assert view.horizontalScrollBarPolicy() == view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_the_id_cell_offers_the_known_ids_and_writes_what_is_typed(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * open the first row's id cell
    * verify the editor offers *Custom* and every preset, those the other rows hold not to be picked, and holds the
      row's id, beside the grip
    * type another id, commit, and verify the row holds it
    """
    view = editor.view
    cell = view.model().index(0, LICENSE_COLUMN)

    view.edit(cell)

    combo = view.indexWidget(cell)
    assert isinstance(combo, EditableChoiceComboBox)
    assert [combo.itemText(at) for at in range(combo.count())] == [CUSTOM_CHOICE, *ASSET_LICENSES]
    items = cast(QStandardItemModel, combo.model())
    enabled = {combo.itemText(at): items.item(at).isEnabled() for at in range(1, combo.count())}
    assert enabled == {FIRST.license: True, SECOND.license: False, THIRD.license: False, "fab-ue-only": True}
    assert combo.value == FIRST.license
    assert combo.geometry().left() == view.visualRect(cell).left() + GRIP_WIDTH
    delegate = view.itemDelegate()
    combo.set_value("my-license")
    delegate.commitData.emit(combo)
    assert editor.licenses.license_at(0) == "my-license"


def test_the_url_cell_is_a_line_on_the_whole_cell(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * open the first row's URL cell
    * verify it is a line holding the URL, on the cell's own rect
    """
    view = editor.view
    cell = view.model().index(0, URL_COLUMN)

    view.edit(cell)

    line = view.indexWidget(cell)
    assert isinstance(line, QLineEdit)
    assert line.geometry() == view.visualRect(cell)


def test_leaving_editing_with_no_cell_open_writes_nothing(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * stop editing with no cell open
    * verify the list reads and the document was given nothing
    """
    document = editor.licenses._LicensesTableModel__document  # type: ignore[attr-defined]

    editor.set_editable(False)

    assert not editor.licenses.editable
    assert [name for name, *_args in document.mock_calls] == ["dirty_changed.connect"]


# endregion

# region the grip


def test_the_grip_widens_the_id_column_and_is_painted_only_while_editing(
    editor: LicensesListEditor, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * measure and paint the first id cell while editing, then while reading
    * verify the cell is wider by the grip while editing, and the grip is painted in its band at the cell's left only
      then
    """
    view = editor.view
    delegate = view.itemDelegate()
    index = view.model().index(0, LICENSE_COLUMN)
    grip = mocker.patch("rehuco_agent.documents.licenses_list_editor.paint_grip")

    def measure_and_paint() -> int:
        option = option_for(editor, 0, LICENSE_COLUMN)
        option.rect = QRect(0, 0, 120, 24)
        image = QImage(120, 24, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        delegate.paint(painter, option, index)
        painter.end()
        return delegate.sizeHint(option_for(editor, 0, 0), index).width()

    editing = measure_and_paint()
    assert grip.call_count == 1
    assert grip.call_args.args[1] == QRect(0, 0, GRIP_WIDTH, 24)
    editor.set_editable(False)
    reading = measure_and_paint()

    assert editing == reading + GRIP_WIDTH
    assert grip.call_count == 1


def test_while_a_row_is_dragged_the_others_close_up_and_its_shadow_spans_the_row(
    editor: LicensesListEditor, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * select the third row, drag the first over the bottom of the last row, and paint every cell
    * verify the shadow was painted in the last row's cells, across the whole row, and the first two rows painted the
      second and third licenses, the second of them selected
    """
    view = editor.view
    editor.set_current_index(2)
    ghost = mocker.patch("rehuco_agent.documents.licenses_list_editor.paint_drag_ghost")
    drawn = mocker.spy(LicensesRowDelegate.__mro__[1], "paint")
    drag_of(editor).begin(0)
    drag_of(editor).place(2)
    model = view.model()

    paint_every_cell(editor)

    whole_row = view.visualRect(model.index(2, 0)).united(view.visualRect(model.index(2, 1)))
    assert ghost.call_count == 2
    rects: set[QRect] = {QRectF(call.args[1]).toRect() for call in ghost.call_args_list}
    assert rects == {whole_row}
    shown = painted_cells(drawn)
    selected = {(row, column) for row, column, state in shown if state & state.State_Selected}
    assert {(row, column) for row, column, _state in shown} == {(1, 0), (1, 1), (2, 0), (2, 1)}
    assert selected == {(2, 0), (2, 1)}


def test_a_drop_moves_the_dragged_license_to_the_shadow(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * drag the first license over the bottom of the last row and drop it there
    * verify the rows' new order
    """
    view = editor.view
    drag_of(editor).begin(0)
    mime = view.model().mimeData([view.model().index(0, 0)])
    bottom = view.visualRect(view.model().index(2, 1)).bottomLeft() - QPoint(0, 1)

    assert send_drop(editor, QEvent.Type.DragEnter, bottom, mime)
    assert send_drop(editor, QEvent.Type.Drop, bottom, mime)

    assert editor.licenses.entries == [SECOND, THIRD, FIRST]


def test_only_a_drag_of_the_dragged_row_is_taken(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * drag the first license, and drag over the list data naming another row, and another kind of data
    * verify each is refused and the shadow stays where the row was
    """
    drag_of(editor).begin(0)
    other_row = QMimeData()
    other_row.setData(LICENSE_MIME_TYPE, b"1")
    text = QMimeData()
    text.setText("0")
    point = editor.view.visualRect(editor.view.model().index(2, 1)).center()

    assert not send_drop(editor, QEvent.Type.DragEnter, point, other_row)
    assert not send_drop(editor, QEvent.Type.DragEnter, point, text)

    assert drag_of(editor).slot == 0


def test_the_grip_filter_moves_only_a_list_of_licenses(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * ask the filter to move a row of a model that is not a list of licenses
    * verify nothing happened, and a row of the list's own model moves
    """
    grip = LicensesGripFilter(editor.view, ReorderDrag())
    other = Mock()

    grip._move(other, 0, 2)
    grip._move(editor.licenses, 0, 2)

    assert not other.mock_calls
    assert editor.licenses.entries == [SECOND, THIRD, FIRST]


def test_a_reset_under_a_drag_abandons_it(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * drag the first license, and give the list other licenses meanwhile
    * verify the drag is over
    """
    drag_of(editor).begin(0)

    editor.licenses.set_entries([THIRD])

    assert not drag_of(editor).active


# endregion


def test_pressing_and_moving_a_grip_drags_the_whole_row(editor: LicensesListEditor, mocker: MockerFixture) -> None:
    """The picture a drag carries is the row, every cell of it, not the id alone.

    **Test steps:**

    * replace ``QDrag`` so the drag does not block, press the second row's grip and move past the drag distance
    * verify one move drag carrying the second row, whose picture is grabbed from the whole row
    """
    view = editor.view
    viewport = view.viewport()
    drag_class = mocker.patch("rehuco_agent.grip_reorder.QDrag")
    grab = mocker.spy(viewport, "grab")
    model = view.model()
    grip = QPoint(GRIP_WIDTH // 2, view.visualRect(model.index(1, 0)).center().y())
    far = QPointF(grip + QPoint(0, QApplication.startDragDistance() + 2))

    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.Type.MouseMove,
            far,
            viewport.mapToGlobal(far),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    started = drag_class.return_value
    started.exec.assert_called_once_with(Qt.DropAction.MoveAction)
    (mime,) = started.setMimeData.call_args.args
    assert bytes(mime.data(LICENSE_MIME_TYPE).data()) == b"1"
    assert grab.call_args.args[0] == view.visualRect(model.index(1, 0)).united(view.visualRect(model.index(1, 1)))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)


def test_the_columns_share_the_width_equally(editor: LicensesListEditor) -> None:
    """An id is not sized to its text, which left a row being added a sliver to type into.

    **Test steps:**

    * verify every column stretches, and an empty row's id cell is as wide as its URL cell
    """
    view = editor.view
    assert isinstance(view, QTableView)
    header = view.horizontalHeader()

    assert {header.sectionResizeMode(column) for column in range(2)} == {header.ResizeMode.Stretch}
    assert abs(header.sectionSize(0) - header.sectionSize(1)) <= 1


def test_an_id_picked_from_the_list_is_written_and_the_url_opens(editor: LicensesListEditor) -> None:
    """Picking is the answer: the user need not leave the cell for it to count.

    **Test steps:**

    * add a row, and pick a known id none of the rows holds from its id cell's list
    * verify the row holds it, the popup is as wide as its longest id, and the URL cell is open
    """
    view = editor.view
    editor.item_actions.insert_action.trigger()
    row = editor.current_index
    combo = view.indexWidget(view.currentIndex())
    assert isinstance(combo, EditableChoiceComboBox)
    popup = combo.view()
    free = ASSET_LICENSES.index("fab-ue-only") + 1

    combo.setCurrentIndex(free)
    combo.activated.emit(free)

    assert editor.licenses.license_at(row) == "fab-ue-only"
    assert popup.minimumWidth() >= popup.sizeHintForColumn(0)
    assert view.currentIndex().column() == 1
    assert isinstance(view.indexWidget(view.currentIndex()), QLineEdit)


def document_of(editor: LicensesListEditor) -> Mock:
    """The document a list follows.

    :param editor: the list.
    :returns: the mock.
    """
    return editor._LicensesListEditor__document  # type: ignore[attr-defined]


def test_picking_custom_leaves_its_name_selected_to_be_typed_over_or_kept(
    editor: LicensesListEditor, qtbot: QtBot
) -> None:
    """**Test steps:**

    * add two rows; in the first, pick *Custom*
    * verify the cell is still open holding *Custom*, all of it selected, and nothing is written yet
    * commit it as it is and verify the row is a license named *Custom*
    * in the second, pick *Custom* and type a name over it, and verify the row holds the name typed
    """
    view = editor.view
    editor.licenses.insert(-1)
    editor.licenses.insert(-1)

    def pick_custom(row: int) -> EditableChoiceComboBox:
        cell = view.model().index(row, LICENSE_COLUMN)
        view.setCurrentIndex(cell)
        view.edit(cell)
        combo = view.indexWidget(cell)
        assert isinstance(combo, EditableChoiceComboBox)
        combo.setCurrentIndex(0)
        combo.activated.emit(0)
        assert view.indexWidget(cell) is combo
        return combo

    combo = pick_custom(3)
    assert combo.value == CUSTOM_CHOICE
    assert cast(QLineEdit, combo.lineEdit()).selectedText() == CUSTOM_CHOICE
    assert editor.licenses.license_at(3) is None
    view.itemDelegate().commitData.emit(combo)
    view.itemDelegate().closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)
    assert editor.licenses.license_at(3) == CUSTOM_CHOICE

    combo = pick_custom(4)
    qtbot.keyClicks(combo.lineEdit(), "my-license")
    view.itemDelegate().commitData.emit(combo)

    assert editor.licenses.license_at(4) == "my-license"


def test_a_row_added_stays_while_the_focus_goes_elsewhere(editor: LicensesListEditor, qtbot: QtBot) -> None:
    """An empty row is kept until the editing stops, wherever the focus goes meanwhile.

    **Test steps:**

    * add a row, close its cell, and move the current row to another
    * verify the row is still there
    """
    view = editor.view
    editor.item_actions.insert_action.trigger()
    combo = view.indexWidget(view.currentIndex())
    assert combo is not None
    view.itemDelegate().closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)

    editor.set_current_index(0)
    qtbot.wait(10)  # long enough for a removal that must not happen to have happened

    assert editor.licenses.count == 4
    assert not editor.row_is_blank(3)


def test_rows_with_no_id_go_when_the_editing_stops(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * add a row and stop editing
    * verify only the three licenses are left
    """
    editor.item_actions.insert_action.trigger()

    editor.set_editable(False)

    assert editor.licenses.count == 3


def test_rows_with_no_id_go_when_the_record_is_saved(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * add a row, and have the document become dirty -- the row stays
    * have it become clean, as a save makes it, and verify only the licenses are left
    """
    editor.item_actions.insert_action.trigger()

    editor._LicensesListEditor__on_dirty_changed(True)  # type: ignore[attr-defined]
    assert editor.licenses.count == 4
    editor._LicensesListEditor__on_dirty_changed(False)  # type: ignore[attr-defined]

    assert editor.licenses.count == 3


def test_a_detached_list_stops_following_the_document(editor: LicensesListEditor) -> None:
    """**Test steps:**

    * detach the list
    * verify it let go of the document's dirty signal it took
    """
    document = document_of(editor)
    handler = document.dirty_changed.connect.call_args.args[0]

    editor.detach()

    document.dirty_changed.disconnect.assert_called_once_with(handler)
