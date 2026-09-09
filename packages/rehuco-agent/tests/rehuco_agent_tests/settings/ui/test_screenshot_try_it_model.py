"""Tests for ScreenshotTryItModel: sample filenames beside the slot the live patterns assign each one
(#287).
"""

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.screenshot_try_it_model import (
    FILENAME_COLUMN,
    NOT_A_SCREENSHOT,
    SLOT_COLUMN,
    ScreenshotTryItModel,
)
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern


@fixture(name="model")
def fixture_model() -> ScreenshotTryItModel:
    """A model holding one recognized and one unrecognized sample, reading the shipped patterns.

    :returns: the model.
    """
    model = ScreenshotTryItModel(patterns_provider=lambda: SCREENSHOT_NAME_PATTERNS)
    model.set_entries(("cover.jpg", "lesson1.jpg"))
    return model


@fixture(name="three")
def fixture_three() -> ScreenshotTryItModel:
    """A model holding three samples, for the ordering tests.

    :returns: the model.
    """
    model = ScreenshotTryItModel()
    model.set_entries(("a.jpg", "b.jpg", "c.jpg"))
    return model


# region Rows and cells


def test_the_samples_are_rows_of_two_cells(model: ScreenshotTryItModel) -> None:
    """Each sample is one row: its filename, then the slot the live patterns assign it.

    **Test steps:**

    * read both cells of the first row
    """
    assert model.rowCount() == 2
    assert model.data(model.index(0, FILENAME_COLUMN)) == "cover.jpg"
    assert model.data(model.index(0, SLOT_COLUMN)) == "00"


def test_an_unrecognized_sample_reads_as_not_a_screenshot(model: ScreenshotTryItModel) -> None:
    """A filename no pattern matches shows the plain-language answer, not a crash or a blank cell.

    **Test steps:**

    * read the slot cell of the unmatched sample
    """
    assert model.data(model.index(1, SLOT_COLUMN)) == NOT_A_SCREENSHOT


def test_an_empty_filename_reads_as_not_a_screenshot(model: ScreenshotTryItModel) -> None:
    """A blank sample row has no slot -- there is no "invalid" concept here, just no match.

    **Test steps:**

    * insert a blank row
    * read its slot cell
    """
    row = model.insert(-1)

    assert model.data(model.index(row, SLOT_COLUMN)) == NOT_A_SCREENSHOT


def test_the_slot_column_reads_the_stem_not_the_whole_filename(model: ScreenshotTryItModel) -> None:
    """The patterns match a stem, so the sample's extension is stripped before asking.

    **Test steps:**

    * set a sample to a filename whose stem a pattern matches under a different extension
    * read its slot
    """
    model.setData(model.index(0, FILENAME_COLUMN), "sample-03.png")

    assert model.data(model.index(0, SLOT_COLUMN)) == "03"


def test_editing_the_filename_cell_replaces_the_sample(model: ScreenshotTryItModel) -> None:
    """A row is one plain string, replaced outright on edit.

    **Test steps:**

    * set the first row's filename
    * verify it changed and the entries reflect it
    """
    assert model.setData(model.index(0, FILENAME_COLUMN), "file.jpg") is True

    assert model.entries[0] == "file.jpg"


def test_the_slot_column_is_never_editable(model: ScreenshotTryItModel) -> None:
    """The slot is a pure function of the filename and the live patterns -- nothing to type into.

    **Test steps:**

    * verify the cell carries no edit flag and no edit value, and refuses an edit
    """
    index = model.index(0, SLOT_COLUMN)

    assert not model.flags(index) & Qt.ItemFlag.ItemIsEditable
    assert model.data(index, Qt.ItemDataRole.EditRole) is None
    assert model.setData(index, "99") is False
    assert model.entries[0] == "cover.jpg"


def test_retyping_a_cell_with_what_it_holds_reports_no_edit(model: ScreenshotTryItModel) -> None:
    """An edit that changes nothing is not an edit, so nothing downstream is told there was one.

    **Test steps:**

    * set the filename cell to its current value
    * verify the model refused it
    """
    assert model.setData(model.index(0, FILENAME_COLUMN), "cover.jpg") is False


