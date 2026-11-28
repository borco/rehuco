"""Tests for a table browser's selection entries (#646, #679, #688): which menu offers them, in what order, and what
choosing one asks for -- *Refresh License* and the two copies. What the paths are and how they read is the dock's and
:mod:`~.copied_paths`' to test."""

from dataclasses import replace

from borco_pyside.file_browser import FILE_BROWSER_NAME
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.copied_paths import CopyFormat, json_paths, quoted_paths
from rehuco_core import CatalogRow

from .test_table_browser import (  # noqa: F401  # pylint: disable=unused-import
    ROOT_ID,
    authored_row,
    fixture_browser,
    right_click,
    row,
    select,
)

SELECTION_ENTRIES = [
    f"Open in {FILE_BROWSER_NAME}",
    "Open in Web Browser",
    "Refresh License",
    "Copy paths",
    "Copy paths as JSON",
]
"""The five entries' texts, in menu order: the two open entries (#720, #679), the refresh (#688), then the two
copies."""


def asset_row(path: str) -> CatalogRow:
    """A cache row whose record is an asset.

    :param path: the record's path under the root.
    :returns: the row.
    """
    plain = row(path, 1)
    return replace(plain, record=replace(plain.record, type="asset"))


def test_a_selection_offers_its_entries_on_any_cell(browser: TableBrowser, monkeypatch: MonkeyPatch) -> None:
    """The entries follow the selection, not the clicked column.

    **Test steps:**

    * select a row and right-click its Title cell
    * verify the menu holds the five entries alone
    """
    browser.set_rows([row("a/info.rehu", 1)], [ROOT_ID])
    select(browser, 0)

    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)

    assert [action.text() for action in actions] == SELECTION_ENTRIES


def test_an_authors_cell_keeps_its_entries_and_adds_the_selections_after_a_separator(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The author entries come first, as before, then a separator and the selection's five.

    **Test steps:**

    * select a row with two authors and right-click its Authors cell
    * verify both author entries, a separator, then the five entries
    """
    browser.set_rows([authored_row("a.rehu", "Ann", "Bob")], [ROOT_ID])
    select(browser, 0)

    actions = right_click(browser, CatalogColumn.AUTHORS, monkeypatch)

    assert [action.isSeparator() for action in actions] == [False, False, True, False, False, False, False, False]
    assert [action.text() for action in actions if not action.isSeparator()] == [
        "Filter by Ann",
        "Filter by Bob",
        *SELECTION_ENTRIES,
    ]


def test_with_nothing_selected_no_menu_opens_but_an_authors_cells(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """Nothing is offered for no rows; an Authors cell still offers its authors, with no separator after them.

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
    * choose each copy entry
    * verify each asked for the first row's key then the third's, with quoted paths then JSON, the JSON naming
      licenses and the quoted not
    """
    browser.set_rows([row("a/info.rehu", 1), row("b.rehu", 1), row("c.rehu", 1)], [ROOT_ID])
    select(browser, 2, 0)
    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)
    keys = ((ROOT_ID, "a/info.rehu"), (ROOT_ID, "c.rehu"))

    for action, expected in zip(
        actions[3:],
        (CopyFormat("Copy paths", quoted_paths), CopyFormat("Copy paths as JSON", json_paths, True)),
        strict=True,
    ):
        with qtbot.waitSignal(browser.copy_paths_requested) as requested:
            action.trigger()
        assert requested.args == [keys, expected, frozenset()]


def test_a_copy_that_names_licenses_says_which_of_the_selected_rows_are_assets(
    qtbot: QtBot, browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """Only an asset can have a license text, so the dock is told which rows to look for one beside; a plain copy is not
    told, since it looks for none.

    **Test steps:**

    * show an asset, a tutorial and an asset, and select all three
    * choose the JSON copy and verify it names the two assets' keys
    * choose the quoted copy and verify it names none
    """
    browser.set_rows([asset_row("a/info.rehu"), row("b.rehu", 1), asset_row("c.rehu")], [ROOT_ID])
    select(browser, 0, 1, 2)
    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)

    with qtbot.waitSignal(browser.copy_paths_requested) as as_json:
        actions[4].trigger()
    with qtbot.waitSignal(browser.copy_paths_requested) as quoted:
        actions[3].trigger()

    assert as_json.args is not None and as_json.args[2] == frozenset({(ROOT_ID, "a/info.rehu"), (ROOT_ID, "c.rehu")})
    assert quoted.args is not None and quoted.args[2] == frozenset()


def test_refresh_license_is_offered_only_while_an_asset_is_selected(
    qtbot: QtBot, browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The entry is there for any selection, so the menu keeps its shape, and enabled where an asset is to refresh.

    **Test steps:**

    * select a tutorial alone and verify the entry is disabled
    * select it with an asset and choose the entry
    * verify the refresh asked for both rows' keys, in the table's order
    """
    browser.set_rows([row("a/info.rehu", 1), asset_row("b.rehu")], [ROOT_ID])
    select(browser, 0)
    assert not right_click(browser, CatalogColumn.TITLE, monkeypatch)[2].isEnabled()

    select(browser, 1, 0)
    action = right_click(browser, CatalogColumn.TITLE, monkeypatch)[2]
    with qtbot.waitSignal(browser.refresh_license_requested) as requested:
        action.trigger()

    assert action.isEnabled()
    assert requested.args == [((ROOT_ID, "a/info.rehu"), (ROOT_ID, "b.rehu"))]


def test_a_row_out_of_range_is_no_asset(browser: TableBrowser) -> None:
    """**Test steps:**

    * ask the model whether rows out of range are assets, and whether a tutorial and an asset are
    * verify only the asset is
    """
    browser.set_rows([row("a.rehu", 1), asset_row("b.rehu")], [ROOT_ID])

    assert [browser.model.is_asset(index) for index in (-1, 0, 1, 2)] == [False, False, True, False]
