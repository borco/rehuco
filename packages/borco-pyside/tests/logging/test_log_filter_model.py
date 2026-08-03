"""Tests for LogFilterModel."""

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_filter_model import LogFilterModel
from borco_pyside.logging.log_level_band import LogLevelBand
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
"""One record per named level, so every band has something in it and the errors band has two."""


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


# region the level bands


def test_nothing_is_filtered_out_by_default(proxy: LogFilterModel) -> None:
    """A fresh filter shows every record, because every band starts shown.

    **Test steps:**

    * read the proxy without setting a filter
    * verify every band is visible and every record with it
    """
    assert proxy.visible_bands == frozenset(LogLevelBand)
    assert len(messages_of(proxy)) == len(LEVELS)


def test_showing_one_band_hides_the_other_three(proxy: LogFilterModel) -> None:
    """Asking for exactly the debugs gets the debugs, and nothing above them.

    The whole reason these are toggles rather than a threshold: a reader digging through debug
    output is trying to get the rest out of the way, and a floor would drag it all back in.

    **Test steps:**

    * show only the debugs band
    * verify the debug note is visible and no info, warning or error is
    """
    proxy.visible_bands = {LogLevelBand.DEBUGS}

    assert messages_of(proxy) == ["a debug note"]


def test_each_band_can_be_shown_alone(proxy: LogFilterModel) -> None:
    """Every band stands on its own, not only the lowest one.

    **Test steps:**

    * show only the warnings band
    * verify the warning is visible and neither the info below nor the error above is
    """
    proxy.visible_bands = {LogLevelBand.WARNINGS}

    assert messages_of(proxy) == ["a warning"]


def test_bands_are_independent_of_each_other(proxy: LogFilterModel) -> None:
    """Showing two bands with a hidden one between them is a state the filter honours.

    **Test steps:**

    * show the debugs and the errors, leaving out the infos and warnings
    * verify only those two bands' records are visible
    """
    proxy.visible_bands = {LogLevelBand.DEBUGS, LogLevelBand.ERRORS}

    assert messages_of(proxy) == ["a debug note", "an error", "a catastrophe"]


def test_hiding_every_band_shows_nothing(proxy: LogFilterModel) -> None:
    """Turning all four off is a choice, not a state to be corrected back to showing everything.

    **Test steps:**

    * hide every band
    * verify nothing is visible
    """
    proxy.visible_bands = set()

    assert messages_of(proxy) == []


def test_the_errors_band_covers_everything_above_warning(proxy: LogFilterModel) -> None:
    """Errors and criticals share one band, and one toggle.

    **Test steps:**

    * show only the errors band
    * verify both the error and the catastrophe are visible
    """
    proxy.visible_bands = {LogLevelBand.ERRORS}

    assert messages_of(proxy) == ["an error", "a catastrophe"]


def test_a_level_nobody_named_is_filtered_by_its_band(proxy: LogFilterModel, source: LogModel) -> None:
    """A record logged between two named levels is shown by the band covering it.

    **Test steps:**

    * hand the source a record logged between INFO and WARNING
    * show only the warnings band
    * verify the record is visible
    """
    source.handle_log_records([make_entry(logging.INFO + 1, "logged at an odd level", len(LEVELS))])

    proxy.visible_bands = {LogLevelBand.WARNINGS}

    assert messages_of(proxy) == ["a warning", "logged at an odd level"]


def test_one_band_is_toggled_without_disturbing_the_others(proxy: LogFilterModel) -> None:
    """A toggle button changes its own band and leaves the rest alone.

    **Test steps:**

    * turn off the debugs, then the infos
    * verify both are gone and the warnings and errors are untouched
    """
    proxy.set_band_visible(LogLevelBand.DEBUGS, False)
    proxy.set_band_visible(LogLevelBand.INFOS, False)

    assert messages_of(proxy) == ["a warning", "an error", "a catastrophe"]


