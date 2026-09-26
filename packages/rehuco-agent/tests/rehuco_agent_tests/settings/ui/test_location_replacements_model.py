"""Tests for LocationReplacementsModel: the rule table as editable rows of *text*, *replacement* and a
*regexp* checkbox (#350).
"""

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from rehuco_agent.settings.location_replacements_settings import (
    DEFAULT_RULES,
    EMPTY_TEXT_PROBLEM,
    INVALID_REGEX_PROBLEM,
    ReplacementRule,
)
from rehuco_agent.settings.ui.location_replacements_model import (
    REGEX_COLUMN,
    REPLACEMENT_COLUMN,
    TEXT_COLUMN,
    LocationReplacementsModel,
)

FIRST = ReplacementRule(":", "-")
SECOND = ReplacementRule("|", " - ")


@fixture(name="model")
def fixture_model() -> LocationReplacementsModel:
    """A model holding two rules.

    :returns: the model.
    """
    model = LocationReplacementsModel()
    model.set_entries((FIRST, SECOND))
    return model


# region Rows and cells


def test_a_rule_is_a_row_of_three_cells(model: LocationReplacementsModel) -> None:
    """Each rule is one row: its text, its replacement, and the regexp checkbox.

    **Test steps:**

    * read all three cells of the first row
    """
    assert model.rowCount() == 2
    assert model.columnCount() == 3
    assert model.data(model.index(0, TEXT_COLUMN)) == ":"
    assert model.data(model.index(0, REPLACEMENT_COLUMN)) == "-"
    assert model.data(model.index(0, REGEX_COLUMN), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_editing_the_text_cell_replaces_it_keeping_the_replacement(model: LocationReplacementsModel) -> None:
    """An edit to one cell leaves the other alone.

    **Test steps:**

    * set the first row's text cell
    * verify the text changed and the replacement did not
    """
    assert model.setData(model.index(0, TEXT_COLUMN), "::") is True

    assert model.entries[0] == ReplacementRule("::", "-")


def test_editing_the_replacement_cell_replaces_it_keeping_the_text(model: LocationReplacementsModel) -> None:
    """The other half of the same discipline: retyping *Replace with* keeps *Text*.

    **Test steps:**

    * set the first row's replacement cell
    * verify the replacement changed and the text did not
    """
    assert model.setData(model.index(0, REPLACEMENT_COLUMN), "--") is True

    assert model.entries[0] == ReplacementRule(":", "--")


def test_retyping_a_cell_with_what_it_holds_reports_no_edit(model: LocationReplacementsModel) -> None:
    """An edit that changes nothing is not an edit.

    **Test steps:**

    * set a cell to its current value
    * verify the model refused it
    """
    assert model.setData(model.index(0, TEXT_COLUMN), ":") is False


# endregion

# region Inserting, deleting and reset


def test_an_inserted_rule_lands_after_the_current_one_and_is_blank(model: LocationReplacementsModel) -> None:
    """Insert puts a new rule below the one being pointed at, ready to type into.

    **Test steps:**

    * insert after the first row
    * verify where it landed and that both its cells are empty
    """
    row = model.insert(0)

    assert row == 1
    assert model.entries[1] == ReplacementRule("", "")
    assert model.rowCount() == 3


def test_a_duplicated_rule_lands_below_its_source(model: LocationReplacementsModel) -> None:
    """Duplicate copies both cells in one insert.

    **Test steps:**

    * duplicate the first row
    * verify the copy sits below it, equal to it
    """
    row = model.duplicate(0)

    assert row == 1
    assert model.entries == (FIRST, FIRST, SECOND)


def test_duplicate_with_a_negative_row_does_nothing(model: LocationReplacementsModel) -> None:
    """No row named is a no-op, not an error.

    **Test steps:**

    * duplicate with a negative row
    * verify nothing changed and the row came back as given
    """
    assert model.duplicate(-1) == -1
    assert model.entries == (FIRST, SECOND)


def test_deleting_drops_one_rule(model: LocationReplacementsModel) -> None:
    """Delete removes the row it names and leaves the rest in order.

    **Test steps:**

    * delete the first rule
    * verify only the second remains
    """
    model.delete(0)

    assert model.entries == (SECOND,)


def test_deleting_a_negative_row_does_nothing(model: LocationReplacementsModel) -> None:
    """No row named is a no-op, not an error.

    **Test steps:**

    * delete with a negative row
    * verify nothing changed
    """
    model.delete(-1)

    assert model.entries == (FIRST, SECOND)


def test_reset_restores_the_defaults(model: LocationReplacementsModel) -> None:
    """Reset is what the shipped rules are for -- unlike the ``authors`` list, there genuinely is a
    default here.

    **Test steps:**

    * reset
    * verify the shipped rules are back
    """
    model.reset()

    assert model.entries == DEFAULT_RULES


def test_the_defaults_can_be_read_back(model: LocationReplacementsModel) -> None:
    """What Reset restores is itself readable, not just settable -- the settings page reads it back to
    decide whether Reset has anything to offer.

    **Test steps:**

    * set the defaults to a custom set
    * verify reading them back answers the same set
    """
    model.defaults = (FIRST,)

    assert model.defaults == (FIRST,)


# endregion

# region Ordering


def test_moving_a_rule_up_swaps_it_with_the_one_above(model: LocationReplacementsModel) -> None:
    """Rules apply in table order, so moving one is a real edit.

    **Test steps:**

    * move the second rule up
    * verify the new order and the row it reports
    """
    assert model.move_up(1) == 0
    assert model.entries == (SECOND, FIRST)


def test_a_move_off_either_end_is_a_no_op(model: LocationReplacementsModel) -> None:
    """Nothing wraps around, and a refused move reports the row it started at.

    **Test steps:**

    * move the first rule up and the last one down
    * verify neither moved
    """
    assert model.move_up(0) == 0
    assert model.move_down(1) == 1
    assert model.entries == (FIRST, SECOND)


def test_move_to_top_and_to_bottom_take_a_rule_straight_to_either_end(model: LocationReplacementsModel) -> None:
    """The jump moves skip the one-at-a-time walk `move_up`/`move_down` do.

    **Test steps:**

    * move the second rule to the top, then move it to the bottom
    * verify the row each returns and the resulting order
    """
    assert model.move_to_top(1) == 0
    assert model.entries == (SECOND, FIRST)

    assert model.move_to_bottom(0) == 1
    assert model.entries == (FIRST, SECOND)


# endregion

# region Qt plumbing


def test_the_columns_are_named(model: LocationReplacementsModel) -> None:
    """The headers tell a reader which field is which.

    **Test steps:**

    * read all three column titles
    """
    assert model.headerData(TEXT_COLUMN, Qt.Orientation.Horizontal) == "Text"
    assert model.headerData(REPLACEMENT_COLUMN, Qt.Orientation.Horizontal) == "Replace with"
    assert model.headerData(REGEX_COLUMN, Qt.Orientation.Horizontal) == "Regexp"


def test_the_text_and_replacement_cells_are_editable(model: LocationReplacementsModel) -> None:
    """Both text fields are typed into in place.

    **Test steps:**

    * read the flags of both text cells
    """
    assert model.flags(model.index(0, TEXT_COLUMN)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, REPLACEMENT_COLUMN)) & Qt.ItemFlag.ItemIsEditable


