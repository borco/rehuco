"""Tests for `CardListModel`: rows in, rows out, pending blanks, and the signals a card list updates from."""

from collections.abc import Mapping, Sequence
from typing import Any

from borco_pyside.widgets import CardListModel, ItemEditor, ItemOrderingEditor
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy
from pytest import fixture, mark, param
from pytestqt.qtbot import QtBot


def duplicate_names(items: Sequence[Any]) -> list[Mapping[str, str]]:
    """Flag every row repeating an earlier row's name.

    :param items: the rows' items.
    :returns: per row, ``{"flagged": "Duplicate"}`` or nothing.
    """
    seen: set[str] = set()
    states: list[Mapping[str, str]] = []
    for item in items:
        name = item.get("name", "")
        states.append({"flagged": "Duplicate"} if name and name in seen else {})
        seen.add(name)
    return states


def make_model(*names: str) -> CardListModel:
    """A model over ``{"name": ...}`` rows, flagging repeated names.

    :param names: the rows' names.
    :returns: the model.
    """
    model = CardListModel(dict, lambda item: not item, duplicate_names)
    model.set_items([{"name": name} for name in names])
    return model


@fixture
def model(qtbot: QtBot) -> CardListModel:  # pylint: disable=unused-argument
    """Three rows, ``a``, ``b``, ``c``.

    :param qtbot: ensures a QApplication exists.
    :returns: the model.
    """
    return make_model("a", "b", "c")


def names(model: CardListModel) -> list[str]:
    """Every row's name, pending rows included.

    :param model: the model.
    :returns: the names, in order.
    """
    return [item.get("name", "") for item in model.items]


def test_the_model_is_an_item_editor_and_ordering_editor(model: CardListModel) -> None:
    """The model plugs into the shared item-action machinery.

    **Test steps:**

    * verify it satisfies both protocols structurally
    """
    assert isinstance(model, ItemEditor)
    assert isinstance(model, ItemOrderingEditor)


@mark.parametrize(
    ("method", "at", "row", "order"),
    [
        param("move_to_top", 2, 0, ["c", "a", "b"], id="to-top"),
        param("move_up", 1, 0, ["b", "a", "c"], id="up"),
        param("move_down", 1, 2, ["a", "c", "b"], id="down"),
        param("move_to_bottom", 0, 2, ["b", "c", "a"], id="to-bottom"),
    ],
)
def test_each_move_returns_the_rows_new_place(
    model: CardListModel, method: str, at: int, row: int, order: list[str]
) -> None:
    """The four moves reorder and say where the row landed.

    **Test steps:**

    * move one row
    * verify the returned row and the new order
    """
    assert getattr(model, method)(at) == row
    assert names(model) == order


@mark.parametrize(("at", "to"), [param(0, 0, id="unchanged"), param(0, 3, id="out-of-range"), param(-1, 0, id="none")])
def test_a_move_that_goes_nowhere_is_a_no_op(model: CardListModel, at: int, to: int) -> None:
    """A move to its own row, or off the list, changes nothing.

    **Test steps:**

    * move a row nowhere
    * verify the original row comes back and the order stands
    """
    assert model.move(at, to) == at
    assert names(model) == ["a", "b", "c"]


