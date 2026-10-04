"""Tests for the table browser: a catalog's rows as a table under a filter line, with a status line and a state worth
remembering (#396, #398)."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser
from rehuco_agent.rehuco.catalog_table_model import COLUMN_IDS, TITLE_COLUMN
from rehuco_agent.rehuco.table_browser import FILTER_HELP, FILTER_SETTLE_MS
from rehuco_agent.settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from rehuco_core import CatalogField, CatalogQuery, CatalogRecord, CatalogRow, RecordKind

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


# region the filter line


def hidden_columns(browser: TableBrowser) -> list[str]:
    """Which columns the browser's header hides.

    :param browser: the browser.
    :returns: their ids, in column order.
    """
    header = browser.view.horizontalHeader()
    return [column for section, column in enumerate(COLUMN_IDS) if header.isSectionHidden(section)]


def set_column_shown(browser: TableBrowser, column: str, shown: bool) -> None:
    """Check or uncheck one column in the header's own menu, as a reader would.

    :param browser: the browser.
    :param column: the column's id.
    :param shown: whether to show it.
    """
    menu = browser.sections_menu.build_menu()
    action = next(action for action in menu.actions() if action.text().lower() == column)
    action.setChecked(shown)
    menu.deleteLater()


def test_typing_applies_the_filter_once_the_text_settles(qtbot: QtBot, browser: TableBrowser) -> None:
    """The rows are asked for once per pause in typing, not once per keystroke.

    **Test steps:**

    * type a token into the line
    * verify the query is unchanged right after, then changes once, carrying the token
    """
    with qtbot.waitSignal(browser.query_changed, timeout=FILTER_SETTLE_MS * 10) as changed:
        qtbot.keyClicks(browser.filter_edit, "type:tutorial")
        assert browser.query == CatalogQuery()
    assert changed.args == [CatalogQuery("", ((CatalogField.TYPE, "tutorial"),))]
    assert browser.filter_text == "type:tutorial"


def test_enter_applies_the_filter_without_waiting(qtbot: QtBot, browser: TableBrowser) -> None:
    """Enter is the reader saying they are done typing.

    **Test steps:**

    * type a word and press Enter
    * verify the query carries it at once
    """
    qtbot.keyClicks(browser.filter_edit, "blender")
    qtbot.keyClick(browser.filter_edit, Qt.Key.Key_Return)

    assert browser.query == CatalogQuery("blender")


def test_a_change_of_columns_alone_asks_for_no_rows(qtbot: QtBot, browser: TableBrowser) -> None:
    """Showing other columns reads nothing again.

    **Test steps:**

    * set a line that only names columns
    * verify no query change was announced
    """
    with qtbot.assertNotEmitted(browser.query_changed):
        browser.set_filter_text("columns:title")


def test_the_columns_token_shows_the_columns_it_names_and_hides_the_rest(browser: TableBrowser) -> None:
    """One string says which columns show.

    **Test steps:**

    * name two columns on the line
    * verify the other two are hidden
    * take the token away by naming all four
    * verify none is hidden
    """
    browser.set_filter_text("columns:authors,title")
    assert hidden_columns(browser) == ["type", "path"]

    browser.set_filter_text("columns:authors,title,type,path")
    assert not hidden_columns(browser)


def test_hiding_a_column_from_the_header_menu_writes_the_columns_token(browser: TableBrowser) -> None:
    """The header menu and the token stay in step: the line always says which columns show.

    **Test steps:**

    * type some free text, then uncheck Path in the header menu
    * verify the line keeps the text and gains a token naming the three shown columns
    * check Path again
    * verify the token is gone, every column showing
    """
    browser.set_filter_text("intro")

    set_column_shown(browser, "path", False)
    assert browser.filter_text == "intro columns:authors,title,type"
    assert hidden_columns(browser) == ["path"]

    set_column_shown(browser, "path", True)
    assert browser.filter_text == "intro"
    assert not hidden_columns(browser)


def test_every_column_shown_again_with_no_columns_token_leaves_the_line_alone(browser: TableBrowser) -> None:
    """With nothing on the line to take back, showing every column writes nothing.

    **Test steps:**

    * type some free text and hide a column on the header directly, so no token says so
    * restore a header state showing every column through the header's menu
    * verify the line is unchanged and every column shows
    """
    browser.set_filter_text("intro")
    every_column = browser.sections_menu.save_state()
    browser.view.horizontalHeader().setSectionHidden(0, True)

    browser.sections_menu.restore_state(every_column)

    assert browser.filter_edit.text() == "intro"
    assert not hidden_columns(browser)


def test_an_unknown_field_is_reported_on_the_line(browser: TableBrowser) -> None:
    """What the line cannot apply is shown on it, and nothing once it can apply it all.

    **Test steps:**

    * set a line with an unknown field
    * verify the problem is reported, by a visible warning action and the line's tooltip
    * set a line it can apply
    * verify the warning is gone and the tooltip is the grammar alone
    """
    browser.set_filter_text("colour:red")

    assert browser.filter_problems == ('Unknown field "colour"',)
    warning = next(action for action in browser.filter_edit.actions() if action.toolTip() == 'Unknown field "colour"')
    assert warning.isVisible()
    assert browser.filter_edit.toolTip().startswith('Unknown field "colour"\n\n')

    browser.set_filter_text("type:tutorial")

    assert not warning.isVisible()
    assert browser.filter_edit.toolTip() == FILTER_HELP


def test_a_browser_built_from_a_state_applies_its_filter_and_columns(qtbot: QtBot) -> None:
    """A remembered filter is applied, not only shown.

    **Test steps:**

    * build a browser from a state whose filter names a type and two columns
    * verify the line, the query and the hidden columns
    """
    state = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials", "type:tutorial columns:title,path")
    browser = TableBrowser(state)
    qtbot.addWidget(browser)

    assert browser.filter_edit.text() == state.filter
    assert browser.query == CatalogQuery("", ((CatalogField.TYPE, "tutorial"),))
    assert hidden_columns(browser) == ["authors", "type"]


def test_the_state_and_a_clone_carry_the_line_as_typed(qtbot: QtBot, browser: TableBrowser) -> None:
    """What is on the line when the catalog is left is what comes back, settled or not.

    **Test steps:**

    * type a token without waiting for it to settle
    * verify the state and a clone state both carry it
    """
    qtbot.keyClicks(browser.filter_edit, "tags:python")

    assert browser.state().filter == "tags:python"
    assert browser.clone_state("Copy").filter == "tags:python"


def test_setting_a_token_replaces_its_field_on_the_line_and_applies_it(browser: TableBrowser) -> None:
    """What a click-to-filter link does to a browser.

    **Test steps:**

    * set a line with free text and an authors token
    * set another author
    * verify the line and the query carry the new author only, the text kept
    """
    browser.set_filter_text("intro authors:Old")

    browser.set_token("authors", "Foo Bar")

    assert browser.filter_text == 'intro authors:"Foo Bar"'
    assert browser.query == CatalogQuery("intro", ((CatalogField.AUTHORS, "Foo Bar"),))


# endregion


def test_clearing_the_line_applies_once_it_settles(qtbot: QtBot, browser: TableBrowser) -> None:
    """A clear button empties the line without a keystroke, and the rows still follow.

    **Test steps:**

    * apply a token, then clear the line the way a clear button does
    * verify the query goes back to matching everything once the text settles
    """
    browser.set_filter_text("type:tutorial")

    with qtbot.waitSignal(browser.query_changed, timeout=FILTER_SETTLE_MS * 10) as changed:
        browser.filter_edit.clear()
    assert changed.args == [CatalogQuery()]