def test_the_regex_cell_is_checkable_not_editable(model: LocationReplacementsModel) -> None:
    """The regexp column is a checkbox, toggled rather than typed into.

    **Test steps:**

    * read the regexp cell's flags
    """
    flags = model.flags(model.index(0, REGEX_COLUMN))
    assert flags & Qt.ItemFlag.ItemIsUserCheckable
    assert not flags & Qt.ItemFlag.ItemIsEditable


def test_checking_the_regex_box_sets_is_regex(model: LocationReplacementsModel) -> None:
    """Checking the box flips the rule to regex mode.

    **Test steps:**

    * set the checkbox cell's check state to checked
    * verify the rule's ``is_regex`` flipped and the cell reads back checked
    """
    index = model.index(0, REGEX_COLUMN)

    assert model.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole) is True

    assert model.entries[0] == ReplacementRule(":", "-", is_regex=True)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_the_regex_cell_round_trips_through_the_edit_role(model: LocationReplacementsModel) -> None:
    """The settings dialog's frame snapshot reads and restores every cell under ``EditRole`` -- so the
    checkbox answers there too, or a toggle would never light the frame's Apply and its Reset/Defaults
    would drop it.

    **Test steps:**

    * read the regexp cell under the edit role, then write the opposite value back through it
    * verify the rule flipped
    """
    index = model.index(0, REGEX_COLUMN)
    assert model.data(index, Qt.ItemDataRole.EditRole) is False

    assert model.setData(index, True, Qt.ItemDataRole.EditRole) is True

    assert model.entries[0] == ReplacementRule(":", "-", is_regex=True)


