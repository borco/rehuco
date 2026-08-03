"""Tests for LogModel."""

import logging
from collections.abc import Hashable, Sequence

from borco_pyside.logging.log_bridge import DEFAULT_LOG_LIMIT
from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_model import (
    COLUMN_COUNT,
    LEVEL_COLUMN,
    MESSAGE_COLUMN,
    LogModel,
)
from borco_pyside.logging.log_record_sink import LogRecordSink
from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot

# region helpers


def make_entry(message: str, *, level: int = logging.INFO, scope: Hashable | None = None, serial: int = 0) -> LogEntry:
    """Build one entry the way the bridge would.

    :param message: the formatted message.
    :param level: the record's level.
    :param scope: what the record is about.
    :param serial: its position in the run.
    :returns: the entry.
    """
    record = logging.LogRecord("test", level, __file__, 1, message, None, None)
    return LogEntry(record, message, scope, serial)


def make_entries(*messages: str) -> Sequence[LogEntry]:
    """Build a batch of entries, serialled in order.

    :param messages: the formatted messages.
    :returns: the batch.
    """
    return [make_entry(message, serial=serial) for serial, message in enumerate(messages)]


def messages_of(model: LogModel) -> list[str]:
    """Read a model's message column, top to bottom.

    :param model: the model to read.
    :returns: the messages.
    """
    return [model.data(model.index(row, MESSAGE_COLUMN)) for row in range(model.rowCount())]


# endregion


# region fixtures


@fixture
def model(qtbot: QtBot) -> LogModel:
    """Provide an empty model.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the model.
    """
    del qtbot  # only needed so a QApplication exists
    return LogModel()


# endregion


# region taking entries


def test_a_new_model_is_empty(model: LogModel) -> None:
    """A model holds nothing until it is given something.

    **Test steps:**

    * build a model
    * verify it has no rows
    """
    assert model.rowCount() == 0


def test_a_batch_becomes_rows_in_order(model: LogModel) -> None:
    """Entries are appended in the order they were logged.

    **Test steps:**

    * hand the model a batch of three entries
    * verify the message column reads them back in order
    """
    model.handle_log_records(make_entries("first", "second", "third"))

    assert messages_of(model) == ["first", "second", "third"]


def test_a_batch_is_one_insertion(model: LogModel, qtbot: QtBot) -> None:
    """A batch of any size costs the view one row insertion, not one per record.

    **Test steps:**

    * hand the model a batch of three entries while watching rowsInserted
    * verify the signal fired once, spanning all three rows
    """
    with qtbot.waitSignal(model.rowsInserted) as inserted:
        model.handle_log_records(make_entries("first", "second", "third"))

    assert inserted.args is not None
    assert inserted.args[1:] == [0, 2]


def test_an_empty_batch_changes_nothing(model: LogModel) -> None:
    """Handing over no entries is a no-op rather than an empty insertion.

    **Test steps:**

    * hand the model an empty batch
    * verify it still has no rows
    """
    model.handle_log_records([])

    assert model.rowCount() == 0


def test_successive_batches_accumulate(model: LogModel) -> None:
    """A second batch is appended after the first, not instead of it.

    **Test steps:**

    * hand the model two batches in turn
    * verify both are present, in order
    """
    model.handle_log_records(make_entries("first"))
    model.handle_log_records(make_entries("second"))

    assert messages_of(model) == ["first", "second"]


# endregion


# region clearing


def test_clearing_drops_every_row(model: LogModel) -> None:
    """Clearing empties the model.

    **Test steps:**

    * hand the model a batch, then clear it
    * verify it has no rows
    """
    model.handle_log_records(make_entries("first", "second"))

    model.clear()

    assert model.rowCount() == 0


def test_clearing_an_empty_model_changes_nothing(model: LogModel, qtbot: QtBot) -> None:
    """Clearing a model that is already empty does not reset it for nothing.

    **Test steps:**

    * clear an empty model while watching modelReset
    * verify the signal never fired
    """
    with qtbot.assertNotEmitted(model.modelReset):
        model.clear()


def test_one_model_is_cleared_without_touching_another(model: LogModel) -> None:
    """Each model's history is its own: clearing one leaves the other alone.

    The rule behind a per-resource log surface -- emptying it says nothing about the app-wide one, or
    about another resource's.

    **Test steps:**

    * give two models the same batch
    * clear the first
    * verify the second still holds its rows
    """
    other = LogModel()
    model.handle_log_records(make_entries("first", "second"))
    other.handle_log_records(make_entries("first", "second"))

    model.clear()

    assert model.rowCount() == 0
    assert other.rowCount() == 2


