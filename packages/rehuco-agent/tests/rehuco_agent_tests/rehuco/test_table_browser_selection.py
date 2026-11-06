"""Tests for a table browser's selection across a restart ([[plugins#session-restore]], #576)."""

from uuid import uuid4

from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState

from .test_table_browser import ROOT_ID, row


def selection_browser(qtbot: QtBot, keys: tuple[str, ...]) -> tuple[TableBrowser, list[object]]:
    """A browser remembering a selection, and a list of what it announces.

    :param qtbot: the test's bot.
    :param keys: the selected rows' paths.
    :returns: the browser and what it has announced.
    """
    state = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Remembered", selection=tuple((ROOT_ID, key) for key in keys))
    browser = TableBrowser(state)
    qtbot.addWidget(browser)
    announced: list[object] = []
    browser.current_changed.connect(announced.append)
    return browser, announced


def test_a_remembered_row_is_selected_with_the_first_read_of_every_row_and_nothing_follows_it(qtbot: QtBot) -> None:
    """The selection waits for the rows and comes back silently: it must not retarget the preview.

    **Test steps:**

    * build a browser remembering a row, and show it a filter's rows, which are not every row
    * verify nothing is selected and the state still says the remembered row
    * show it every row, and verify the row is selected and current, and nothing was announced
    """
    browser, announced = selection_browser(qtbot, ("b.rehu",))
    rows = [row("a.rehu", 1), row("b.rehu", 2)]

    browser.set_rows(rows[:1], [ROOT_ID])

    assert browser.current_resource is None
    assert browser.state().selection == ((ROOT_ID, "b.rehu"),)

    browser.set_rows(rows, [ROOT_ID], catalog={entry.resource_id for entry in rows})

    assert browser.current_resource == (ROOT_ID, "b.rehu")
    assert not announced


def test_several_remembered_rows_come_back_selected(qtbot: QtBot) -> None:
    """A selection of several rows is a selection of several rows again, and names no current resource.

    **Test steps:**

    * remember two rows of three, and show every row
    * verify exactly those are selected and the state says so
    """
    browser, _ = selection_browser(qtbot, ("a.rehu", "c.rehu"))
    rows = [row("a.rehu", 1), row("b.rehu", 2), row("c.rehu", 3)]

    browser.set_rows(rows, [ROOT_ID], catalog={entry.resource_id for entry in rows})

    assert [index.row() for index in browser.view.selectionModel().selectedRows()] == [0, 2]
    assert browser.state().selection == ((ROOT_ID, "a.rehu"), (ROOT_ID, "c.rehu"))
    assert browser.current_resource is None


def test_a_remembered_row_that_is_gone_selects_nothing_and_is_let_go(qtbot: QtBot) -> None:
    """A row no longer in the catalog restores nothing, and is not remembered for ever.

    **Test steps:**

    * remember a row no read holds, and show every row
    * verify nothing is selected and the state remembers nothing
    """
    browser, _ = selection_browser(qtbot, ("gone.rehu",))
    rows = [row("a.rehu", 1)]

    browser.set_rows(rows, [ROOT_ID], catalog={entry.resource_id for entry in rows})

    assert not browser.view.selectionModel().selectedRows()
    assert not browser.state().selection


def test_the_readers_selection_overtakes_the_one_remembered(qtbot: QtBot) -> None:
    """A row selected before every row is read wins, and is announced as any selection is.

    **Test steps:**

    * remember one row, and show a filter's rows holding another
    * select that one, and verify it is announced
    * show every row, and verify the remembered row was not selected over it
    """
    browser, announced = selection_browser(qtbot, ("b.rehu",))
    rows = [row("a.rehu", 1), row("b.rehu", 2)]
    browser.set_rows(rows, [ROOT_ID])

    browser.view.selectRow(0)
    assert announced == [(ROOT_ID, "a.rehu")]

    browser.set_rows(rows, [ROOT_ID], catalog={entry.resource_id for entry in rows})

    assert browser.state().selection != ((ROOT_ID, "b.rehu"),)


def test_an_empty_first_read_keeps_the_remembered_rows_for_the_next(qtbot: QtBot) -> None:
    """A cache still being built answers no rows: that says nothing about the rows remembered, which wait.

    **Test steps:**

    * remember a row, and show a full read of no rows
    * verify the state still remembers it
    * show a full read holding it, and verify it is selected
    """
    browser, _ = selection_browser(qtbot, ("b.rehu",))

    browser.set_rows([], [ROOT_ID], catalog=set())

    assert browser.state().selection == ((ROOT_ID, "b.rehu"),)

    rows = [row("b.rehu", 2)]
    browser.set_rows(rows, [ROOT_ID], catalog={entry.resource_id for entry in rows})

    assert browser.current_resource == (ROOT_ID, "b.rehu")
