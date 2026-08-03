"""Tests for LogFilterModel."""

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_filter_model import LogFilterModel
from borco_pyside.logging.log_model import MESSAGE_COLUMN, LogModel
from borco_pyside.widgets import StringItemListModel
from pytest import fixture
from pytestqt.qtbot import QtBot

LEVELS = (
    (logging.DEBUG, "a debug note"),
    (logging.INFO, "an info note"),
    (logging.WARNING, "a warning"),
    (logging.ERROR, "an error"),
    (logging.CRITICAL, "a catastrophe"),
)
"""One record per level, so a threshold's cut is visible from either side of it."""


# region helpers


def make_entry(level: int, message: str, serial: int) -> LogEntry:
    """Build one entry the way the bridge would.

    :param level: the record's level.
    :param message: the formatted message.
    :param serial: its position in the run.
    :returns: the entry.
    """
    record = logging.LogRecord("test", level, __file__, 1, message, None, None)
    return LogEntry(record, message, None, serial)


def messages_of(model: LogFilterModel) -> list[str]:
    """Read what the proxy shows, top to bottom.

    :param model: the proxy to read.
    :returns: the visible messages.
    """
    return [model.data(model.index(row, MESSAGE_COLUMN)) for row in range(model.rowCount())]


# endregion


# region fixtures


@fixture
def source(qtbot: QtBot) -> LogModel:
    """Provide a model holding one record per level.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the model.
    """
    del qtbot  # only needed so a QApplication exists
    model = LogModel()
    model.handle_log_records([make_entry(level, message, serial) for serial, (level, message) in enumerate(LEVELS)])
    return model


@fixture
def proxy(source: LogModel) -> LogFilterModel:
    """Provide a filter over that model, filtering nothing yet.

    :param source: the model to filter.
    :returns: the proxy.
    """
    model = LogFilterModel()
    model.setSourceModel(source)
    return model


# endregion


# region the level floor


def test_nothing_is_filtered_out_by_default(proxy: LogFilterModel) -> None:
    """A fresh filter shows every record.

    **Test steps:**

    * read the proxy without setting a filter
    * verify every record is visible
    """
    assert len(messages_of(proxy)) == len(LEVELS)


def test_the_floor_reads_back_what_was_set(proxy: LogFilterModel) -> None:
    """The floor is readable, so a control can show the state it is driving.

    **Test steps:**

    * verify a fresh filter reports NOTSET
    * set the floor and verify it reports the new value
    """
    assert proxy.minimum_level == logging.NOTSET

    proxy.minimum_level = logging.WARNING

    assert proxy.minimum_level == logging.WARNING


def test_a_floor_hides_everything_below_it(proxy: LogFilterModel) -> None:
    """Setting a minimum level shows that level and worse.

    **Test steps:**

    * set the floor to WARNING
    * verify the warning, error and catastrophe are visible and the rest are not
    """
    proxy.minimum_level = logging.WARNING

    assert messages_of(proxy) == ["a warning", "an error", "a catastrophe"]


def test_the_floor_is_inclusive(proxy: LogFilterModel) -> None:
    """A record exactly at the floor is shown, not hidden.

    **Test steps:**

    * set the floor to ERROR
    * verify the error itself is visible
    """
    proxy.minimum_level = logging.ERROR

    assert "an error" in messages_of(proxy)


def test_a_floor_between_two_named_levels_is_honoured(proxy: LogFilterModel) -> None:
    """The floor is a number, not one of five choices.

    **Test steps:**

    * set the floor between WARNING and ERROR
    * verify the warning is hidden and the error is not
    """
    proxy.minimum_level = logging.WARNING + 1

    assert messages_of(proxy) == ["an error", "a catastrophe"]


def test_lowering_the_floor_brings_records_back(proxy: LogFilterModel) -> None:
    """Filtering hides records rather than discarding them.

    **Test steps:**

    * raise the floor to CRITICAL, then drop it back to NOTSET
    * verify every record is visible again
    """
    proxy.minimum_level = logging.CRITICAL

    proxy.minimum_level = logging.NOTSET

    assert len(messages_of(proxy)) == len(LEVELS)


def test_filtering_hides_nothing_from_the_source(proxy: LogFilterModel, source: LogModel) -> None:
    """A narrowed view leaves the model holding everything.

    **Test steps:**

    * set the floor to CRITICAL
    * verify the proxy shows one row while the source still holds them all
    """
    proxy.minimum_level = logging.CRITICAL

    assert len(messages_of(proxy)) == 1
    assert source.rowCount() == len(LEVELS)