def test_setting_the_same_entries_again_does_not_reset_the_rows(model: ScreenshotTryItModel, qtbot: QtBot) -> None:
    """A caller handing back what it just read must not rebuild the rows under an open cell editor.

    **Test steps:**

    * set the entries the model already holds
    * verify no reset was emitted
    """
    with qtbot.assertNotEmitted(model.modelReset):
        model.set_entries(model.entries)


# endregion

# region Inserting, deleting and reset


def test_an_inserted_sample_lands_after_the_current_one_and_is_blank(model: ScreenshotTryItModel) -> None:
    """Insert puts a new sample below the one being pointed at, ready to type into.

    **Test steps:**

    * insert after the first row
    * verify where it landed and that it is blank
    """
    row = model.insert(0)

    assert row == 1
    assert model.entries[1] == ""
    assert model.rowCount() == 3


def test_deleting_drops_one_sample(model: ScreenshotTryItModel) -> None:
    """Delete removes the row it names and leaves the rest in order.

    **Test steps:**

    * delete the first sample
    * verify only the second remains
    """
    model.delete(0)

    assert model.entries == ("lesson1.jpg",)


def test_deleting_with_no_current_row_does_nothing(model: ScreenshotTryItModel) -> None:
    """Delete acts on the current row, and there may not be one.

    **Test steps:**

    * delete a negative row
    * verify nothing was dropped
    """
    model.delete(-1)

    assert model.entries == ("cover.jpg", "lesson1.jpg")


def test_reset_restores_the_defaults_once_they_are_set(model: ScreenshotTryItModel) -> None:
    """A widget promoted into a ``.ui`` is built with no defaults; the page sets them, and Reset is
    what they are for.

    **Test steps:**

    * verify a fresh model has nothing to restore
    * set the defaults, then reset
    * verify the defaults are what the rows became
    """
    assert model.defaults == ()

    model.defaults = ("a.jpg", "b.jpg")
    model.reset()

    assert model.defaults == ("a.jpg", "b.jpg")
    assert model.entries == ("a.jpg", "b.jpg")


# endregion

# region Ordering


def test_moving_a_sample_up_swaps_it_with_the_one_above(three: ScreenshotTryItModel) -> None:
    """The model implements the `ItemOrderingEditor` contract even though the editor hides the ordering
    column -- an ``ItemListEditor`` binds its ordering actions to the model whether or not they show.

    **Test steps:**

    * move the second of three samples up
    * verify the new order and the row it reports
    """
    assert three.move_up(1) == 0
    assert three.entries == ("b.jpg", "a.jpg", "c.jpg")


def test_moving_a_sample_to_the_top_and_the_bottom(three: ScreenshotTryItModel) -> None:
    """The two ends, which is what a long list is actually reordered with.

    **Test steps:**

    * move the last sample to the top, then the first to the bottom
    """
    assert three.move_to_top(2) == 0
    assert three.entries == ("c.jpg", "a.jpg", "b.jpg")

    assert three.move_to_bottom(0) == 2
    assert three.entries == ("a.jpg", "b.jpg", "c.jpg")


def test_a_move_off_either_end_is_a_no_op(three: ScreenshotTryItModel) -> None:
    """Nothing wraps around, and a refused move reports the row it started at.

    **Test steps:**

    * move the first sample up and the last one down
    * verify neither moved
    """
    assert three.move_up(0) == 0
    assert three.move_down(2) == 2
    assert three.entries == ("a.jpg", "b.jpg", "c.jpg")


def test_a_move_is_one_model_move_rather_than_a_removal_and_an_insertion(
    three: ScreenshotTryItModel, qtbot: QtBot
) -> None:
    """One ``rowsMoved`` keeps every other row's index and lets the selection follow the sample.

    **Test steps:**

    * move a sample down
    * verify the model reported a move and neither a removal nor an insertion
    """
    with qtbot.waitSignal(three.rowsMoved):
        with qtbot.assertNotEmitted(three.rowsRemoved), qtbot.assertNotEmitted(three.rowsInserted):
            three.move_down(0)

    assert three.entries == ("b.jpg", "a.jpg", "c.jpg")