def test_clearing_does_not_reset_what_was_dropped(model: LogModel) -> None:
    """The drop count survives a clear, because clearing brings nothing back.

    **Test steps:**

    * cap a model at one and give it two entries, dropping one
    * clear it
    * verify it still reports one dropped
    """
    model.limit = 1
    model.handle_log_records(make_entries("first", "second"))

    model.clear()

    assert model.dropped == 1


# endregion


# region the cap


def test_a_new_model_holds_the_default_number_of_rows(model: LogModel) -> None:
    """A model built with no limit uses the shared default.

    **Test steps:**

    * read a fresh model's limit
    * verify it is the default
    """
    assert model.limit == DEFAULT_LOG_LIMIT


def test_a_cap_below_one_still_holds_one(qtbot: QtBot) -> None:
    """A cap of zero or less is raised to one rather than making the model useless.

    **Test steps:**

    * build a model with a cap of zero
    * verify its limit is one
    """
    del qtbot  # only needed so a QApplication exists

    assert LogModel(limit=0).limit == 1


def test_the_oldest_rows_are_dropped_past_the_cap(qtbot: QtBot) -> None:
    """Past the cap, the model keeps its newest rows.

    **Test steps:**

    * build a model capped at two and hand it three entries in two batches
    * verify only the newest two remain
    """
    del qtbot  # only needed so a QApplication exists
    model = LogModel(limit=2)

    model.handle_log_records(make_entries("first", "second"))
    model.handle_log_records(make_entries("third"))

    assert messages_of(model) == ["second", "third"]


def test_dropping_rows_is_a_removal_not_a_reset(qtbot: QtBot) -> None:
    """Overflow removes rows, so a view keeps its selection and scroll position.

    **Test steps:**

    * build a model capped at one and give it a row
    * hand it another entry while watching rowsRemoved
    * verify the removal fired for the top row
    """
    model = LogModel(limit=1)
    model.handle_log_records(make_entries("first"))

    with qtbot.waitSignal(model.rowsRemoved) as removed:
        model.handle_log_records(make_entries("second"))

    assert removed.args is not None
    assert removed.args[1:] == [0, 0]


def test_a_batch_longer_than_the_cap_keeps_its_newest(qtbot: QtBot) -> None:
    """One oversized batch leaves what appending it record by record would have.

    **Test steps:**

    * build a model capped at two and hand it a batch of four
    * verify the last two are what remains
    """
    del qtbot  # only needed so a QApplication exists
    model = LogModel(limit=2)

    model.handle_log_records(make_entries("first", "second", "third", "fourth"))

    assert messages_of(model) == ["third", "fourth"]


def test_a_batch_longer_than_the_cap_reports_everything_it_lost(qtbot: QtBot) -> None:
    """Entries never put in the buffer are counted as dropped, not silently missing.

    **Test steps:**

    * build a model capped at two and hand it a batch of four
    * verify it reports two dropped
    """
    del qtbot  # only needed so a QApplication exists
    model = LogModel(limit=2)

    model.handle_log_records(make_entries("first", "second", "third", "fourth"))

    assert model.dropped == 2


def test_dropping_rows_announces_the_new_count(qtbot: QtBot) -> None:
    """A surface is told what it is missing without having to poll.

    **Test steps:**

    * build a model capped at one and give it a row
    * hand it another entry while watching dropped_changed
    * verify the signal carried the running total
    """
    model = LogModel(limit=1)
    model.handle_log_records(make_entries("first"))

    with qtbot.waitSignal(model.dropped_changed) as dropped:
        model.handle_log_records(make_entries("second"))

    assert dropped.args == [1]


def test_lowering_the_cap_trims_at_once(model: LogModel) -> None:
    """A cap lowered while running applies now, not at the next restart.

    **Test steps:**

    * give a model three rows, then lower its cap to one
    * verify only the newest row remains and two are reported dropped
    """
    model.handle_log_records(make_entries("first", "second", "third"))

    model.limit = 1

    assert messages_of(model) == ["third"]
    assert model.dropped == 2


