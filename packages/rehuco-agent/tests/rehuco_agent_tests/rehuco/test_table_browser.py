"""Tests for the table browser: a catalog's rows as a table, with a status line and a state worth remembering (#396)."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.rehuco.catalog_table_model import TITLE_COLUMN
from rehuco_agent.settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from rehuco_core import CatalogRecord, CatalogRow, RecordKind

ROOT_ID = uuid4()
ROOT_PATH = Path("/fake/root")


def row(path: str, size: int, title: str = "") -> CatalogRow:
    """A cache row for one ``.rehu`` of ``size`` bytes under the test root.

    :param path: the record's path under the root.
    :param size: its size.
    :param title: its title.
    :returns: the row.
    """
    record = CatalogRecord(path, RecordKind.REHU, title=title or path, type="tutorial", current_size=size)
    return CatalogRow(resource_id=1, root_id=ROOT_ID, root_label="root", record=record, scanned_at=0.0)


@fixture(name="browser")
def fixture_browser(qtbot: QtBot) -> Iterator[TableBrowser]:
    """A new browser, owned by the test."""
    browser = TableBrowser()
    qtbot.addWidget(browser)
    yield browser


def test_a_new_browser_has_a_fresh_id_the_default_name_and_no_filter(qtbot: QtBot) -> None:
    """Two new browsers are told apart, and start out the same way.

    **Test steps:**

    * build two browsers with no state
    * verify different ids, the default name, the table kind and an empty filter
    """
    first, second = TableBrowser(), TableBrowser()
    qtbot.addWidget(first)
    qtbot.addWidget(second)

    assert first.browser_id != second.browser_id
    assert (first.name, first.kind, first.filter_text) == (TableBrowser.DEFAULT_NAME, TABLE_BROWSER_KIND, "")


def test_a_browser_built_from_a_state_takes_its_id_name_and_filter(qtbot: QtBot) -> None:
    """What was remembered is what comes back.

    **Test steps:**

    * build a browser from a state
    * verify its id, name and filter
    """
    state = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Python", 'type:"tutorial"')
    browser = TableBrowser(state)
    qtbot.addWidget(browser)

    assert (browser.browser_id, browser.name, browser.filter_text) == (state.browser_id, "Python", 'type:"tutorial"')


def test_a_model_with_no_row_has_no_path(browser: TableBrowser) -> None:
    """Nothing is opened for a row the model does not hold.

    **Test steps:**

    * ask the empty model for row 0's path
    * verify there is none
    """
    assert browser.model.absolute_path(0) is None


def test_the_status_line_says_no_resources_when_the_table_is_empty(browser: TableBrowser) -> None:
    """An empty table is said so, not left blank.

    **Test steps:**

    * read the status line of a browser with no rows
    * verify it reads ``No resources``
    """
    assert browser.status_bar.currentMessage() == "No resources"


def test_the_status_line_counts_the_rows_and_adds_up_their_sizes(browser: TableBrowser) -> None:
    """The count follows the rows shown, with the singular spelled right.

    **Test steps:**

    * show one 1.5 KiB row and then a second of 2 KiB
    * verify ``1 resource / 1.5K`` and then ``2 resources / 3.5K``
    """
    browser.set_rows([row("a/info.rehu", 1536)], {ROOT_ID: ROOT_PATH})
    assert browser.status_bar.currentMessage() == "1 resource / 1.5K"

    browser.set_rows([row("a/info.rehu", 1536), row("b/info.rehu", 2048)], {ROOT_ID: ROOT_PATH})
    assert browser.status_bar.currentMessage() == "2 resources / 3.5K"


def test_a_browser_starts_unsorted(browser: TableBrowser) -> None:
    """No arrow on a column until one is clicked, because the rows start in the cache's order.

    **Test steps:**

    * read the sort indicator of a new browser
    * verify no column is marked
    """
    assert browser.view.horizontalHeader().sortIndicatorSection() == -1


def test_a_double_click_on_a_row_announces_its_path_and_on_nothing_announces_nothing(
    qtbot: QtBot, browser: TableBrowser
) -> None:
    """Activating a row asks for its resource to be opened, by absolute path.

    **Test steps:**

    * show a row and double-click it, then double-click no row
    * verify the first announces the row's absolute path and the second nothing
    """
    browser.set_rows([row("python/info.rehu", 10)], {ROOT_ID: ROOT_PATH})

    with qtbot.waitSignal(browser.row_activated) as activated:
        browser.view.doubleClicked.emit(browser.model.index(0, 0))
    assert activated.args == [ROOT_PATH / "python/info.rehu"]

    with qtbot.assertNotEmitted(browser.row_activated):
        browser.view.doubleClicked.emit(QModelIndex())


def test_the_state_carries_the_header_and_restores_it_with_its_sort(qtbot: QtBot, browser: TableBrowser) -> None:
    """Widths, order and the sort a reader set come back in another browser built from the state.

    **Test steps:**

    * widen a column and sort by title descending, then take the state
    * build a second browser from it
    * verify its column width, sort indicator and that its model sorts the same way
    """
    browser.view.horizontalHeader().resizeSection(0, 233)
    browser.view.sortByColumn(TITLE_COLUMN, Qt.SortOrder.DescendingOrder)

    restored = TableBrowser(browser.state())
    qtbot.addWidget(restored)

    header = restored.view.horizontalHeader()
    assert header.sectionSize(0) == 233
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (TITLE_COLUMN, Qt.SortOrder.DescendingOrder)
    restored.set_rows([row("a", 1, "Alpha"), row("b", 1, "Beta")], {ROOT_ID: ROOT_PATH})
    assert restored.model.index(0, TITLE_COLUMN).data() == "Beta"


def test_a_clone_state_keeps_the_filter_and_columns_under_a_new_id_and_name(browser: TableBrowser) -> None:
    """A copy is the same view of the rows, not the same browser.

    **Test steps:**

    * widen a column and ask for a clone state named "Copy"
    * verify the new id and name, and the same filter and header state
    """
    browser.view.horizontalHeader().resizeSection(0, 233)

    clone = browser.clone_state("Copy")

    assert clone.browser_id != browser.browser_id
    assert (clone.name, clone.filter, clone.columns) == ("Copy", browser.filter_text, browser.state().columns)


def test_renaming_a_browser_shows_in_its_state(browser: TableBrowser) -> None:
    """The name a browser is remembered by is the one it was last given.

    **Test steps:**

    * set a new name
    * verify the state carries it
    """
    browser.name = "Everything"

    assert browser.state().name == "Everything"
