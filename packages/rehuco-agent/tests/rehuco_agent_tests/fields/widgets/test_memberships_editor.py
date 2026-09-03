"""Tests for the two memberships tables as widgets: the shared chrome, and the learning paths' view switch."""

from typing import Any

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSpinBox
from pytest import fixture, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.field import HeaderPinned
from rehuco_agent.fields.widgets.collections_table_model import CollectionsTableModel
from rehuco_agent.fields.widgets.index_spin_box_delegate import (
    UNPLACED_TEXT,
    IndexSpinBoxDelegate,
    index_spin_box,
)
from rehuco_agent.fields.widgets.learning_paths_table_model import SUBSCRIBED_COLUMN
from rehuco_agent.fields.widgets.membership_table_model import INDEX_COLUMN, MAXIMUM_INDEX, TITLE_COLUMN
from rehuco_agent.fields.widgets.memberships_editor import (
    CollectionsEditor,
    LearningPathsEditor,
    MembershipsEditor,
)

RECORDS: dict[str, list[dict[str, Any]]] = {
    "admin": [{"title": "My Order", "index": 7, "ref": 1}],
    "foo": [{"title": "Private Study", "index": 1, "ref": 2}],
}


@fixture
def collections(qtbot: QtBot) -> CollectionsEditor:
    """A collections table over one membership.

    :param qtbot: the widget-owning fixture.
    :returns: the editor, shown.
    """
    widget = CollectionsEditor()
    qtbot.addWidget(widget)
    widget.set_value([{"title": "Series", "index": 2, "url": "https://example.com"}])
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


@fixture
def learning_paths(qtbot: QtBot) -> LearningPathsEditor:
    """A learning-paths table over :data:`RECORDS`, as ``admin``.

    :param qtbot: the widget-owning fixture.
    :returns: the editor, shown.
    """
    widget = LearningPathsEditor("admin", lambda: 3, "unknown")
    qtbot.addWidget(widget)
    widget.set_value(RECORDS)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def inner_view(editor: ItemListEditor) -> ContentSizedTableView:
    """The editor's own table.

    :param editor: the editor to reach into.
    :returns: the table it edits through.
    """
    view = editor.view
    assert isinstance(view, ContentSizedTableView)
    return view


# region shared chrome


def test_a_row_is_one_membership(collections: CollectionsEditor) -> None:
    """A click anywhere on a row acts on that membership; multi-select would promise a bulk edit none of
    the actions here can carry out.

    **Test steps:**

    * verify the selection behavior and mode
    """
    view = inner_view(collections)

    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection


def test_the_table_wears_no_row_numbers_grid_or_wrapping(collections: CollectionsEditor) -> None:
    """The row numbers say nothing (the position is a column), banded rows already separate entries, and
    a wrapped cell grows its row -- which a view sized to its rows then measures too early and clips.

    **Test steps:**

    * verify the vertical header, the grid and word-wrap are all off
    """
    view = inner_view(collections)

    assert view.verticalHeader().isVisible() is False
    assert view.showGrid() is False
    assert view.wordWrap() is False


def test_there_is_no_reset_and_no_ordering(collections: CollectionsEditor) -> None:
    """A default set of memberships would be somebody else's, and ``index`` is the position -- so four
    move buttons would offer an edit that changes no stored value.

    **Test steps:**

    * verify the reset button and the whole ordering column are hidden
    """
    assert collections.item_actions.reset_action.isVisible() is False
    assert collections.ordering_actions.isVisible() is False


def test_the_position_cell_opens_in_a_spin_box(collections: CollectionsEditor) -> None:
    """The position is stepped far more often than it is typed, so the arrow keys and the wheel are what
    the cell answers to.

    **Test steps:**

    * verify the index column carries the spin delegate
    * open the cell and verify the editor is a bounded spin box showing a dash at unplaced
    """
    view = inner_view(collections)
    assert isinstance(view.itemDelegateForColumn(INDEX_COLUMN), IndexSpinBoxDelegate)

    index = collections.model.index(0, INDEX_COLUMN)
    view.setCurrentIndex(index)
    view.edit(index)
    spin = view.findChild(QSpinBox)

    assert spin is not None
    assert (spin.minimum(), spin.maximum()) == (0, MAXIMUM_INDEX)
    assert spin.specialValueText() == UNPLACED_TEXT