def test_the_regex_cell_shows_no_text(model: LocationReplacementsModel) -> None:
    """A checkbox column draws the box, not the word ``True``/``False`` beside it.

    **Test steps:**

    * read the regexp cell under the display role, and write it under that role
    """
    index = model.index(0, REGEX_COLUMN)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) is None
    assert model.setData(index, True, Qt.ItemDataRole.DisplayRole) is False


def test_an_invalid_index_reads_as_nothing(model: LocationReplacementsModel) -> None:
    """A view asking about a row that is not there gets no data rather than an error.

    **Test steps:**

    * read data and flags for an invalid index
    """
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags


def test_an_empty_text_cell_explains_and_colours_itself(model: LocationReplacementsModel) -> None:
    """Flagged, never refused: the text cell says what is wrong and paints itself.

    **Test steps:**

    * empty a rule's text cell
    * read that cell's tooltip and foreground
    """
    model.setData(model.index(0, TEXT_COLUMN), "")
    index = model.index(0, TEXT_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == EMPTY_TEXT_PROBLEM
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None


def test_an_unparsable_regex_text_cell_explains_and_colours_itself(model: LocationReplacementsModel) -> None:
    """Checking Regexp over text that does not parse flags the text cell, not the checkbox cell.

    **Test steps:**

    * set a rule's text to something that never parses as a regex, then check its Regexp box
    * read the text cell's tooltip and foreground
    """
    model.setData(model.index(0, TEXT_COLUMN), "(")
    model.setData(model.index(0, REGEX_COLUMN), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    index = model.index(0, TEXT_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == INVALID_REGEX_PROBLEM
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None


def test_an_empty_replacement_cell_is_never_flagged(model: LocationReplacementsModel) -> None:
    """Deleting the matched text outright is a legitimate rule, so only the text column can be invalid.

    **Test steps:**

    * empty a rule's replacement cell
    * read that cell's tooltip and foreground
    """
    model.setData(model.index(0, REPLACEMENT_COLUMN), "")
    index = model.index(0, REPLACEMENT_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None


def test_a_usable_cell_carries_no_tooltip_and_no_colour(model: LocationReplacementsModel) -> None:
    """A row with text wears nothing.

    **Test steps:**

    * read both roles on a well-formed rule's text cell
    """
    index = model.index(0, TEXT_COLUMN)

    assert model.data(index, Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None


def test_an_edit_outside_the_model_or_under_another_role_is_refused(model: LocationReplacementsModel) -> None:
    """Only an in-place edit of a real cell writes anything.

    **Test steps:**

    * set data on an invalid index, and on a valid one under a display role
    """
    assert model.setData(QModelIndex(), ":") is False
    assert model.setData(model.index(0, TEXT_COLUMN), ":", Qt.ItemDataRole.DisplayRole) is False


def test_a_row_operation_under_a_parent_or_outside_the_list_is_refused(model: LocationReplacementsModel) -> None:
    """There is nothing under a row, and a range past the end names nothing to act on.

    **Test steps:**

    * insert, remove and move under a valid index, and insert/remove nothing
    * verify all were refused and the list is untouched
    """
    parent = model.index(0, TEXT_COLUMN)

    assert model.insertRows(0, 1, parent) is False
    assert model.removeRows(0, 1, parent) is False
    assert model.moveRows(parent, 0, 1, QModelIndex(), 1) is False
    assert model.moveRows(QModelIndex(), 0, 1, parent, 1) is False
    assert model.insertRows(0, 0) is False
    assert model.removeRows(0, 0) is False
    assert model.entries == (FIRST, SECOND)


def test_a_move_into_its_own_source_range_is_refused(model: LocationReplacementsModel) -> None:
    """Qt refuses a move whose destination falls inside the range being moved -- there is nowhere for
    it to land that isn't where it already is.

    **Test steps:**

    * move the first row to a destination inside its own one-row range
    * verify the model refused it
    """
    assert model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 0) is False
    assert model.entries == (FIRST, SECOND)


# endregion
