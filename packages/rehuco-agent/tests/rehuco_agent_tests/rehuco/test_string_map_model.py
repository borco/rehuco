"""Tests for StringMapModel: a ``str -> str`` map as editable rows of a key and a value (#578, #637)."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.string_map_model import KEY_COLUMN, VALUE_COLUMN, StringMapModel


@fixture(name="model")
def fixture_model() -> StringMapModel:
    """A model holding two entries.

    :returns: the model.
    """
    built = StringMapModel(("Type", "Path template"))
    built.set_mapping({"*": "*", "tutorial": "{title}"})
    return built


def rows(model: StringMapModel) -> list[tuple[str, str]]:
    """Every row's key and value, as the view reads them.

    :param model: the model.
    :returns: one pair per row.
    """
    return [
        (model.index(row, KEY_COLUMN).data(), model.index(row, VALUE_COLUMN).data()) for row in range(model.rowCount())
    ]


def test_the_rows_are_the_maps_entries_in_order(model: StringMapModel) -> None:
    """A map shows as one row per entry, its key then its value, under the titles given.

    **Test steps:**

    * read the rows, the headers, the counts and the map
    * verify each
    """
    assert rows(model) == [("*", "*"), ("tutorial", "{title}")]
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in (0, 1)] == ["Type", "Path template"]
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert (model.count, model.columnCount(), model.rowCount(model.index(0, 0))) == (2, 2, 0)
    assert model.columnCount(model.index(0, 0)) == 0
    assert model.mapping == {"*": "*", "tutorial": "{title}"}


def test_a_row_with_no_key_or_a_repeated_key_is_flagged_and_left_out(model: StringMapModel) -> None:
    """Such a row is kept, coloured and explained, and the map is made of the others.

    **Test steps:**

    * add a row with no key and one repeating ``*``
    * verify their tooltips and colours, a sound row's lack of both, and the map
    """
    model.insert(-1)
    blank = model.insert(-1)
    model.setData(model.index(blank, KEY_COLUMN), " * ")
    model.setData(model.index(blank, VALUE_COLUMN), "{title}")

    assert model.index(2, KEY_COLUMN).data(Qt.ItemDataRole.ToolTipRole) == "No key: this row is ignored."
    assert "already a key above" in model.index(3, KEY_COLUMN).data(Qt.ItemDataRole.ToolTipRole)
    assert isinstance(model.index(3, KEY_COLUMN).data(Qt.ItemDataRole.ForegroundRole), QBrush)
    assert model.index(0, KEY_COLUMN).data(Qt.ItemDataRole.ToolTipRole) is None
    assert model.index(0, KEY_COLUMN).data(Qt.ItemDataRole.ForegroundRole) is None
    assert model.index(0, KEY_COLUMN).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.index(3, VALUE_COLUMN).data(Qt.ItemDataRole.ToolTipRole) is None
    assert model.mapping == {"*": "*", "tutorial": "{title}"}


def test_an_edit_that_changes_nothing_is_no_edit(qtbot: QtBot, model: StringMapModel) -> None:
    """Setting a cell to what it holds, or with a role other than editing, says nothing.

    **Test steps:**

    * set a value to itself, then with the display role, then on an invalid index
    * verify each returns ``False`` and no change was signalled
    """
    with qtbot.assertNotEmitted(model.dataChanged):
        assert not model.setData(model.index(0, VALUE_COLUMN), "*")
        assert not model.setData(model.index(0, VALUE_COLUMN), "x", Qt.ItemDataRole.DisplayRole)
        assert not model.setData(QModelIndex(), "x")
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable


def test_setting_the_same_map_again_keeps_the_rows(qtbot: QtBot, model: StringMapModel) -> None:
    """Showing the map the rows already are is not a reset, so a view keeps its place.

    **Test steps:**

    * set the same map, then a different one
    * verify only the second resets the model
    """
    with qtbot.assertNotEmitted(model.modelReset):
        model.set_mapping({"*": "*", "tutorial": "{title}"})
    with qtbot.waitSignal(model.modelReset):
        model.set_mapping({"*": "*"})
    assert rows(model) == [("*", "*")]


def test_rows_are_inserted_copied_moved_and_deleted(model: StringMapModel) -> None:
    """The list editor's operations each act on the row they are given.

    **Test steps:**

    * duplicate the first row, move it to the bottom and back to the top, down, up, and delete it
    * try each on a row that does not exist
    * verify the rows after each step
    """
    assert model.duplicate(0) == 1
    assert rows(model) == [("*", "*"), ("*", "*"), ("tutorial", "{title}")]
    assert model.move_to_bottom(1) == 2
    assert model.move_to_top(2) == 0
    assert model.move_down(0) == 1
    assert model.move_up(1) == 0
    model.delete(0)
    assert rows(model) == [("*", "*"), ("tutorial", "{title}")]

    assert model.duplicate(-1) == -1
    assert model.move_up(0) == 0
    model.delete(-1)
    assert not model.insertRows(5, 1)
    assert not model.removeRows(5, 1)
    assert not model.moveRows(model.index(0, 0), 0, 1, QModelIndex(), 1)
    assert rows(model) == [("*", "*"), ("tutorial", "{title}")]


def test_a_move_qt_refuses_moves_nothing(model: StringMapModel) -> None:
    """A move onto itself is refused by Qt, and the rows stay.

    **Test steps:**

    * ask to move the first row to before itself
    * verify it is refused and the rows unchanged
    """
    assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 1)
    assert rows(model) == [("*", "*"), ("tutorial", "{title}")]


def test_reset_puts_the_defaults_back(model: StringMapModel) -> None:
    """Reset shows the map the model was told is its default.

    **Test steps:**

    * set the defaults, read them, and reset
    * verify the rows are the defaults
    """
    model.defaults = {"*": "{title}"}
    model.reset()

    assert model.defaults == {"*": "{title}"}
    assert rows(model) == [("*", "{title}")]


def test_renaming_the_columns_says_so(qtbot: QtBot, model: StringMapModel) -> None:
    """The headers are named after the map they show.

    **Test steps:**

    * rename the columns and verify the change is signalled and read back
    """
    with qtbot.waitSignal(model.headerDataChanged):
        model.set_titles(("Placeholder", "When empty"))

    assert model.headerData(1, Qt.Orientation.Horizontal) == "When empty"


def test_a_value_the_checker_faults_is_coloured_with_its_reason_and_kept(model: StringMapModel) -> None:
    """With a value checker set, a faulted value shows a warning colour and the reason as a tooltip, on the value cell
    only, and the row still counts (#637).

    **Test steps:**

    * set a checker that faults the value ``{title}`` with a reason, and read the roles of both value cells
    * verify the faulted one has the colour and the reason, the other neither, and the map unchanged
    * clear the checker and verify nothing is flagged
    """
    model.set_value_problem(lambda key, value: f"{key} cannot use {value}" if value == "{title}" else "")

    faulted, fine = model.index(1, VALUE_COLUMN), model.index(0, VALUE_COLUMN)
    assert isinstance(faulted.data(Qt.ItemDataRole.ForegroundRole), QBrush)
    assert faulted.data(Qt.ItemDataRole.ToolTipRole) == "tutorial cannot use {title}"
    assert fine.data(Qt.ItemDataRole.ForegroundRole) is None
    assert fine.data(Qt.ItemDataRole.ToolTipRole) is None
    assert model.mapping == {"*": "*", "tutorial": "{title}"}

    model.set_value_problem(None)
    assert faulted.data(Qt.ItemDataRole.ForegroundRole) is None


def test_a_changed_checker_is_announced_for_every_value(qtbot: QtBot, model: StringMapModel) -> None:
    """Rows already shown are repainted when the checker changes (#637).

    **Test steps:**

    * set a checker and verify the data changed over the value column
    """
    with qtbot.waitSignal(model.dataChanged):
        model.set_value_problem(lambda _key, _value: "")


def test_fixed_keys_make_one_read_only_row_per_key_and_keep_only_filled_values(model: StringMapModel) -> None:
    """Fixing the keys shows exactly those rows, in order, their values from the map; a key outside them is dropped,
    and a row with an empty value is not in the map (#637).

    **Test steps:**

    * fix three keys over a model holding other entries, and show a map of one of them and a stranger
    * verify three rows in order, the key column read-only and the value column editable
    * verify the map holds the one filled value; edit another and verify it joins; empty it and verify it leaves
    """
    model.set_fixed_keys(("title", "authors", "year"))
    model.set_mapping({"authors": "Unknown", "colour": "Red"})

    assert model.fixed_keys == ("title", "authors", "year")
    assert rows(model) == [("title", ""), ("authors", "Unknown"), ("year", "")]
    assert not model.flags(model.index(0, KEY_COLUMN)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, VALUE_COLUMN)) & Qt.ItemFlag.ItemIsEditable
    assert model.mapping == {"authors": "Unknown"}

    assert model.setData(model.index(2, VALUE_COLUMN), "2025")
    assert model.mapping == {"authors": "Unknown", "year": "2025"}
    assert model.setData(model.index(1, VALUE_COLUMN), "")
    assert model.mapping == {"year": "2025"}


def test_fixed_keys_refuse_to_add_remove_duplicate_or_reset_a_row(model: StringMapModel) -> None:
    """The rows are the keys: nothing inserts, removes, duplicates or resets one (#637).

    **Test steps:**

    * fix two keys, give the model defaults, and ask for each of the four
    * verify two rows, unchanged
    """
    model.set_fixed_keys(("title", "year"))
    model.set_mapping({"title": "Intro"})
    model.defaults = {"*": "*"}

    assert not model.insertRow(0)
    assert model.insert(0) == 1
    assert not model.removeRow(0)
    model.delete(0)
    assert model.duplicate(0) == 0
    model.reset()

    assert rows(model) == [("title", "Intro"), ("year", "")]
