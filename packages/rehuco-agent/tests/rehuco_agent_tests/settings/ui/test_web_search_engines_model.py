"""Tests for WebSearchEnginesModel: the name/URL rows of the web search engine list (#388)."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush
from pytest import fixture
from rehuco_agent.settings.ui.web_search_engines_model import (
    ACTIVE_COLUMN,
    NAME_COLUMN,
    URL_COLUMN,
    WebSearchEnginesModel,
)
from rehuco_agent.settings.web_search_settings import (
    DEFAULT_ENGINES,
    EMPTY_NAME_PROBLEM,
    NO_PLACEHOLDER_PROBLEM,
    SearchEngine,
)

ONE = SearchEngine("One", "https://one.example/?q={query}", active=True)
TWO = SearchEngine("Two", "https://two.example/?q={query}")
THREE = SearchEngine("Three", "https://three.example/?q={query}")


@fixture(name="model")
def fixture_model() -> WebSearchEnginesModel:
    """A model holding three engines, in the order One, Two, Three."""
    model = WebSearchEnginesModel()
    model.set_entries((ONE, TWO, THREE))
    return model


def cell(model: WebSearchEnginesModel, row: int, column: int) -> QModelIndex:
    """The index of one cell.

    :param model: the model.
    :param row: the row.
    :param column: the column.
    :returns: the index.
    """
    return model.index(row, column)


def test_the_cells_show_the_name_and_the_url(model: WebSearchEnginesModel) -> None:
    """Two columns, each showing its half of the engine.

    **Test steps:**

    * read the headers and the first row
    * verify them
    """
    assert model.columnCount() == 3
    assert model.headerData(URL_COLUMN, Qt.Orientation.Horizontal) == "URL"
    assert model.data(cell(model, 0, NAME_COLUMN)) == "One"
    assert model.data(cell(model, 0, URL_COLUMN)) == ONE.url


def actives(model: WebSearchEnginesModel) -> list[bool]:
    """Which rows are active, in order.

    :param model: the model.
    :returns: one flag per row.
    """
    return [entry.active for entry in model.entries]


def test_exactly_one_radio_is_on_and_a_click_moves_it(model: WebSearchEnginesModel) -> None:
    """A list with none active activates its first usable row, and checking another row switches.

    **Test steps:**

    * verify the fixture's first row is the only active one
    * check the third row via the check-state role and verify it alone is on, through EditRole too
    * try to clear it and verify it stays on
    """
    assert actives(model) == [True, False, False]
    check = Qt.ItemDataRole.CheckStateRole
    assert model.setData(cell(model, 2, ACTIVE_COLUMN), Qt.CheckState.Checked, check)
    assert actives(model) == [False, False, True]
    assert model.data(cell(model, 2, ACTIVE_COLUMN), check) == Qt.CheckState.Checked
    assert model.data(cell(model, 0, ACTIVE_COLUMN), Qt.ItemDataRole.EditRole) is False
    assert not model.setData(cell(model, 2, ACTIVE_COLUMN), Qt.CheckState.Unchecked, check)
    assert not model.setData(cell(model, 2, ACTIVE_COLUMN), True, Qt.ItemDataRole.EditRole)
    assert not model.setData(cell(model, 2, ACTIVE_COLUMN), True, Qt.ItemDataRole.DisplayRole)
    assert actives(model) == [False, False, True]
    model.set_entries((ONE, TWO._replace(active=True)))
    assert actives(model) == [True, False]
    model.set_entries((SearchEngine("", ""), TWO))
    assert actives(model) == [False, True]


def test_the_active_flag_follows_its_row_and_deleting_it_activates_another(model: WebSearchEnginesModel) -> None:
    """The flag is on the row: moving keeps it, a copy starts off, and deleting the active row hands over.

    **Test steps:**

    * move the active row down and verify the flag went with it
    * duplicate it and verify the copy is off
    * delete the active row and verify the first usable row is active
    """
    model.move_down(0)
    assert actives(model) == [False, True, False]
    model.duplicate(1)
    assert actives(model) == [False, True, False, False]
    model.delete(1)
    assert actives(model) == [True, False, False]


def test_editing_a_cell_changes_that_half_only(model: WebSearchEnginesModel) -> None:
    """An edit replaces one field, and an unchanged value reports no edit.

    **Test steps:**

    * set a new name and a new URL and verify the entry
    * set the same value again and verify it is refused as a non-change
    """
    assert model.setData(cell(model, 0, NAME_COLUMN), "Uno")
    assert model.setData(cell(model, 0, URL_COLUMN), "https://uno.example/?q={query}")
    assert model.entries[0] == SearchEngine("Uno", "https://uno.example/?q={query}", active=True)
    assert not model.setData(cell(model, 0, NAME_COLUMN), "Uno")
    assert not model.setData(cell(model, 0, NAME_COLUMN), "x", Qt.ItemDataRole.DisplayRole)


def test_a_broken_row_flags_the_cell_that_is_wrong(model: WebSearchEnginesModel) -> None:
    """A nameless row flags its name, a URL without ``{query}`` flags its URL, and a fine row flags nothing.

    **Test steps:**

    * blank the first name and empty the second URL's placeholder
    * verify each row's tooltip and colour sit on the right cell only
    """
    model.setData(cell(model, 0, NAME_COLUMN), "")
    model.setData(cell(model, 1, URL_COLUMN), "https://two.example/")
    tooltip = Qt.ItemDataRole.ToolTipRole
    assert model.data(cell(model, 0, NAME_COLUMN), tooltip) == EMPTY_NAME_PROBLEM
    assert model.data(cell(model, 0, URL_COLUMN), tooltip) is None
    assert model.data(cell(model, 1, URL_COLUMN), tooltip) == NO_PLACEHOLDER_PROBLEM
    assert model.data(cell(model, 1, NAME_COLUMN), tooltip) is None
    assert isinstance(model.data(cell(model, 1, URL_COLUMN), Qt.ItemDataRole.ForegroundRole), QBrush)
    assert model.data(cell(model, 2, URL_COLUMN), Qt.ItemDataRole.ForegroundRole) is None


def test_insert_duplicate_delete_and_reset(model: WebSearchEnginesModel) -> None:
    """The editing contract: a blank row after the current one, a copy below, a drop, and Reset.

    **Test steps:**

    * insert after the first row and verify a blank row is there, and a negative row appends
    * duplicate the last row and verify the copy follows it; delete it again
    * reset and verify the shipped engines
    """
    assert model.insert(0) == 1
    assert model.entries[1] == SearchEngine("", "")
    assert model.insert(-1) == 4
    assert model.duplicate(3) == 4
    assert model.entries[4] == THREE
    assert model.duplicate(-1) == -1
    model.delete(4)
    model.delete(-1)
    assert model.count == 5
    model.reset()
    assert model.entries == DEFAULT_ENGINES


def test_moving_rows(model: WebSearchEnginesModel) -> None:
    """The four ordering moves land where they say, and a move off the end is a no-op.

    **Test steps:**

    * move to the bottom, up, down and to the top
    * verify the order after each and the returned rows
    """
    assert model.move_to_bottom(0) == 2
    assert model.entries == (TWO, THREE, ONE)
    assert model.move_up(2) == 1
    assert model.entries == (TWO, ONE, THREE)
    assert model.move_down(0) == 1
    assert model.entries == (ONE, TWO, THREE)
    assert model.move_to_top(2) == 0
    assert model.entries == (THREE, ONE, TWO)
    assert model.move_up(0) == 0


def test_the_flags_say_which_cells_are_typed_into_and_which_are_checked(model: WebSearchEnginesModel) -> None:
    """The radio cell is checkable and not editable, the text cells the other way round, and no index
    has no flags.

    **Test steps:**

    * read the flags of an invalid index, a radio cell and a name cell
    * verify each
    """
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    radio = model.flags(cell(model, 0, ACTIVE_COLUMN))
    assert radio & Qt.ItemFlag.ItemIsUserCheckable
    assert not radio & Qt.ItemFlag.ItemIsEditable
    text = model.flags(cell(model, 0, NAME_COLUMN))
    assert text & Qt.ItemFlag.ItemIsEditable
    assert not text & Qt.ItemFlag.ItemIsUserCheckable


def test_a_role_or_an_index_the_model_has_no_answer_for_gets_none(model: WebSearchEnginesModel) -> None:
    """No index, and a role a flagged cell has no style for, both answer nothing.

    **Test steps:**

    * ask for the data of an invalid index and set data on one
    * break a URL and ask for its decoration role
    * verify nothing was answered or changed
    """
    assert model.data(QModelIndex()) is None
    assert not model.setData(QModelIndex(), "x")
    model.setData(cell(model, 0, URL_COLUMN), "https://one.example/")
    assert model.data(cell(model, 0, URL_COLUMN), Qt.ItemDataRole.DecorationRole) is None


def test_requests_that_make_no_sense_are_refused(model: WebSearchEnginesModel) -> None:
    """A flat list has no children, and a row cannot be inserted, removed or moved out of range.

    **Test steps:**

    * insert, remove and move under a valid parent, with a zero count, and onto its own place
    * verify each is refused and the rows are unchanged
    """
    child_parent = model.index(0, 0)
    before = model.entries
    assert not model.insertRows(0, 1, child_parent)
    assert not model.insertRows(0, 0)
    assert not model.removeRows(0, 1, child_parent)
    assert not model.removeRows(0, 0)
    assert not model.removeRows(0, 4)
    assert not model.moveRows(child_parent, 0, 1, QModelIndex(), 2)
    assert not model.moveRows(QModelIndex(), 0, 1, child_parent, 2)
    assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 0)
    assert model.entries == before


def test_defaults_can_be_replaced_and_a_same_list_is_not_a_reset() -> None:
    """Reset restores whatever defaults were set, and setting an equal list emits nothing.

    **Test steps:**

    * set custom defaults and reset
    * set the same entries again and verify no model reset fires
    """
    model = WebSearchEnginesModel()
    model.defaults = (ONE,)
    assert model.defaults == (ONE,)
    model.reset()
    assert model.entries == (ONE,)
    resets: list[bool] = []
    model.modelReset.connect(lambda: resets.append(True))
    model.set_entries((ONE,))
    assert not resets