def test_records_arriving_while_narrowed_are_kept(proxy: LogFilterModel, source: LogModel) -> None:
    """A record that did not match when it arrived shows up once the filter widens.

    **Test steps:**

    * set the floor to CRITICAL and hand the source a debug record
    * verify it is not visible
    * drop the floor and verify it appears
    """
    proxy.minimum_level = logging.CRITICAL
    source.handle_log_records([make_entry(logging.DEBUG, "arrived while narrowed", len(LEVELS))])

    assert "arrived while narrowed" not in messages_of(proxy)

    proxy.minimum_level = logging.NOTSET

    assert "arrived while narrowed" in messages_of(proxy)


def test_setting_the_same_floor_does_not_refilter(proxy: LogFilterModel, qtbot: QtBot) -> None:
    """Re-setting the floor to what it already is does no work.

    **Test steps:**

    * set the floor, then set it again to the same value while watching for a refilter
    * verify the model was not invalidated the second time
    """
    proxy.minimum_level = logging.WARNING

    with qtbot.assertNotEmitted(proxy.layoutChanged):
        proxy.minimum_level = logging.WARNING


# endregion


# region the search


def test_the_search_reads_back_what_was_set(proxy: LogFilterModel) -> None:
    """The search is readable, so a control can show the state it is driving.

    **Test steps:**

    * verify a fresh filter reports an empty search
    * set the search and verify it reports the new value
    """
    assert proxy.search == ""

    proxy.search = "warning"

    assert proxy.search == "warning"


def test_a_search_keeps_only_matching_messages(proxy: LogFilterModel) -> None:
    """The search narrows to messages containing it.

    **Test steps:**

    * search for "warning"
    * verify only the warning is visible
    """
    proxy.search = "warning"

    assert messages_of(proxy) == ["a warning"]


def test_the_search_ignores_case(proxy: LogFilterModel) -> None:
    """A search matches regardless of case, in either direction.

    **Test steps:**

    * search for "CATASTROPHE"
    * verify the lowercase message matched
    """
    proxy.search = "CATASTROPHE"

    assert messages_of(proxy) == ["a catastrophe"]


def test_an_empty_search_matches_everything(proxy: LogFilterModel) -> None:
    """Clearing the search stops filtering by it.

    **Test steps:**

    * search for something, then clear the search
    * verify every record is visible again
    """
    proxy.search = "warning"

    proxy.search = ""

    assert len(messages_of(proxy)) == len(LEVELS)


def test_a_search_matching_nothing_shows_nothing(proxy: LogFilterModel) -> None:
    """A search with no match leaves an empty view rather than an unfiltered one.

    **Test steps:**

    * search for a string no message contains
    * verify nothing is visible
    """
    proxy.search = "no message says this"

    assert messages_of(proxy) == []


def test_the_search_and_the_floor_both_apply(proxy: LogFilterModel) -> None:
    """The two filters narrow together, not one instead of the other.

    **Test steps:**

    * search for "a" and set the floor to ERROR
    * verify only the error-or-worse messages containing it are visible
    """
    proxy.search = "a"
    proxy.minimum_level = logging.ERROR

    assert messages_of(proxy) == ["an error", "a catastrophe"]


def test_setting_the_same_search_does_not_refilter(proxy: LogFilterModel, qtbot: QtBot) -> None:
    """Re-setting the search to what it already is does no work.

    **Test steps:**

    * set the search, then set it again to the same value while watching for a refilter
    * verify the model was not invalidated the second time
    """
    proxy.search = "warning"

    with qtbot.assertNotEmitted(proxy.layoutChanged):
        proxy.search = "warning"


# endregion


# region a source that is not a log model


def test_rows_that_are_not_log_entries_fall_back_to_the_base_filter(qtbot: QtBot) -> None:
    """Over a model holding something else, the proxy defers rather than hiding everything.

    **Test steps:**

    * put the filter over a plain string list model and set a floor
    * verify its rows are still shown
    """
    del qtbot  # only needed so a QApplication exists
    source = StringItemListModel()
    source.set_entries(["not a log entry"])
    proxy = LogFilterModel()
    proxy.setSourceModel(source)

    proxy.minimum_level = logging.CRITICAL

    assert proxy.rowCount() == 1


# endregion