def test_an_insert_is_pending_and_left_out_of_the_value(model: CardListModel) -> None:
    """A blank card is shown but is not part of the value until something is typed into it.

    **Test steps:**

    * insert after the first row
    * verify the new row is pending and the value is unchanged
    * give it a name and verify it is no longer pending and joins the value
    * blank it again and verify it stays in the value
    """
    row = model.insert(0)

    assert row == 1
    assert model.is_pending(1)
    assert model.value == [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    model.set_item(1, {"name": "x"})
    assert not model.is_pending(1)
    assert model.value[1] == {"name": "x"}

    model.set_item(1, {})
    assert not model.value[1]


def test_insert_with_a_negative_row_appends(model: CardListModel) -> None:
    """A negative row inserts at the end.

    **Test steps:**

    * insert at ``-1``
    * verify the new row is last
    """
    assert model.insert(-1) == 3
    assert model.count == 4


def test_delete_drops_one_row_and_duplicate_copies_one(model: CardListModel) -> None:
    """Delete removes a row; duplicate inserts a copy below it.

    **Test steps:**

    * delete the middle row, then duplicate the first
    * verify the order after each
    """
    model.delete(1)
    assert names(model) == ["a", "c"]

    assert model.duplicate(0) == 1
    assert names(model) == ["a", "a", "c"]


def test_an_equal_set_items_changes_nothing_and_keeps_pending_rows(model: CardListModel, qtbot: QtBot) -> None:
    """Setting the value the model already holds is the echo guard: no reset, pending rows kept.

    **Test steps:**

    * insert a pending row
    * set the unchanged value back, watching for a reset
    * verify no reset happened and the pending row is still there
    """
    model.insert(-1)

    with qtbot.assertNotEmitted(model.modelReset):
        model.set_items([{"name": "a"}, {"name": "b"}, {"name": "c"}])

    assert model.count == 4


def test_each_change_emits_its_fine_grained_signal(model: CardListModel, qtbot: QtBot) -> None:
    """Insert, delete, move and edit each announce only themselves; a new value resets.

    **Test steps:**

    * insert, delete, move, edit and set a new value, waiting on each signal
    """
    with qtbot.waitSignals([model.rowsInserted, model.count_changed]):
        model.insert(0)
    with qtbot.waitSignals([model.rowsRemoved, model.count_changed]):
        model.delete(1)
    with qtbot.waitSignal(model.rowsMoved), qtbot.assertNotEmitted(model.count_changed):
        model.move_down(0)
    with qtbot.waitSignal(model.dataChanged):
        model.set_item(0, {"name": "z"})
    with qtbot.waitSignal(model.modelReset):
        model.set_items([{"name": "q"}])


@mark.parametrize(
    ("change", "signal"),
    [
        param(lambda model: model.set_item(1, {"name": "a"}), "dataChanged", id="edit"),
        param(lambda model: model.duplicate(1), "rowsInserted", id="insert"),
        param(lambda model: model.delete(0), "rowsRemoved", id="delete"),
        param(lambda model: model.move_to_top(2), "rowsMoved", id="move"),
        param(lambda model: model.set_items([{"name": "b"}, {"name": "b"}]), "modelReset", id="reset"),
    ],
)
def test_states_are_current_when_the_row_signal_fires(  # pylint: disable=unused-argument
    qtbot: QtBot, change: Any, signal: str
) -> None:
    """A listener updating from a row signal already reads the new rows' states, and hears
    ``states_changed`` only after that row signal.

    **Test steps:**

    * start from ``a``, ``b``, ``a`` (the last one flagged) and make a change that moves the flags
    * record the states the row signal's listener sees, and the order of the two signals
    * verify the listener saw the final states, and ``states_changed`` came after the row signal
    """
    model = make_model("a", "b", "a")
    seen: list[list[Mapping[str, str]]] = []
    order: list[str] = []

    def on_row_signal(*_args: Any) -> None:
        order.append(signal)
        seen.append([model.states(row) for row in range(model.count)])

    getattr(model, signal).connect(on_row_signal)
    model.states_changed.connect(lambda: order.append("states_changed"))

    change(model)

    assert seen == [[model.states(row) for row in range(model.count)]]
    assert order == [signal, "states_changed"]


def test_states_follow_the_rows_and_announce_only_a_change(model: CardListModel, qtbot: QtBot) -> None:
    """The hook's states are recomputed on every change, and announced only when they differ.

    **Test steps:**

    * rename the last row to repeat the first and verify it is flagged, announced once
    * edit it to another repeat and verify nothing is announced
    * move the flagged row to the top and verify the flag moves to the other repeat
    """
    with qtbot.waitSignal(model.states_changed):
        model.set_item(2, {"name": "a"})
    assert model.states(2) == {"flagged": "Duplicate"}

    model.set_item(1, {"name": "a", "extra": True})
    assert model.states(1) == {"flagged": "Duplicate"}
    with qtbot.assertNotEmitted(model.states_changed):
        model.set_item(1, {"name": "a", "extra": False})

    model.move_to_top(2)
    assert [model.states(row) for row in range(3)] == [{}, {"flagged": "Duplicate"}, {"flagged": "Duplicate"}]


def test_setting_an_equal_item_changes_nothing(model: CardListModel, qtbot: QtBot) -> None:
    """Replacing a row's item with an equal one announces nothing.

    **Test steps:**

    * set the first row to the item it already holds
    * verify no data change was emitted
    """
    with qtbot.assertNotEmitted(model.dataChanged):
        model.set_item(0, {"name": "a"})


def test_a_negative_row_is_a_no_op_for_duplicate_and_delete(model: CardListModel) -> None:
    """Duplicating or deleting "no row" leaves the list alone, and duplicate says so.

    **Test steps:**

    * duplicate and delete row ``-1``
    * verify the returned row and that nothing changed
    """
    assert model.duplicate(-1) == -1
    model.delete(-1)
    assert names(model) == ["a", "b", "c"]


def test_reset_is_a_no_op_and_a_duplicated_blank_stays_pending(model: CardListModel) -> None:
    """A list with no defaults has nothing to reset, and a copy of a pending row is pending too.

    **Test steps:**

    * insert a blank row, duplicate it, and reset
    * verify both blanks are still pending and the rows are unchanged
    """
    model.insert(-1)
    model.duplicate(3)
    model.reset()

    assert model.count == 5
    assert model.is_pending(3)
    assert model.is_pending(4)


def test_the_model_answers_the_qt_interface(model: CardListModel) -> None:
    """The item is reachable through Qt's item-data role and nothing else; bad ranges are refused.

    **Test steps:**

    * read a row through the user role, another role, and an invalid index
    * remove and move rows with an invalid range and a valid parent, and verify each is refused
    """
    index = model.index(1)
    assert model.data(index, Qt.ItemDataRole.UserRole) == {"name": "b"}
    assert model.data(index, Qt.ItemDataRole.DisplayRole) is None
    assert model.data(QModelIndex(), Qt.ItemDataRole.UserRole) is None
    assert model.rowCount(index) == 0

    assert model.removeRows(2, 5) is False
    assert model.removeRows(0, 1, index) is False
    assert model.moveRows(index, 0, 1, QModelIndex(), 2) is False
    assert model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 0) is False
    assert names(model) == ["a", "b", "c"]