# endregion

# region refresh_slots


def test_refresh_slots_picks_up_a_changed_provider(qtbot: QtBot) -> None:
    """The slot column is computed fresh on every read, but a view needs telling to repaint -- that is
    what :meth:`~ScreenshotTryItModel.refresh_slots` is for, as one full reset.

    **Test steps:**

    * build a model whose provider starts out empty
    * verify no slot matches
    * point the provider at real patterns and refresh
    * verify a reset was emitted and the slot column now matches
    """
    patterns: tuple[ScreenshotNamePattern, ...] = ()
    model = ScreenshotTryItModel(patterns_provider=lambda: patterns)
    model.set_entries(("cover.jpg",))
    assert model.data(model.index(0, SLOT_COLUMN)) == NOT_A_SCREENSHOT

    patterns = SCREENSHOT_NAME_PATTERNS
    with qtbot.waitSignal(model.modelReset):
        model.refresh_slots()

    assert model.data(model.index(0, SLOT_COLUMN)) == "00"


# endregion

# region Qt plumbing


def test_the_columns_are_named(model: ScreenshotTryItModel) -> None:
    """The header is what tells a reader which column is which.

    **Test steps:**

    * read both column titles
    """
    assert model.headerData(FILENAME_COLUMN, Qt.Orientation.Horizontal) == "Sample filename"
    assert model.headerData(SLOT_COLUMN, Qt.Orientation.Horizontal) == "Slot"


def test_only_the_filename_column_is_editable(model: ScreenshotTryItModel) -> None:
    """The filename is what is typed into; the slot column's refusal is tested with the column.

    **Test steps:**

    * read the flags of the filename cell
    """
    assert model.flags(model.index(0, FILENAME_COLUMN)) & Qt.ItemFlag.ItemIsEditable


def test_an_invalid_index_reads_as_nothing(model: ScreenshotTryItModel) -> None:
    """A view asking about a row that is not there gets no data rather than an error.

    **Test steps:**

    * read data and flags for an invalid index
    """
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_a_child_index_holds_no_rows(model: ScreenshotTryItModel) -> None:
    """The model is flat, which a view is entitled to ask about.

    **Test steps:**

    * ask for the row and column count under a valid index
    """
    child = model.index(0, 0)

    assert model.rowCount(child) == 0
    assert model.columnCount(child) == 0


# Mirrors test_string_item_list_model.py's row-refusal trio exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's model-test convention.
# pylint: disable=duplicate-code
def test_a_row_operation_under_a_parent_is_refused(model: ScreenshotTryItModel) -> None:
    """There is nothing under a row, so nothing can be inserted, removed or moved there.

    **Test steps:**

    * insert, remove and move under a valid index
    * verify all were refused and the list is untouched
    """
    parent = model.index(0, FILENAME_COLUMN)

    assert model.insertRow(0, parent) is False
    assert model.removeRow(0, parent) is False
    assert model.moveRow(parent, 0, QModelIndex(), 1) is False
    assert model.moveRow(QModelIndex(), 0, parent, 1) is False
    assert model.rowCount() == 2


def test_a_row_operation_outside_the_list_is_refused(model: ScreenshotTryItModel) -> None:
    """A row past the end, or none at all, names nothing to act on.

    **Test steps:**

    * insert past the end, insert nothing, remove past the end and remove nothing
    """
    assert model.insertRow(3) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRow(2) is False
    assert model.removeRows(0, 0) is False


def test_a_move_that_would_leave_the_list_as_it_was_is_refused(model: ScreenshotTryItModel) -> None:
    """A no-op move is not an edit, and reporting one would be a lie.

    **Test steps:**

    * move a row to where it already is
    """
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 0) is False


# pylint: enable=duplicate-code


# endregion
