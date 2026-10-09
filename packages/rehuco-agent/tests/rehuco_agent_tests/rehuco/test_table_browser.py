"""Tests for the table browser: a catalog's rows as a table under a filter line, with a status line and a state worth
remembering (#396, #398, #379)."""

from collections.abc import Iterator
from dataclasses import replace
from itertools import count
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, QModelIndex, QPoint, Qt
from PySide6.QtGui import QAction, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView
from pytest import MonkeyPatch, fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import TableBrowser, table_browser
from rehuco_agent.rehuco.browser_presets import BrowserPreset, browser_presets
from rehuco_agent.rehuco.catalog_delegates import DurationDelegate, SizeDelegate
from rehuco_agent.rehuco.catalog_table_model import DEFAULT_HIDDEN, CatalogColumn
from rehuco_agent.rehuco.table_browser import FILTER_HELP, FILTER_SETTLE_MS, PROBLEMS_ACTION_NAME
from rehuco_agent.settings.catalog_state_store import TABLE_BROWSER_KIND, BrowserState
from rehuco_core import CatalogField, CatalogQuery, CatalogRecord, CatalogRow, RecordKind
from shiboken6 import invalidate

ROOT_ID = uuid4()
ROOT_PATH = Path("/fake/root")

ids: Iterator[int] = count(10_000)
"""Every row :func:`row` builds has an id of its own, as the cache's rows do -- far above any a test gives."""


def row(path: str, size: int, title: str = "", resource_id: int | None = None) -> CatalogRow:
    """A cache row for one ``.rehu`` of ``size`` bytes under the test root.

    :param path: the record's path under the root.
    :param size: its size.
    :param title: its title.
    :param resource_id: its id; a fresh one when omitted.
    :returns: the row.
    """
    record = CatalogRecord(path, RecordKind.REHU, title=title or path, type="tutorial", current_size=size)
    return CatalogRow(
        resource_id=next(ids) if resource_id is None else resource_id,
        root_id=ROOT_ID,
        root_label="root",
        record=record,
        scanned_at=0.0,
    )


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
    assert browser.status_line.full_text == "No resources"