def test_the_title_takes_the_row(collections: CollectionsEditor) -> None:
    """A series name is unbounded where a position is two or three digits, so stretching both would leave
    half the row empty -- and with nothing to scroll sideways to, the bar is off rather than merely unused.

    **Test steps:**

    * verify the title stretches, the position sizes to its contents, and there is no horizontal bar
    """
    header = inner_view(collections).horizontalHeader()

    assert header.sectionResizeMode(TITLE_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert inner_view(collections).horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_an_edit_is_reported_once_with_the_value(collections: CollectionsEditor) -> None:
    """One report per edit, carrying the value -- the `ValueWidget` contract ([[plugins#field-toolkit]]).

    **Test steps:**

    * retype a title through the model
    * verify exactly one report arrived, carrying the merged record
    """
    reported: list[Any] = []
    collections.value_changed.connect(reported.append)

    collections.model.setData(collections.model.index(0, TITLE_COLUMN), "Renamed")

    assert reported == [[{"title": "Renamed", "index": 2, "url": "https://example.com"}]]


def test_seeding_reports_nothing(collections: CollectionsEditor) -> None:
    """The echo guard: a value the owner pushed in is not a user edit to report back to the owner.

    **Test steps:**

    * seed a new value
    * verify the table shows it and reported nothing
    """
    reported: list[Any] = []
    collections.value_changed.connect(reported.append)

    collections.set_value([{"title": "Reverted"}])

    assert collections.value == [{"title": "Reverted"}]
    assert not reported


def test_the_base_editor_has_no_value_of_its_own(qtbot: QtBot) -> None:
    """The shared machinery is the chrome and the echo guard; what the value *is* belongs to whichever
    model the table was built over.

    **Test steps:**

    * build the base over a collections model and read its value
    * verify it refuses to answer
    """
    editor = MembershipsEditor(ContentSizedTableView(), CollectionsTableModel())
    qtbot.addWidget(editor)

    with raises(NotImplementedError):
        _ = editor.value


def test_the_row_label_is_pinned_to_the_column_header(collections: CollectionsEditor) -> None:
    """The label names the columns, so it sits level with them (`HeaderPinned`) rather than drifting down
    the middle of a table whose height is however many memberships there happen to be.

    **Test steps:**

    * verify the editor reports the table's own header height
    """
    assert isinstance(collections, HeaderPinned)
    assert collections.header_height == inner_view(collections).horizontalHeader().sizeHint().height()


def test_the_position_column_has_room_for_its_open_editor(collections: CollectionsEditor) -> None:
    """A column sized to what a position *draws* -- two digits, or nothing at all -- leaves an opened spin
    box showing its up/down buttons and none of the number between them. The column is fixed at the
    editor's own width instead.

    **Test steps:**

    * verify the column is fixed, and at least as wide as the editor that opens in it
    * open the position cell and verify the editor got the width it asks for
    """
    view = inner_view(collections)
    header = view.horizontalHeader()
    assert header.sectionResizeMode(INDEX_COLUMN) == QHeaderView.ResizeMode.Fixed
    assert header.sectionSize(INDEX_COLUMN) > index_spin_box(view).sizeHint().width()

    index = collections.model.index(0, INDEX_COLUMN)
    view.setCurrentIndex(index)
    view.edit(index)

    spin = view.findChild(QSpinBox)
    assert spin is not None
    assert spin.width() >= spin.sizeHint().width()


# endregion

# region the learning paths' view switch


def test_the_editor_opens_in_the_identitys_own_view(learning_paths: LearningPathsEditor) -> None:
    """The identity's own view is what an editor opens in: what am I in, before what is in this file.

    **Test steps:**

    * verify the view is not the all-scopes one, and the other identity's row is hidden
    """
    assert learning_paths.all_scopes is False
    assert inner_view(learning_paths).model().rowCount() == 1


def test_switching_to_every_scope_reveals_the_other_identity(learning_paths: LearningPathsEditor) -> None:
    """The private paths of other identities are exactly what the editor exists to reveal.

    **Test steps:**

    * switch to every scope
    * verify both rows are on screen, and the switch was reported once
    """
    reported: list[bool] = []
    learning_paths.all_scopes_changed.connect(reported.append)

    learning_paths.set_all_scopes(True)

    assert inner_view(learning_paths).model().rowCount() == 2
    assert reported == [True]


def test_switching_to_the_same_view_reports_nothing(learning_paths: LearningPathsEditor) -> None:
    """A switch that switches nothing is not one.

    **Test steps:**

    * ask for the view already in force
    * verify nothing was reported
    """
    reported: list[bool] = []
    learning_paths.all_scopes_changed.connect(reported.append)

    learning_paths.set_all_scopes(False)

    assert not reported


def test_the_view_is_remembered_across_a_session(learning_paths: LearningPathsEditor) -> None:
    """Which paths a user was last looking at in *this* file is theirs to keep, the same way the
    ``authors`` editor's mode is (:class:`~rehuco_agent.fields.field.StatefulWidget`).

    **Test steps:**

    * switch to every scope and save the state
    * restore it onto a fresh editor and verify the view came back
    """
    learning_paths.set_all_scopes(True)

    state = learning_paths.save_state()
    restored = LearningPathsEditor("admin", lambda: 3, "unknown")
    restored.restore_state(state)

    assert restored.all_scopes is True


def test_an_unreadable_saved_state_reads_as_the_identitys_own_view(learning_paths: LearningPathsEditor) -> None:
    """Anything but the one recognized byte is the default view, never a crash.

    **Test steps:**

    * restore an empty blob
    * verify the identity's own view is what is shown
    """
    learning_paths.set_all_scopes(True)

    learning_paths.restore_state(b"")

    assert learning_paths.all_scopes is False


def test_the_learning_paths_table_carries_four_sized_columns(learning_paths: LearningPathsEditor) -> None:
    """The title takes the row; the position, the owner and the checkbox take what they need.

    **Test steps:**

    * verify each column's resize mode
    """
    header = inner_view(learning_paths).horizontalHeader()

    assert header.sectionResizeMode(TITLE_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(SUBSCRIBED_COLUMN) == QHeaderView.ResizeMode.ResizeToContents


def test_an_edit_reports_the_scoped_records(learning_paths: LearningPathsEditor) -> None:
    """The value is every scope's records, so an edit reports the whole mapping.

    **Test steps:**

    * retype this identity's own path
    * verify the reported value carries both scopes, the slot intact
    """
    reported: list[Any] = []
    learning_paths.value_changed.connect(reported.append)

    learning_paths.model.setData(learning_paths.model.index(0, TITLE_COLUMN), "Renamed")

    assert reported == [
        {
            "admin": [{"title": "Renamed", "index": 7, "ref": 1}],
            "foo": [{"title": "Private Study", "index": 1, "ref": 2}],
        }
    ]


# endregion
