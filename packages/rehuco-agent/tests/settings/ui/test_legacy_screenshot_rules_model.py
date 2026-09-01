"""Tests for LegacyScreenshotRulesModel: the rules as editable rows of cover and rest (#53)."""

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.legacy_screenshot_rules_model import (
    COVER_COLUMN,
    MISSING_COVER_REASON,
    REST_COLUMN,
    LegacyScreenshotRulesModel,
)
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule

FIRST: LegacyScreenshotRule = LegacyScreenshotRule("cover", "file-##")
SECOND: LegacyScreenshotRule = LegacyScreenshotRule("shot-1", "shot-#")
THIRD: LegacyScreenshotRule = LegacyScreenshotRule("00", "##")


@fixture(name="model")
def fixture_model() -> LegacyScreenshotRulesModel:
    """A model holding three rules.

    :returns: the model.
    """
    model = LegacyScreenshotRulesModel()
    model.set_entries((FIRST, SECOND, THIRD))
    return model


# region Rows and cells


def test_the_rules_are_rows_of_two_cells(model: LegacyScreenshotRulesModel) -> None:
    """Each rule is one row: its cover, then its rest template.

    **Test steps:**

    * read both cells of the first row
    """
    assert model.rowCount() == 3
    assert model.data(model.index(0, COVER_COLUMN)) == "cover"
    assert model.data(model.index(0, REST_COLUMN)) == "file-##"


def test_editing_a_cell_replaces_only_that_field(model: LegacyScreenshotRulesModel) -> None:
    """A rule is frozen, so an edit builds a new one carrying the other field unchanged.

    **Test steps:**

    * set the rest cell of the first row
    * verify the cover survived and the rule changed
    """
    assert model.setData(model.index(0, REST_COLUMN), "cover-##") is True

    assert model.entries[0] == LegacyScreenshotRule("cover", "cover-##")


def test_retyping_a_cell_with_what_it_holds_reports_no_edit(model: LegacyScreenshotRulesModel) -> None:
    """An edit that changes nothing is not an edit, so nothing downstream is told there was one.

    **Test steps:**

    * set a cell to its current value
    * verify the model refused it
    """
    assert model.setData(model.index(0, COVER_COLUMN), "cover") is False


def test_setting_the_same_entries_again_does_not_reset_the_rows(
    model: LegacyScreenshotRulesModel, qtbot: QtBot
) -> None:
    """A caller handing back what it just read must not rebuild the rows under an open cell editor.

    **Test steps:**

    * set the entries the model already holds
    * verify no reset was emitted
    """
    with qtbot.assertNotEmitted(model.modelReset):
        model.set_entries((FIRST, SECOND, THIRD))


# endregion

# region Inserting, deleting and the blank rule


def test_an_inserted_rule_lands_after_the_current_one_and_is_blank(model: LegacyScreenshotRulesModel) -> None:
    """Insert puts a new rule below the one being pointed at, ready to type into.

    **Test steps:**

    * insert after the first row
    * verify where it landed and that both cells are empty
    """
    row = model.insert(0)

    assert row == 1
    assert model.entries[1] == LegacyScreenshotRule("", "")
    assert model.rowCount() == 4


def test_a_rule_is_blank_only_while_both_cells_are_empty(model: LegacyScreenshotRulesModel) -> None:
    """Both columns, unlike the base's first-column rule: a rest typed without a cover is a rule
    somebody is writing, and abandoning the insert would throw it away.

    **Test steps:**

    * insert a blank rule and check it reads as blank
    * type into its rest cell only
    * verify it no longer reads as blank
    """
    row = model.insert(0)
    assert model.row_is_blank(row) is True

    model.setData(model.index(row, REST_COLUMN), "shot-#")

    assert model.row_is_blank(row) is False


def test_deleting_with_no_current_row_does_nothing(model: LegacyScreenshotRulesModel) -> None:
    """Delete acts on the current row, and there may not be one.

    **Test steps:**

    * delete a negative row
    * verify nothing was dropped
    """
    model.delete(-1)

    assert model.entries == (FIRST, SECOND, THIRD)


def test_a_row_outside_the_list_is_never_blank(model: LegacyScreenshotRulesModel) -> None:
    """The base asks about the row an insert just made, which a failed insert never produced.

    **Test steps:**

    * ask about a row past the end and a negative one
    """
    assert model.row_is_blank(len(model.entries)) is False
    assert model.row_is_blank(-1) is False


def test_deleting_drops_one_rule(model: LegacyScreenshotRulesModel) -> None:
    """Delete removes the row it names and leaves the rest in order.

    **Test steps:**

    * delete the middle rule
    * verify the other two remain, in order
    """
    model.delete(1)

    assert model.entries == (FIRST, THIRD)


def test_reset_restores_the_defaults(model: LegacyScreenshotRulesModel) -> None:
    """Reset is what the shipped set is for.

    **Test steps:**

    * reset
    * verify the shipped rules are back
    """
    model.reset()

    assert model.entries == LEGACY_SCREENSHOT_RULES


# endregion

# region Ordering


def test_moving_a_rule_up_swaps_it_with_the_one_above(model: LegacyScreenshotRulesModel) -> None:
    """Order decides which rule claims a folder, so moving one is a real edit.

    **Test steps:**

    * move the second rule up
    * verify the new order and the row it reports
    """
    assert model.move_up(1) == 0
    assert model.entries == (SECOND, FIRST, THIRD)