# region never_empty


def make_never_empty(*names: str) -> CardListModel:
    """A never-empty model over ``{"name": ...}`` rows.

    :param names: the rows' names; none for an empty value.
    :returns: the model.
    """
    model = CardListModel(dict, lambda item: not item, never_empty=True)
    model.set_items([{"name": name} for name in names])
    return model


def test_a_never_empty_model_starts_with_one_pending_blank_row(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """The one row is shown, but it is not part of the value.

    **Test steps:**

    * build a never-empty model
    * verify one pending row and an empty value
    """
    model = CardListModel(dict, lambda item: not item, never_empty=True)

    assert model.never_empty
    assert model.count == 1
    assert model.is_pending(0)
    assert model.value == []


def test_an_empty_value_shows_one_pending_blank_row(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """Setting nothing resets the rows to the single blank one, and setting nothing again is a no-op.

    **Test steps:**

    * set two rows, then an empty value, watching for a reset
    * verify one pending row and, for the same value again, no further reset
    """
    model = make_never_empty("a", "b")

    model.set_items([])

    assert model.count == 1
    assert model.is_pending(0)
    resets = QSignalSpy(model.modelReset)
    model.set_items([])
    assert resets.count() == 0


def test_deleting_the_only_row_clears_it_in_place(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """The row is not removed: its item is reset, it is pending again, and it is announced as a change.

    **Test steps:**

    * delete the only row of a one-row model, watching the row signals
    * verify one blank pending row, a data change for row 0 and no removal
    """
    model = make_never_empty("a")

    changes = QSignalSpy(model.dataChanged)
    removals = QSignalSpy(model.rowsRemoved)
    model.delete(0)

    assert model.count == 1
    assert not model.item(0)
    assert model.is_pending(0)
    assert model.value == []
    assert changes.count() == 1
    assert removals.count() == 0


def test_clearing_a_blank_row_announces_nothing(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """There is nothing to clear on a row that is already blank and pending.

    **Test steps:**

    * delete the only row of an empty never-empty model, watching for a data change
    * verify none was announced
    """
    model = make_never_empty()

    changes = QSignalSpy(model.dataChanged)
    model.delete(0)

    assert changes.count() == 0


def test_deleting_one_of_several_rows_removes_it(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """Only the last remaining row is cleared; any other is removed as usual.

    **Test steps:**

    * delete the first of two rows, then the one left
    * verify the first was removed and the second cleared
    """
    model = make_never_empty("a", "b")

    model.delete(0)
    assert names(model) == ["b"]
    model.delete(0)

    assert model.count == 1
    assert model.value == []


def test_deleting_a_row_that_does_not_exist_clears_nothing(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """An out-of-range row is a no-op here as everywhere, not a clear of the one row there is.

    **Test steps:**

    * delete row 3 of a one-row model, watching for a data change
    * verify nothing was announced and the row is untouched
    """
    model = make_never_empty("a")

    changes = QSignalSpy(model.dataChanged)
    model.delete(3)

    assert changes.count() == 0
    assert names(model) == ["a"]


def test_removing_every_row_is_refused(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """The model never goes to no rows, whatever asks.

    **Test steps:**

    * remove all rows of a two-row model through Qt's interface
    * verify it was refused and both rows remain
    """
    model = make_never_empty("a", "b")

    assert model.removeRows(0, 2) is False
    assert names(model) == ["a", "b"]


# endregion
