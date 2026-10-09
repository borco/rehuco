"""Every search box answers the same text pair the same way (#475): the shared matcher, the Settings frame filter,
the Shortcuts table, both conversion dialogs and the log. The catalog's own search is the cache's, tested beside it."""

import logging
from collections.abc import Callable
from typing import Final

from borco_core import TextMatcher
from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_filter_model import LogFilterModel
from borco_pyside.logging.log_model import LogModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.conversion_backups_table_model import RESOURCE_COLUMN, ConversionBackupsFilterProxyModel
from rehuco_agent.dialogs.tc_conversion_plan_table_model import PATH_COLUMN, TcConversionPlanFilterProxyModel
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.shortcuts_table_model import SEARCH_TEXT_ROLE, ShortcutsFilterProxyModel

from rehuco_agent_tests.settings.ui.test_settings_frame_filter import make_page

COLUMNS: Final = 8
"""Wider than any column either dialog reads, so the unused ones are empty cells."""


def matcher_finds(_qtbot: QtBot, text: str, search: str) -> bool:
    """Ask the shared matcher."""
    return TextMatcher.of(search).matches(text)


def frame_filter_shows(qtbot: QtBot, text: str, search: str) -> bool:
    """Ask a Settings page's frame filter whether the frame holding ``text`` stays visible."""
    groups = [list((text,))]  # one frame, one label
    page, (frame,) = make_page(qtbot, groups)
    SettingsFrameFilter(page, "A title that matches nothing").apply(search, show_full_on_title_match=False)
    return frame.isVisibleTo(page)


def shortcuts_keeps(_qtbot: QtBot, text: str, search: str) -> bool:
    """Ask the Shortcuts table's proxy whether a row whose search text is ``text`` stays."""
    source = QStandardItemModel(0, 1)
    item = QStandardItem()
    item.setData(text, SEARCH_TEXT_ROLE)
    source.appendRow(item)
    proxy = ShortcutsFilterProxyModel()
    proxy.setSourceModel(source)
    proxy.set_filter_text(search)
    return proxy.rowCount() == 1


def column_proxy_keeps(
    proxy: ConversionBackupsFilterProxyModel | TcConversionPlanFilterProxyModel, column: int
) -> Callable[[str, str], bool]:
    """Build a one-row source holding the text in ``column``, set the search, and return a function of the text."""

    def keeps(text: str, search: str) -> bool:
        source = QStandardItemModel(1, COLUMNS)
        source.setItem(0, column, QStandardItem(text))
        proxy.setSourceModel(source)
        proxy.set_filter_text(search)
        return proxy.rowCount() == 1

    return keeps


def backups_keeps(_qtbot: QtBot, text: str, search: str) -> bool:
    """Ask the conversion-backups dialog's proxy."""
    return column_proxy_keeps(ConversionBackupsFilterProxyModel(), RESOURCE_COLUMN)(text, search)


def plan_keeps(_qtbot: QtBot, text: str, search: str) -> bool:
    """Ask the .tc conversion plan dialog's proxy."""
    return column_proxy_keeps(TcConversionPlanFilterProxyModel(), PATH_COLUMN)(text, search)


def log_keeps(_qtbot: QtBot, text: str, search: str) -> bool:
    """Ask the log's proxy whether a record with the message ``text`` stays."""
    record = logging.LogRecord("test", logging.INFO, __file__, 1, text, None, None)
    source = LogModel()
    source.handle_log_records([LogEntry(record, text, (), 0)])
    proxy = LogFilterModel()
    proxy.setSourceModel(source)
    proxy.search = search
    return proxy.rowCount() == 1


SITES: Final[dict[str, Callable[[QtBot, str, str], bool]]] = {
    "matcher": matcher_finds,
    "settings frames": frame_filter_shows,
    "shortcuts": shortcuts_keeps,
    "conversion backups": backups_keeps,
    "tc conversion plan": plan_keeps,
    "log": log_keeps,
}
"""Each search box, as a function of its text and the search typed into it."""

CASES: Final = (
    ("Intro to Blender", "blender intro", True),  # every word, in any order
    ("Intro to Blender", '"intro to"', True),  # a phrase
    ("Intro to Blender", '"blender intro"', False),  # a phrase is in order
    ("Intro to Blender", "blender zbrush", False),  # every word is needed
    ("José Pérez", "jose perez", True),  # accents typed away
    ("Jose Perez", "JOSÉ", True),  # accents typed, case ignored
    ("Straße", "strasse", True),
    ("Intro to Blender", "", True),  # nothing typed narrows nothing
)
"""``(text, search, whether it is found)``."""


@mark.parametrize("site", SITES)
@mark.parametrize(("text", "search", "found"), CASES)
def test_every_search_box_answers_a_text_pair_alike(
    qtbot: QtBot, site: str, text: str, search: str, found: bool
) -> None:
    """The same text and search give the same answer wherever they are typed.

    **Test steps:**

    * ask one search box about a text and a search: words in any order, a phrase, accents, case, nothing typed
    * verify it finds the text exactly when the shared rule says it should
    """
    assert SITES[site](qtbot, text, search) is found
