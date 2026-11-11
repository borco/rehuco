"""Tests for a table browser's *Copy paths* and *Copy paths as JSON* entries (#646): which menu offers them, and what
choosing one asks for. What the paths are and how they read is the dock's and :mod:`~.copied_paths`' to test."""

from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.copied_paths import json_paths, quoted_paths

from .test_table_browser import (  # noqa: F401  # pylint: disable=unused-import
    ROOT_ID,
    authored_row,
    fixture_browser,
    right_click,
    row,
    select,
)

COPY_ENTRIES = ["Copy paths", "Copy paths as JSON"]
"""The two entries' texts, in menu order."""


def test_a_selection_offers_both_copies_on_any_cell(browser: TableBrowser, monkeypatch: MonkeyPatch) -> None:
    """The entries follow the selection, not the clicked column.

    **Test steps:**

    * select a row and right-click its Title cell
    * verify the menu holds the two copy entries alone
    """
    browser.set_rows([row("a/info.rehu", 1)], [ROOT_ID])
    select(browser, 0)

    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)

    assert [action.text() for action in actions] == COPY_ENTRIES


def test_an_authors_cell_keeps_its_entries_and_adds_the_copies_after_a_separator(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The author entries come first, as before, then a separator and the two copies.

    **Test steps:**

    * select a row with two authors and right-click its Authors cell
    * verify both author entries, a separator, then the two copy entries
    """
    browser.set_rows([authored_row("a.rehu", "Ann", "Bob")], [ROOT_ID])
    select(browser, 0)

    actions = right_click(browser, CatalogColumn.AUTHORS, monkeypatch)

    assert [action.isSeparator() for action in actions] == [False, False, True, False, False]
    assert [action.text() for action in actions if not action.isSeparator()] == [
        "Filter by Ann",
        "Filter by Bob",
        *COPY_ENTRIES,
    ]


def test_with_nothing_selected_no_menu_opens_but_an_authors_cells(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """No copy is offered for no rows; an Authors cell still offers its authors, with no separator after them.

    **Test steps:**

    * show a row with authors, with nothing selected
    * right-click its Title cell, then its Authors cell
    * verify no menu, then the author entry alone
    """
    browser.set_rows([authored_row("a.rehu", "Ann")], [ROOT_ID])

    assert not right_click(browser, CatalogColumn.TITLE, monkeypatch)
    assert [action.text() for action in right_click(browser, CatalogColumn.AUTHORS, monkeypatch)] == ["Filter by Ann"]


def test_choosing_a_copy_asks_for_the_selected_rows_in_the_tables_order_and_its_format(
    qtbot: QtBot, browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The rows go in the table's order, whatever order they were selected in, each entry with its own format.

    **Test steps:**

    * show three rows and select the third, then the first
    * choose each entry
    * verify each asked for the first row's key then the third's, with quoted paths then JSON
    """
    browser.set_rows([row("a/info.rehu", 1), row("b.rehu", 1), row("c.rehu", 1)], [ROOT_ID])
    select(browser, 2, 0)
    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)
    keys = ((ROOT_ID, "a/info.rehu"), (ROOT_ID, "c.rehu"))

    for action, writer in zip(actions, (quoted_paths, json_paths), strict=True):
        with qtbot.waitSignal(browser.copy_paths_requested) as requested:
            action.trigger()
        assert requested.args == [keys, writer]