def test_a_model_trimmed_by_a_lowered_cap_still_takes_entries(model: LogModel) -> None:
    """Re-capping leaves a working buffer, not one stuck at its old size.

    **Test steps:**

    * give a model three rows and lower its cap to two
    * hand it another entry
    * verify it holds the newest two
    """
    model.handle_log_records(make_entries("first", "second", "third"))
    model.limit = 2

    model.handle_log_records(make_entries("fourth"))

    assert messages_of(model) == ["third", "fourth"]


def test_raising_the_cap_drops_nothing(model: LogModel) -> None:
    """A cap raised while running leaves every row in place.

    **Test steps:**

    * give a model a row, then raise its cap
    * verify the row is still there and nothing is reported dropped
    """
    model.handle_log_records(make_entries("first"))

    model.limit = DEFAULT_LOG_LIMIT * 2

    assert messages_of(model) == ["first"]
    assert model.dropped == 0


def test_setting_the_same_cap_changes_nothing(model: LogModel, qtbot: QtBot) -> None:
    """Re-setting the cap to what it already is leaves the rows alone.

    **Test steps:**

    * give a model a row, then set its cap to the current value while watching rowsRemoved
    * verify nothing was removed
    """
    model.handle_log_records(make_entries("first"))

    with qtbot.assertNotEmitted(model.rowsRemoved):
        model.limit = model.limit

    assert messages_of(model) == ["first"]


# endregion


# region Qt model interface


def test_the_columns_are_the_level_and_the_message(model: LogModel) -> None:
    """A row lays out as level then message.

    **Test steps:**

    * hand the model one warning
    * verify the level column shows the level name and the message column the message
    """
    model.handle_log_records([make_entry("careful", level=logging.WARNING)])

    assert model.data(model.index(0, LEVEL_COLUMN)) == "WARNING"
    assert model.data(model.index(0, MESSAGE_COLUMN)) == "careful"


def test_the_whole_entry_is_reachable_through_its_own_role(model: LogModel) -> None:
    """Everything a delegate needs beyond the two columns is on the entry.

    **Test steps:**

    * hand the model one scoped entry
    * read the entry role on both columns
    * verify each gives back the entry itself
    """
    entry = make_entry("about a", scope="a")
    model.handle_log_records([entry])

    assert model.data(model.index(0, LEVEL_COLUMN), LogModel.Roles.ENTRY) is entry
    assert model.data(model.index(0, MESSAGE_COLUMN), LogModel.Roles.ENTRY) is entry


def test_an_unhandled_role_gives_back_nothing(model: LogModel) -> None:
    """A role the model does not answer gives None rather than a stray value.

    **Test steps:**

    * hand the model one entry
    * ask for its tooltip
    * verify the answer is None
    """
    model.handle_log_records(make_entries("first"))

    assert model.data(model.index(0, MESSAGE_COLUMN), Qt.ItemDataRole.ToolTipRole) is None


def test_an_invalid_index_holds_nothing(model: LogModel) -> None:
    """An invalid index answers None instead of raising.

    **Test steps:**

    * hand the model one entry
    * read data at an invalid index
    * verify the answer is None
    """
    model.handle_log_records(make_entries("first"))

    assert model.data(QModelIndex()) is None


def test_the_table_is_flat(model: LogModel) -> None:
    """A row has no children -- the log is a list, not a tree.

    **Test steps:**

    * hand the model one entry
    * count the rows and columns under the first row
    * verify both are zero
    """
    model.handle_log_records(make_entries("first"))
    child = model.index(0, 0)

    assert model.rowCount(child) == 0
    assert model.columnCount(child) == 0


def test_the_columns_are_titled(model: LogModel) -> None:
    """The header names both columns.

    **Test steps:**

    * read the horizontal header for both columns
    * verify the titles
    """
    assert model.headerData(LEVEL_COLUMN, Qt.Orientation.Horizontal) == "Level"
    assert model.headerData(MESSAGE_COLUMN, Qt.Orientation.Horizontal) == "Message"


def test_rows_are_not_titled(model: LogModel) -> None:
    """Only the horizontal header carries titles, and only for the display role.

    **Test steps:**

    * ask for a vertical header title, a non-display role, and an out-of-range column
    * verify each answers None
    """
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(LEVEL_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert model.headerData(COLUMN_COUNT, Qt.Orientation.Horizontal) is None


# endregion


# region the protocol


def test_the_model_satisfies_the_sink_protocol(model: LogModel) -> None:
    """A log model is a sink structurally, with no Protocol inheritance.

    **Test steps:**

    * check the model against the sink protocol
    * verify it satisfies it
    """
    assert isinstance(model, LogRecordSink)


# endregion