def test_the_status_line_counts_the_rows_and_adds_up_their_sizes(browser: TableBrowser) -> None:
    """The count follows the rows shown, with the singular spelled right.

    **Test steps:**

    * show one 1.5 KiB row and then a second of 2 KiB
    * verify ``1 resource / 1.5K`` and then ``2 resources / 3.5K``
    """
    browser.set_rows([row("a/info.rehu", 1536)], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "1 resource / 1.5K"

    browser.set_rows([row("a/info.rehu", 1536), row("b/info.rehu", 2048)], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "2 resources / 3.5K"


def test_the_status_line_says_when_a_total_is_partial(browser: TableBrowser) -> None:
    """A total never silently understates: it names the rows it left out, and says nothing when none is missing.

    **Test steps:**

    * show a sized tutorial, a legacy ``.tc``, a measured pack and an unmeasured one
    * verify the legacy count and the image total's ``unmeasured`` parenthesis
    * show only measured rows, and verify the parentheses are gone
    * show only an empty pack, and verify ``0 images`` is still said
    """
    sized = row("a/info.rehu", 1536)
    unsized = CatalogRow(1, ROOT_ID, "root", CatalogRecord("b/info.tc", RecordKind.TC, type="tutorial"), 0.0)
    pack = CatalogRecord("c.rehu", RecordKind.REHU, type="reference_images", current_size=512, current_count=1)
    unmeasured = CatalogRecord("d.rehu", RecordKind.REHU, type="reference_images", current_size=512)
    packs = [CatalogRow(1, ROOT_ID, "root", entry, 0.0) for entry in (pack, unmeasured)]

    browser.set_rows([sized, unsized, *packs], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "4 resources / 1 legacy .tc / 2.5K / 1 image (1 unmeasured)"

    browser.set_rows([sized, packs[0]], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "2 resources / 2.0K / 1 image"

    empty = CatalogRecord("e.rehu", RecordKind.REHU, type="reference_images", current_size=0, current_count=0)
    browser.set_rows([CatalogRow(1, ROOT_ID, "root", empty, 0.0)], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "1 resource / 0B / 0 images"

    many = CatalogRecord("f.rehu", RecordKind.REHU, type="reference_images", current_size=0, current_count=18400)
    browser.set_rows([CatalogRow(1, ROOT_ID, "root", many, 0.0)], {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "1 resource / 0B / 18,400 images"

    legacy = CatalogRecord("g.tc", RecordKind.TC, type="reference_images")
    rows = [CatalogRow(1, ROOT_ID, "root", legacy, 0.0)] * 1188 + [row("h/info.rehu", 0)] * 52
    browser.set_rows(rows, {ROOT_ID: ROOT_PATH})
    assert browser.status_line.full_text == "1,240 resources / 1,188 legacy .tc / 0B"


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
    browser.view.sortByColumn(CatalogColumn.TITLE, Qt.SortOrder.DescendingOrder)

    restored = TableBrowser(browser.state())
    qtbot.addWidget(restored)

    header = restored.view.horizontalHeader()
    assert header.sectionSize(0) == 233
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        CatalogColumn.TITLE,
        Qt.SortOrder.DescendingOrder,
    )
    restored.set_rows([row("a", 1, "Alpha"), row("b", 1, "Beta")], {ROOT_ID: ROOT_PATH})
    assert restored.model.index(0, CatalogColumn.TITLE).data() == "Beta"


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


def test_a_size_reads_short_while_the_cell_keeps_its_bytes(browser: TableBrowser) -> None:
    """The model holds the bytes; the column's delegate says them in short form, and a duration as a field would.

    **Test steps:**

    * show a row of 1,024 bytes
    * verify the cell holds the number and the size and duration columns' delegates word it
    """
    browser.set_rows([row("a/info.rehu", 1024)], {ROOT_ID: ROOT_PATH})
    index = browser.model.index(0, CatalogColumn.SIZE)
    view = browser.view
    locale = view.locale()

    sizes = view.itemDelegateForColumn(CatalogColumn.SIZE)
    durations = view.itemDelegateForColumn(CatalogColumn.CURRENT_DURATION)
    assert isinstance(sizes, SizeDelegate) and isinstance(durations, DurationDelegate)

    assert index.data() == 1024
    assert sizes.displayText(index.data(), locale) == "1.0K"
    assert durations.displayText(8100, locale) == "2h 15m"
    assert sizes.displayText("text", locale) == "text"
    assert durations.displayText(None, locale) == ""


def test_renaming_a_browser_shows_in_its_state(browser: TableBrowser) -> None:
    """The name a browser is remembered by is the one it was last given.

    **Test steps:**

    * set a new name
    * verify the state carries it
    """
    browser.name = "Everything"

    assert browser.state().name == "Everything"


# region the columns


def hidden_columns(browser: TableBrowser) -> set[CatalogColumn]:
    """Which columns the browser's header hides.

    :param browser: the browser.
    :returns: the hidden columns.
    """
    header = browser.view.horizontalHeader()
    return {column for column in CatalogColumn if header.isSectionHidden(column)}


def set_column_shown(browser: TableBrowser, title: str, shown: bool) -> None:
    """Check or uncheck one column in the header's own menu, as a reader would.

    :param browser: the browser.
    :param title: the column's header.
    :param shown: whether to show it.
    """
    menu = browser.sections_menu.build_menu()
    action = next(action for action in menu.actions() if action.text() == title)
    action.setChecked(shown)
    menu.deleteLater()


def test_a_plain_browser_starts_with_the_common_columns(browser: TableBrowser) -> None:
    """The URL and the type-specific columns start hidden; a preset shows those (#400).

    **Test steps:**

    * read which columns a new browser hides
    * verify exactly the default hidden ones
    """
    assert hidden_columns(browser) == DEFAULT_HIDDEN


def test_the_header_menu_alone_chooses_the_columns_and_the_state_keeps_them(
    qtbot: QtBot, browser: TableBrowser
) -> None:
    """Toggling a column never touches the filter line; the header state round-trips the choice, and a clone copies it.

    **Test steps:**

    * type some free text, hide Path and show URL from the header menu
    * verify the line is unchanged and no rows were asked for
    * build a browser from the state and another from a clone state
    * verify both hide the same columns
    """
    browser.set_filter_text("intro")

    with qtbot.assertNotEmitted(browser.query_changed):
        set_column_shown(browser, "Path", False)
        set_column_shown(browser, "URL", True)

    assert browser.filter_text == browser.filter_edit.text() == "intro"
    expected = (DEFAULT_HIDDEN - {CatalogColumn.URL}) | {CatalogColumn.PATH}
    assert hidden_columns(browser) == expected
    for state in (browser.state(), browser.clone_state("Copy")):
        copy = TableBrowser(state)
        qtbot.addWidget(copy)
        assert hidden_columns(copy) == expected


def test_a_browser_from_a_preset_takes_its_name_columns_and_filter(qtbot: QtBot) -> None:
    """A preset sets the name, the header's hidden columns and the line -- and the query read from it (#400).

    **Test steps:**

    * build a browser from a preset hiding Title and filtering by type
    * verify its name, hidden columns, line and query
    """
    preset = BrowserPreset("Tutorial Columns", "Tutorial", frozenset({CatalogColumn.TITLE}), "type:tutorial")

    browser = TableBrowser(preset=preset)
    qtbot.addWidget(browser)

    assert browser.name == "Tutorial"
    assert hidden_columns(browser) == {CatalogColumn.TITLE}
    assert browser.filter_edit.text() == browser.filter_text == "type:tutorial"
    assert browser.query == CatalogQuery((), ((CatalogField.TYPE, "tutorial"),))


def test_a_browser_from_a_preset_is_remembered_and_cloned_like_any_other(qtbot: QtBot) -> None:
    """Its state and a clone's carry the preset's columns and line; nothing of the preset itself is kept (#400).

    **Test steps:**

    * build a browser from each built-in preset
    * rebuild one browser from its state and another from a clone state
    * verify both hide the preset's columns and read the preset's line
    """
    for preset in browser_presets():
        browser = TableBrowser(preset=preset)
        qtbot.addWidget(browser)
        for state in (browser.state(), browser.clone_state("Copy")):
            copy = TableBrowser(state)
            qtbot.addWidget(copy)
            assert hidden_columns(copy) == preset.hidden
            assert copy.filter_text == preset.filter


def test_a_remembered_columns_word_is_dropped_on_load_without_a_problem(qtbot: QtBot) -> None:
    """A line an older build saved with a ``columns:`` word loses it, and the header state alone says what shows.

    **Test steps:**

    * build a browser from a state whose filter names a type and two columns
    * verify the line and the query keep the type only, no problem is reported, and the columns are the defaults
    """
    state = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials", "type:tutorial columns:title,path")
    browser = TableBrowser(state)
    qtbot.addWidget(browser)

    assert browser.filter_edit.text() == browser.filter_text == "type:tutorial"
    assert browser.query == CatalogQuery((), ((CatalogField.TYPE, "tutorial"),))
    assert not browser.filter_problems
    assert hidden_columns(browser) == DEFAULT_HIDDEN
    assert browser.state().filter == "type:tutorial"


def test_a_header_saved_before_the_later_columns_existed_keeps_them_at_their_defaults(qtbot: QtBot) -> None:
    """A state covering only #377's four columns applies to those four; Qt would show the rest, so the ones a plain
    browser hides are hidden again.

    **Test steps:**

    * save a four-column header with Type hidden and Title widened
    * build a browser from it
    * verify Type and the default hidden columns are hidden, and the width came back
    """
    old = QTableView()
    qtbot.addWidget(old)
    old.setModel(QStandardItemModel(0, 4, old))
    old.horizontalHeader().setSectionHidden(CatalogColumn.TYPE, True)
    old.horizontalHeader().resizeSection(CatalogColumn.TITLE, 321)
    saved = bytes(old.horizontalHeader().saveState().data())

    browser = TableBrowser(BrowserState(uuid4(), TABLE_BROWSER_KIND, "Old", "", saved))
    qtbot.addWidget(browser)

    assert TableBrowser.saved_column_count(saved) == 4
    assert hidden_columns(browser) == DEFAULT_HIDDEN | {CatalogColumn.TYPE}
    assert browser.view.horizontalHeader().sectionSize(CatalogColumn.TITLE) == 321


def test_a_header_state_the_header_refuses_leaves_the_defaults(qtbot: QtBot) -> None:
    """Bytes that are no header state cost the reader their layout, never the defaults.

    **Test steps:**

    * build a browser from a state holding junk header bytes
    * verify the default columns are hidden
    """
    browser = TableBrowser(BrowserState(uuid4(), TABLE_BROWSER_KIND, "Junk", "", b"junk"))
    qtbot.addWidget(browser)

    assert TableBrowser.saved_column_count(b"junk") == 0
    assert hidden_columns(browser) == DEFAULT_HIDDEN


# endregion

# region the selection's stats


def test_the_status_line_adds_the_selection_after_the_totals(browser: TableBrowser) -> None:
    """Nothing selected says nothing; a selection adds up as the totals would over those rows alone.

    **Test steps:**

    * show a sized row, a legacy ``.tc`` and a pack of images
    * verify no selection part, then one row, then the ``.tc`` with the pack, then every row
    """
    legacy = CatalogRecord("b/info.tc", RecordKind.TC, type="reference_images")
    pack = CatalogRecord("c.rehu", RecordKind.REHU, type="reference_images", current_size=1024, current_count=120)
    rows = [
        row("a/info.rehu", 2048),
        CatalogRow(1, ROOT_ID, "root", legacy, 0.0),
        CatalogRow(2, ROOT_ID, "root", pack, 0.0),
    ]
    browser.set_rows(rows, {ROOT_ID: ROOT_PATH})
    totals = "3 resources / 1 legacy .tc / 3.0K / 120 images"
    assert browser.status_line.full_text == totals

    select(browser, 0)
    assert browser.status_line.full_text == f"{totals} — 1 selected / 2.0K"

    select(browser, 1, 2)
    assert browser.status_line.full_text == f"{totals} — 2 selected / 1 legacy .tc / 1.0K / 120 images"

    browser.view.selectAll()
    assert browser.status_line.full_text == f"{totals} — 3 selected / 1 legacy .tc / 3.0K / 120 images"

    select(browser)
    assert browser.status_line.full_text == totals


def test_the_selection_part_names_the_rows_it_leaves_out(browser: TableBrowser) -> None:
    """A selected unmeasured row is counted in the selection's parenthesis, as in the totals'.

    **Test steps:**

    * show a measured pack and an unmeasured one, and select the second
    * verify its part says ``(1 unmeasured)`` twice
    """
    measured = CatalogRecord("a.rehu", RecordKind.REHU, type="reference_images", current_size=1024, current_count=1)
    unmeasured = CatalogRecord("b.rehu", RecordKind.REHU, type="reference_images")
    browser.set_rows(
        [CatalogRow(1, ROOT_ID, "root", entry, 0.0) for entry in (measured, unmeasured)], {ROOT_ID: ROOT_PATH}
    )

    select(browser, 1)
    assert browser.status_line.full_text.endswith("— 1 selected / 0B (1 unmeasured) / 0 images (1 unmeasured)")


def test_a_selected_row_changed_in_place_updates_the_line_without_a_reset(browser: TableBrowser) -> None:
    """A resize, a rename and a removal reach the selection part, and the selection stays.

    **Test steps:**

    * show two rows with both selected, then resize one in place
    * verify the selection's size, rename it (it moves) and verify it is still counted, then remove the other and
      verify its count
    """
    browser.set_rows(
        [row("a/info.rehu", 1024, resource_id=1), row("b/info.rehu", 1024, resource_id=2)], {ROOT_ID: ROOT_PATH}
    )
    select(browser, 0, 1)

    browser.update_rows({1}, [row("a/info.rehu", 3072, resource_id=1)])
    assert browser.status_line.full_text == "2 resources / 4.0K — 2 selected / 4.0K"

    browser.update_rows({1}, [row("z/info.rehu", 3072, resource_id=1)])
    assert browser.status_line.full_text == "2 resources / 4.0K — 2 selected / 4.0K"

    browser.update_rows({2}, [])
    assert browser.status_line.full_text == "1 resource / 3.0K — 1 selected / 3.0K"


# endregion

# region the current resource


def select(browser: TableBrowser, *rows: int) -> None:
    """Select ``rows`` as a reader would, replacing the selection.

    :param browser: the browser.
    :param rows: the rows to select; none clears it.
    """
    selection = browser.view.selectionModel()
    selection.clearSelection()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row_ in rows:
        selection.select(browser.model.index(row_, 0), flags)


def test_exactly_one_selected_row_is_the_current_resource(qtbot: QtBot, browser: TableBrowser) -> None:
    """One row names its resource by root id and relative path; none or several name none.

    **Test steps:**

    * show two rows, then select one, both, and none
    * verify the resource announced each time, and the property agreeing
    """
    browser.set_rows([row("a/info.rehu", 1), row("b/info.rehu", 1)], {ROOT_ID: ROOT_PATH})

    with qtbot.waitSignal(browser.current_changed) as changed:
        select(browser, 0)
    assert changed.args == [(ROOT_ID, "a/info.rehu")]
    assert browser.current_resource == (ROOT_ID, "a/info.rehu")

    with qtbot.waitSignal(browser.current_changed) as changed:
        select(browser, 0, 1)
    assert changed.args == [None]

    select(browser, 1)
    with qtbot.waitSignal(browser.current_changed) as changed:
        select(browser)
    assert changed.args == [None]
    assert browser.current_resource is None


def test_the_current_resource_follows_its_row_renamed_and_removed_in_place(qtbot: QtBot, browser: TableBrowser) -> None:
    """The selection survives a rename, which changes what the current resource is called; a removal ends it.

    **Test steps:**

    * select a row, then update it in place under a new path
    * verify the row is still selected and the new key announced, with no reset
    * remove it in place
    * verify no resource is current
    """
    browser.set_rows([row("a/info.rehu", 1, resource_id=7), row("b/info.rehu", 1, resource_id=8)], {ROOT_ID: ROOT_PATH})
    select(browser, 0)

    with qtbot.assertNotEmitted(browser.model.modelReset), qtbot.waitSignal(browser.current_changed) as changed:
        browser.update_rows({7}, [row("c/info.rehu", 1, resource_id=7)])
    assert changed.args == [(ROOT_ID, "c/info.rehu")]
    assert browser.view.selectionModel().isRowSelected(browser.model.rowCount() - 1, QModelIndex())

    with qtbot.waitSignal(browser.current_changed) as changed:
        browser.update_rows({7}, [])
    assert changed.args == [None]


def test_an_update_in_place_keeps_the_status_line_current(browser: TableBrowser) -> None:
    """The totals follow an update in place as they follow a reset.

    **Test steps:**

    * show one row, then update it with a new size and insert another
    * verify the status line counts both and adds the new sizes
    """
    browser.set_rows([row("a/info.rehu", 1024, resource_id=1)], {ROOT_ID: ROOT_PATH})

    browser.update_rows({1, 2}, [row("a/info.rehu", 2048, resource_id=1), row("b/info.rehu", 1024, resource_id=2)])

    assert browser.status_line.full_text == "2 resources / 3.0K"


# endregion

# region the filter line


def test_typing_applies_the_filter_once_the_text_settles(qtbot: QtBot, browser: TableBrowser) -> None:
    """The rows are asked for once per pause in typing, not once per keystroke.

    **Test steps:**

    * type a token into the line
    * verify the query is unchanged right after, then changes once, carrying the token
    """
    with qtbot.waitSignal(browser.query_changed, timeout=FILTER_SETTLE_MS * 10) as changed:
        qtbot.keyClicks(browser.filter_edit, "type:tutorial")
        assert browser.query == CatalogQuery()
    assert changed.args == [CatalogQuery((), ((CatalogField.TYPE, "tutorial"),))]
    assert browser.filter_text == "type:tutorial"


def test_enter_applies_the_filter_without_waiting(qtbot: QtBot, browser: TableBrowser) -> None:
    """Enter is the reader saying they are done typing.

    **Test steps:**

    * type a word and press Enter
    * verify the query carries it at once
    """
    qtbot.keyClicks(browser.filter_edit, "blender")
    qtbot.keyClick(browser.filter_edit, Qt.Key.Key_Return)

    assert browser.query == CatalogQuery(("blender",))


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


def test_a_browser_built_from_a_state_applies_its_filter(qtbot: QtBot) -> None:
    """A remembered filter is applied, not only shown.

    **Test steps:**

    * build a browser from a state whose filter names a type
    * verify the line and the query
    """
    state = BrowserState(uuid4(), TABLE_BROWSER_KIND, "Tutorials", "type:tutorial")
    browser = TableBrowser(state)
    qtbot.addWidget(browser)

    assert browser.filter_edit.text() == state.filter
    assert browser.query == CatalogQuery((), ((CatalogField.TYPE, "tutorial"),))


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
    assert browser.query == CatalogQuery(("intro",), ((CatalogField.AUTHORS, "Foo Bar"),))


# endregion


# region Author menu


def authored_row(path: str, *authors: str) -> CatalogRow:
    """A cache row whose record lists ``authors``.

    :param path: the record's path under the root.
    :param authors: its authors, in order.
    :returns: the row.
    """
    plain = row(path, 1)
    return CatalogRow(plain.resource_id, plain.root_id, plain.root_label, replace(plain.record, authors=authors), 0.0)


def right_click(
    browser: TableBrowser, column: CatalogColumn, monkeypatch: MonkeyPatch, row_number: int = 0
) -> list[QAction]:
    """Right-click a cell and return the actions of the menu it opened, empty if none opened.

    :param browser: the browser, already holding rows.
    :param column: the clicked column.
    :param monkeypatch: swaps the browser's menu for one that runs no modal loop.
    :param row_number: the clicked row.
    :returns: the menu's actions as they stood when it would have shown.
    """
    opened: list[list[QAction]] = []

    class RecordingMenu(QMenu):
        """Reports its actions instead of running a modal loop, which a patched ``QMenu.exec`` would not prevent."""

        def exec(self, *_args: object) -> None:  # type: ignore[override]
            """Record what would have been shown."""
            opened.append(self.actions())

    monkeypatch.setattr(table_browser, "QMenu", RecordingMenu)
    view = browser.view
    index = browser.model.index(row_number, column)
    view.customContextMenuRequested.emit(view.visualRect(index).center())
    return opened[0] if opened else []


def test_a_row_out_of_range_has_no_authors(browser: TableBrowser) -> None:
    """The model answers for a row it lacks with nothing, as its other per-row reads do.

    **Test steps:**

    * ask an empty model, and a model of one row, for authors out of range
    * verify none, and the row's own authors in range
    """
    assert browser.model.authors_of(0) == ()
    browser.set_rows([authored_row("a.rehu", "Ann")], {ROOT_ID: ROOT_PATH})

    assert browser.model.authors_of(1) == ()
    assert browser.model.authors_of(0) == ("Ann",)


def test_an_authors_cell_offers_one_entry_per_author_in_the_records_order(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The names come from the record, not from splitting the cell's text.

    **Test steps:**

    * show a row whose author names contain a comma and spaces
    * right-click its Authors cell
    * verify one entry per author, in order
    """
    browser.set_rows([authored_row("a.rehu", "Doe, Jane", "Bob")], {ROOT_ID: ROOT_PATH})

    actions = right_click(browser, CatalogColumn.AUTHORS, monkeypatch)

    assert [action.text() for action in actions] == ["Filter by Doe, Jane", "Filter by Bob"]


def test_choosing_an_author_sets_that_field_only_and_keeps_the_rest_of_the_line(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """An existing authors word is replaced, the free text and other tokens stay, and a name with spaces or quotes
    is quoted so it reads back whole.

    **Test steps:**

    * set a line with free text, a tags token and another author
    * choose an author whose name holds spaces and a quote
    * verify the line and the query
    """
    name = 'Jane "J" Doe'
    browser.set_rows([authored_row("a.rehu", name)], {ROOT_ID: ROOT_PATH})
    browser.set_filter_text("intro tags:python authors:Old")

    actions = right_click(browser, CatalogColumn.AUTHORS, monkeypatch)

    actions[0].trigger()
    assert browser.filter_text == 'intro tags:python authors:"Jane \\"J\\" Doe"'
    assert browser.query == CatalogQuery(("intro",), ((CatalogField.TAGS, "python"), (CatalogField.AUTHORS, name)))


def test_an_author_already_on_the_line_is_offered_to_be_cleared(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The menu also undoes: choosing the applied author drops its word and nothing else.

    **Test steps:**

    * filter by one of a row's two authors, with free text
    * right-click the Authors cell
    * verify that author reads as a clear and the other as a filter, then trigger the clear
    * verify the line keeps only the free text
    """
    browser.set_rows([authored_row("a.rehu", "Ann", "Bob")], {ROOT_ID: ROOT_PATH})
    browser.set_filter_text("intro authors:ann")

    actions = right_click(browser, CatalogColumn.AUTHORS, monkeypatch)

    assert [action.text() for action in actions] == ["Clear the filter by Ann", "Filter by Bob"]
    actions[0].trigger()
    assert browser.filter_text == "intro"


def test_no_menu_opens_on_a_row_without_authors_or_on_another_column(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """Only an Authors cell with something to offer has a menu.

    **Test steps:**

    * show one row with authors and one without
    * right-click the authorless Authors cell, the authored row's Title cell and empty space
    * verify no menu opened, and the line stays empty
    """
    browser.set_rows([authored_row("a.rehu", "Ann"), row("b.rehu", 1)], {ROOT_ID: ROOT_PATH})
    # the second row sorts as the cache gave it, so it is the authorless one

    assert not right_click(browser, CatalogColumn.AUTHORS, monkeypatch, 1)
    assert not right_click(browser, CatalogColumn.TITLE, monkeypatch, 0)
    browser.view.customContextMenuRequested.emit(QPoint(-5, -5))
    assert browser.filter_text == ""


def test_a_menu_whose_exec_fails_is_not_left_behind(
    qtbot: QtBot, browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The menu is the browser's child, so a failed ``exec`` must still delete it (#459).

    **Test steps:**

    * make the menu's ``exec`` raise, and right-click an Authors cell
    * flush deferred deletes
    * verify the failure surfaced and no menu is left under the browser
    """
    browser.set_rows([authored_row("a.rehu", "Ann")], {ROOT_ID: ROOT_PATH})

    class FailingMenu(QMenu):
        """A real menu whose ``exec`` raises."""

        def exec(self, *_args: object) -> None:  # type: ignore[override]
            """Fail as a broken popup would."""
            raise RuntimeError("boom")

    monkeypatch.setattr(table_browser, "QMenu", FailingMenu)
    index = browser.model.index(0, CatalogColumn.AUTHORS)
    with qtbot.capture_exceptions() as raised:
        browser.view.customContextMenuRequested.emit(browser.view.visualRect(index).center())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert [type(error) for _, error, _ in raised] == [RuntimeError]
    assert browser.findChildren(QMenu) == []


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


def test_clearing_the_line_asks_for_all_rows_though_the_problem_markers_wrapper_died(
    qtbot: QtBot, browser: TableBrowser
) -> None:
    """The wrapper of the line's problem marker can be invalidated while the marker lives (#459); applying the text
    used to raise there, before the rows were asked for, so a cleared line kept the filtered rows on screen. The rows
    are asked for first, and the marker is found again on the line.

    **Test steps:**

    * apply a token, then invalidate the wrapper of every action on the line
    * clear the line
    * verify the query goes back to matching everything, and a problem is still marked on the marker
    """
    browser.set_filter_text("type:tutorial")
    for action in browser.filter_edit.actions():
        invalidate(action)

    with qtbot.waitSignal(browser.query_changed, timeout=FILTER_SETTLE_MS * 10) as changed:
        browser.filter_edit.clear()
    assert changed.args == [CatalogQuery()]

    browser.set_filter_text("nonsense:value")
    marker = next(action for action in browser.filter_edit.actions() if action.objectName() == PROBLEMS_ACTION_NAME)
    assert marker.toolTip() == "\n".join(browser.filter_problems) != ""


def test_a_problem_is_still_reported_in_the_tooltip_when_the_marker_is_gone(browser: TableBrowser) -> None:
    """The filter line's own tooltip says what could not be applied, with or without its marker.

    **Test steps:**

    * remove the problem marker from the line and apply a token it cannot
    * verify the line's tooltip names the problem
    """
    for action in browser.filter_edit.actions():
        if action.objectName() == PROBLEMS_ACTION_NAME:
            browser.filter_edit.removeAction(action)

    browser.set_filter_text("nonsense:value")

    problems = "\n".join(browser.filter_problems)
    assert problems
    assert problems in browser.filter_edit.toolTip()
