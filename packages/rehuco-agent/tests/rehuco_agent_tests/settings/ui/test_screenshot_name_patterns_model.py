"""Tests for ScreenshotNamePatternsModel: the patterns as editable rows of one regex each (#53, #287)."""

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.screenshot_name_patterns_model import (
    INVALID_PATTERN_REASON,
    MISSING_PATTERN_REASON,
    PATTERN_COLUMN,
    ScreenshotNamePatternsModel,
)
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern

FIRST: ScreenshotNamePattern = ScreenshotNamePattern("^cover$")
SECOND: ScreenshotNamePattern = ScreenshotNamePattern(r"^shot-(\d+)$")
THIRD: ScreenshotNamePattern = ScreenshotNamePattern(r"^(\d+)$")


@fixture(name="model")
def fixture_model() -> ScreenshotNamePatternsModel:
    """A model holding three patterns.

    :returns: the model.
    """
    model = ScreenshotNamePatternsModel()
    model.set_entries((FIRST, SECOND, THIRD))
    return model


# region Rows and cells


def test_the_patterns_are_rows_of_one_cell(model: ScreenshotNamePatternsModel) -> None:
    """Each pattern is one row: its regex, in the pattern column.

    **Test steps:**

    * read the first row's cell
    """
    assert model.rowCount() == 3
    assert model.data(model.index(0, PATTERN_COLUMN)) == "^cover$"


def test_editing_a_cell_replaces_the_pattern(model: ScreenshotNamePatternsModel) -> None:
    """A pattern is frozen, so an edit builds a new one.

    **Test steps:**

    * set the first row's cell
    * verify the pattern changed
    """
    assert model.setData(model.index(0, PATTERN_COLUMN), "^file$") is True

    assert model.entries[0] == ScreenshotNamePattern("^file$")


def test_retyping_a_cell_with_what_it_holds_reports_no_edit(model: ScreenshotNamePatternsModel) -> None:
    """An edit that changes nothing is not an edit, so nothing downstream is told there was one.

    **Test steps:**

    * set a cell to its current value
    * verify the model refused it
    """
    assert model.setData(model.index(0, PATTERN_COLUMN), "^cover$") is False


def test_setting_the_same_entries_again_does_not_reset_the_rows(
    model: ScreenshotNamePatternsModel, qtbot: QtBot
) -> None:
    """A caller handing back what it just read must not rebuild the rows under an open cell editor.

    **Test steps:**

    * set the entries the model already holds
    * verify no reset was emitted
    """
    with qtbot.assertNotEmitted(model.modelReset):
        model.set_entries((FIRST, SECOND, THIRD))


# endregion

# region Inserting, deleting and reset


def test_an_inserted_pattern_lands_after_the_current_one_and_is_blank(model: ScreenshotNamePatternsModel) -> None:
    """Insert puts a new pattern below the one being pointed at, ready to type into.

    **Test steps:**

    * insert after the first row
    * verify where it landed and that its cell is empty
    """
    row = model.insert(0)

    assert row == 1
    assert model.entries[1] == ScreenshotNamePattern("")
    assert model.rowCount() == 4


def test_deleting_with_no_current_row_does_nothing(model: ScreenshotNamePatternsModel) -> None:
    """Delete acts on the current row, and there may not be one.

    **Test steps:**

    * delete a negative row
    * verify nothing was dropped
    """
    model.delete(-1)

    assert model.entries == (FIRST, SECOND, THIRD)


def test_deleting_drops_one_pattern(model: ScreenshotNamePatternsModel) -> None:
    """Delete removes the row it names and leaves the rest in order.

    **Test steps:**

    * delete the middle pattern
    * verify the other two remain, in order
    """
    model.delete(1)

    assert model.entries == (FIRST, THIRD)


def test_reset_restores_the_defaults(model: ScreenshotNamePatternsModel) -> None:
    """Reset is what the shipped set is for.

    **Test steps:**

    * reset
    * verify the shipped patterns are back
    """
    model.reset()

    assert model.entries == SCREENSHOT_NAME_PATTERNS


# endregion

# region Ordering


def test_moving_a_pattern_up_swaps_it_with_the_one_above(model: ScreenshotNamePatternsModel) -> None:
    """Order decides which pattern matches first, so moving one is a real edit.

    **Test steps:**

    * move the second pattern up
    * verify the new order and the row it reports
    """
    assert model.move_up(1) == 0
    assert model.entries == (SECOND, FIRST, THIRD)


def test_moving_a_pattern_to_the_top_and_the_bottom(model: ScreenshotNamePatternsModel) -> None:
    """The two ends, which is what a long list is actually reordered with.

    **Test steps:**

    * move the last pattern to the top, then the first to the bottom
    """
    assert model.move_to_top(2) == 0
    assert model.entries == (THIRD, FIRST, SECOND)

    assert model.move_to_bottom(0) == 2
    assert model.entries == (FIRST, SECOND, THIRD)


def test_a_move_off_either_end_is_a_no_op(model: ScreenshotNamePatternsModel) -> None:
    """Nothing wraps around, and a refused move reports the row it started at.

    **Test steps:**

    * move the first pattern up and the last one down
    * verify neither moved
    """
    assert model.move_up(0) == 0
    assert model.move_down(2) == 2
    assert model.entries == (FIRST, SECOND, THIRD)