def test_a_band_is_toggled_back_on(proxy: LogFilterModel) -> None:
    """Turning a band off and on again restores exactly it.

    **Test steps:**

    * turn the warnings off, then on again
    * verify every record is visible
    """
    proxy.set_band_visible(LogLevelBand.WARNINGS, False)

    proxy.set_band_visible(LogLevelBand.WARNINGS, True)

    assert len(messages_of(proxy)) == len(LEVELS)


def test_turning_on_a_band_that_is_already_on_changes_nothing(proxy: LogFilterModel, qtbot: QtBot) -> None:
    """A toggle set to the state it is already in does no work.

    **Test steps:**

    * turn on a band that is already on, while watching for a refilter
    * verify the model was not invalidated
    """
    with qtbot.assertNotEmitted(proxy.layoutChanged):
        proxy.set_band_visible(LogLevelBand.WARNINGS, True)


def test_the_bands_read_back_what_was_set(proxy: LogFilterModel) -> None:
    """The bands are readable, so four toggle buttons can show the state they drive.

    **Test steps:**

    * show two bands
    * verify the proxy reports exactly those
    """
    proxy.visible_bands = {LogLevelBand.INFOS, LogLevelBand.ERRORS}

    assert proxy.visible_bands == {LogLevelBand.INFOS, LogLevelBand.ERRORS}


def test_showing_the_bands_again_brings_records_back(proxy: LogFilterModel) -> None:
    """Filtering hides records rather than discarding them.

    **Test steps:**

    * hide every band, then show them all again
    * verify every record is visible
    """
    proxy.visible_bands = set()

    proxy.visible_bands = set(LogLevelBand)

    assert len(messages_of(proxy)) == len(LEVELS)


def test_filtering_hides_nothing_from_the_source(proxy: LogFilterModel, source: LogModel) -> None:
    """A narrowed view leaves the model holding everything.

    **Test steps:**

    * show only the warnings band
    * verify the proxy shows one row while the source still holds them all
    """
    proxy.visible_bands = {LogLevelBand.WARNINGS}

    assert len(messages_of(proxy)) == 1
    assert source.rowCount() == len(LEVELS)


def test_records_arriving_while_narrowed_are_kept(proxy: LogFilterModel, source: LogModel) -> None:
    """A record that did not match when it arrived shows up once the filter widens.

    **Test steps:**

    * show only the errors band and hand the source a debug record
    * verify it is not visible
    * show the debugs and verify it appears
    """
    proxy.visible_bands = {LogLevelBand.ERRORS}
    source.handle_log_records([make_entry(logging.DEBUG, "arrived while narrowed", len(LEVELS))])

    assert "arrived while narrowed" not in messages_of(proxy)

    proxy.set_band_visible(LogLevelBand.DEBUGS, True)

    assert "arrived while narrowed" in messages_of(proxy)


def test_setting_the_same_bands_does_not_refilter(proxy: LogFilterModel, qtbot: QtBot) -> None:
    """Re-setting the bands to what they already are does no work.

    **Test steps:**

    * set the bands, then set them again to the same value while watching for a refilter
    * verify the model was not invalidated the second time
    """
    proxy.visible_bands = {LogLevelBand.WARNINGS}

    with qtbot.assertNotEmitted(proxy.layoutChanged):
        proxy.visible_bands = {LogLevelBand.WARNINGS}


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


def test_the_search_and_the_bands_both_apply(proxy: LogFilterModel) -> None:
    """The two filters narrow together, not one instead of the other.

    **Test steps:**

    * search for "note" and show only the debugs band
    * verify only the debug message containing it is visible, not the info note
    """
    proxy.search = "note"
    proxy.visible_bands = {LogLevelBand.DEBUGS}

    assert messages_of(proxy) == ["a debug note"]


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

    * put the filter over a plain string list model and hide every band
    * verify its rows are still shown
    """
    del qtbot  # only needed so a QApplication exists
    source = StringItemListModel()
    source.set_entries(["not a log entry"])
    proxy = LogFilterModel()
    proxy.setSourceModel(source)

    proxy.visible_bands = set()

    assert proxy.rowCount() == 1


# endregion