def test_moving_a_rule_to_the_top_and_the_bottom(model: LegacyScreenshotRulesModel) -> None:
    """The two ends, which is what a long list is actually reordered with.

    **Test steps:**

    * move the last rule to the top, then the first to the bottom
    """
    assert model.move_to_top(2) == 0
    assert model.entries == (THIRD, FIRST, SECOND)

    assert model.move_to_bottom(0) == 2
    assert model.entries == (FIRST, SECOND, THIRD)


def test_a_move_off_either_end_is_a_no_op(model: LegacyScreenshotRulesModel) -> None:
    """Nothing wraps around, and a refused move reports the row it started at.

    **Test steps:**

    * move the first rule up and the last one down
    * verify neither moved
    """
    assert model.move_up(0) == 0
    assert model.move_down(2) == 2
    assert model.entries == (FIRST, SECOND, THIRD)


def test_a_move_is_one_model_move_rather_than_a_removal_and_an_insertion(
    model: LegacyScreenshotRulesModel, qtbot: QtBot
) -> None:
    """One ``rowsMoved`` keeps every other row's index and lets the selection follow the rule.

    **Test steps:**

    * move a rule down
    * verify the model reported a move and neither a removal nor an insertion
    """
    with qtbot.waitSignal(model.rowsMoved):
        with qtbot.assertNotEmitted(model.rowsRemoved), qtbot.assertNotEmitted(model.rowsInserted):
            model.move_down(0)

    assert model.entries == (SECOND, FIRST, THIRD)


# endregion

# region Qt plumbing


def test_the_columns_are_named(model: LegacyScreenshotRulesModel) -> None:
    """The header is what tells a reader which field is which.

    **Test steps:**

    * read both column titles
    """
    assert model.headerData(COVER_COLUMN, Qt.Orientation.Horizontal) == "Cover"
    assert model.headerData(REST_COLUMN, Qt.Orientation.Horizontal) == "Rest"


def test_every_cell_is_editable(model: LegacyScreenshotRulesModel) -> None:
    """Both fields are typed into in place.

    **Test steps:**

    * read the flags of both cells
    """
    for column in (COVER_COLUMN, REST_COLUMN):
        assert model.flags(model.index(0, column)) & Qt.ItemFlag.ItemIsEditable


def test_a_child_index_holds_no_rows(model: LegacyScreenshotRulesModel) -> None:
    """The model is flat, which a view is entitled to ask about.

    **Test steps:**

    * ask for the row and column count under a valid index
    """
    child = model.index(0, 0)

    assert model.rowCount(child) == 0
    assert model.columnCount(child) == 0


def test_an_invalid_index_reads_as_nothing(model: LegacyScreenshotRulesModel) -> None:
    """A view asking about a row that is not there gets no data rather than an error.

    **Test steps:**

    * read data and flags for an invalid index
    """
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_an_unusable_cell_explains_and_colours_itself(model: LegacyScreenshotRulesModel) -> None:
    """Flagged, never refused: the cell says what is wrong and paints itself, and nothing is dropped.

    **Test steps:**

    * empty a rule's cover
    * read the cell's tooltip and foreground
    """
    model.setData(model.index(0, COVER_COLUMN), "")
    index = model.index(0, COVER_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == MISSING_COVER_REASON
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None


def test_a_usable_cell_carries_no_tooltip_and_no_colour(model: LegacyScreenshotRulesModel) -> None:
    """The flag is about what a scan would refuse, so a rule it accepts wears nothing.

    **Test steps:**

    * read both roles on a compilable rule, and a role the model does not answer
    """
    index = model.index(0, COVER_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None
    assert model.data(index, Qt.ItemDataRole.DecorationRole) is None


def test_an_edit_outside_the_model_or_under_another_role_is_refused(model: LegacyScreenshotRulesModel) -> None:
    """Only an in-place edit of a real cell writes anything.

    **Test steps:**

    * set data on an invalid index, and on a valid one under a display role
    """
    assert model.setData(QModelIndex(), "cover") is False
    assert model.setData(model.index(0, COVER_COLUMN), "cover", Qt.ItemDataRole.DisplayRole) is False


def test_a_row_operation_under_a_parent_is_refused(model: LegacyScreenshotRulesModel) -> None:
    """There is nothing under a row, so nothing can be inserted, removed or moved there.

    **Test steps:**

    * insert, remove and move under a valid index
    * verify all were refused and the list is untouched
    """
    parent = model.index(0, COVER_COLUMN)

    assert model.insertRow(0, parent) is False
    assert model.removeRow(0, parent) is False
    assert model.moveRow(parent, 0, QModelIndex(), 1) is False
    assert model.moveRow(QModelIndex(), 0, parent, 1) is False
    assert model.rowCount() == 3


def test_a_row_operation_outside_the_list_is_refused(model: LegacyScreenshotRulesModel) -> None:
    """A row past the end, or none at all, names nothing to act on.

    **Test steps:**

    * insert past the end, insert nothing, remove past the end and remove nothing
    """
    assert model.insertRow(4) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRow(3) is False
    assert model.removeRows(0, 0) is False


def test_a_move_that_would_leave_the_list_as_it_was_is_refused(model: LegacyScreenshotRulesModel) -> None:
    """A no-op move is not an edit, and reporting one would be a lie.

    **Test steps:**

    * move a row to where it already is
    """
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 0) is False


# endregion