def test_a_move_is_one_model_move_rather_than_a_removal_and_an_insertion(
    model: ScreenshotNamePatternsModel, qtbot: QtBot
) -> None:
    """One ``rowsMoved`` keeps every other row's index and lets the selection follow the pattern.

    **Test steps:**

    * move a pattern down
    * verify the model reported a move and neither a removal nor an insertion
    """
    with qtbot.waitSignal(model.rowsMoved):
        with qtbot.assertNotEmitted(model.rowsRemoved), qtbot.assertNotEmitted(model.rowsInserted):
            model.move_down(0)

    assert model.entries == (SECOND, FIRST, THIRD)


# endregion

# region Qt plumbing


def test_the_column_is_named(model: ScreenshotNamePatternsModel) -> None:
    """The header is what tells a reader which field this is.

    **Test steps:**

    * read the column title
    """
    assert model.headerData(PATTERN_COLUMN, Qt.Orientation.Horizontal) == "Pattern"


def test_the_cell_is_editable(model: ScreenshotNamePatternsModel) -> None:
    """The one field is typed into in place.

    **Test steps:**

    * read the flags of the cell
    """
    assert model.flags(model.index(0, PATTERN_COLUMN)) & Qt.ItemFlag.ItemIsEditable


def test_a_child_index_holds_no_rows(model: ScreenshotNamePatternsModel) -> None:
    """The model is flat, which a view is entitled to ask about.

    **Test steps:**

    * ask for the row and column count under a valid index
    """
    child = model.index(0, 0)

    assert model.rowCount(child) == 0
    assert model.columnCount(child) == 0


def test_an_invalid_index_reads_as_nothing(model: ScreenshotNamePatternsModel) -> None:
    """A view asking about a row that is not there gets no data rather than an error.

    **Test steps:**

    * read data and flags for an invalid index
    """
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_a_blank_cell_explains_and_colours_itself(model: ScreenshotNamePatternsModel) -> None:
    """Flagged, never refused: the cell says what is wrong and paints itself, and nothing is dropped.

    **Test steps:**

    * empty a pattern's cell
    * read the cell's tooltip and foreground
    """
    model.setData(model.index(0, PATTERN_COLUMN), "")
    index = model.index(0, PATTERN_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == MISSING_PATTERN_REASON
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None


def test_an_uncompilable_cell_explains_and_colours_itself(model: ScreenshotNamePatternsModel) -> None:
    """A pattern that fails to compile is flagged the same way a blank one is, with its own reason.

    **Test steps:**

    * set a pattern's cell to broken regex syntax
    * read the cell's tooltip and foreground
    """
    model.setData(model.index(0, PATTERN_COLUMN), "[")
    index = model.index(0, PATTERN_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == INVALID_PATTERN_REASON
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None


def test_a_usable_cell_carries_no_tooltip_and_no_colour(model: ScreenshotNamePatternsModel) -> None:
    """The flag is about what a scan would refuse, so a pattern it accepts wears nothing.

    **Test steps:**

    * read both roles on a compilable pattern, and a role the model does not answer
    """
    index = model.index(0, PATTERN_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None
    assert model.data(index, Qt.ItemDataRole.DecorationRole) is None


def test_an_edit_outside_the_model_or_under_another_role_is_refused(model: ScreenshotNamePatternsModel) -> None:
    """Only an in-place edit of a real cell writes anything.

    **Test steps:**

    * set data on an invalid index, and on a valid one under a display role
    """
    assert model.setData(QModelIndex(), "^cover$") is False
    assert model.setData(model.index(0, PATTERN_COLUMN), "^cover$", Qt.ItemDataRole.DisplayRole) is False


# Mirrors test_string_item_list_model.py's row-refusal trio exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's model-test convention.
# pylint: disable=duplicate-code
def test_a_row_operation_under_a_parent_is_refused(model: ScreenshotNamePatternsModel) -> None:
    """There is nothing under a row, so nothing can be inserted, removed or moved there.

    **Test steps:**

    * insert, remove and move under a valid index
    * verify all were refused and the list is untouched
    """
    parent = model.index(0, PATTERN_COLUMN)

    assert model.insertRow(0, parent) is False
    assert model.removeRow(0, parent) is False
    assert model.moveRow(parent, 0, QModelIndex(), 1) is False
    assert model.moveRow(QModelIndex(), 0, parent, 1) is False
    assert model.rowCount() == 3


def test_a_row_operation_outside_the_list_is_refused(model: ScreenshotNamePatternsModel) -> None:
    """A row past the end, or none at all, names nothing to act on.

    **Test steps:**

    * insert past the end, insert nothing, remove past the end and remove nothing
    """
    assert model.insertRow(4) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRow(3) is False
    assert model.removeRows(0, 0) is False


def test_a_move_that_would_leave_the_list_as_it_was_is_refused(model: ScreenshotNamePatternsModel) -> None:
    """A no-op move is not an edit, and reporting one would be a lie.

    **Test steps:**

    * move a row to where it already is
    """
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 0) is False


# pylint: enable=duplicate-code


# endregion
