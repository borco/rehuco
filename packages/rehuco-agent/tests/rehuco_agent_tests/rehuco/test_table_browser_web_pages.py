"""Tests for a table browser's *Open in Web Browser* entry (#679): which pages it opens, and when it asks first."""

from dataclasses import replace

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytest_mock import MockerFixture
from rehuco_agent.rehuco import TableBrowser, web_pages
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.table_browser import OPEN_PAGES_TEXT
from rehuco_agent.rehuco.web_pages import PAGES_WITHOUT_ASKING, confirm_open_pages
from rehuco_core import CatalogRow

from .test_table_browser import (  # noqa: F401  # pylint: disable=unused-import
    ROOT_ID,
    fixture_browser,
    right_click,
    row,
    select,
)


def row_with_url(path: str, url: str) -> CatalogRow:
    """A cache row whose record has ``url`` as its primary source's.

    :param path: the record's path under the root.
    :param url: its URL.
    :returns: the row.
    """
    plain = row(path, 1)
    return CatalogRow(plain.resource_id, plain.root_id, plain.root_label, replace(plain.record, url=url), 0.0)


def open_entry(browser: TableBrowser, monkeypatch: MonkeyPatch) -> QAction:
    """The *Open in Web Browser* entry of the menu a right-click on the first row opens.

    :param browser: the browser, with its rows shown and selected.
    :param monkeypatch: swaps the browser's menu for one that runs no modal loop.
    :returns: the entry.
    """
    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)
    return next(action for action in actions if action.text() == OPEN_PAGES_TEXT)


def test_the_selected_records_pages_open_in_the_tables_order_each_once(
    browser: TableBrowser, monkeypatch: MonkeyPatch, mocker: MockerFixture
) -> None:
    """The pages follow the table, not the order of the selection, and a page two records share opens once.

    **Test steps:**

    * show four records, two with the same page, and select the third, then the first, then the second
    * choose the entry
    * verify each distinct page was opened once, in the table's order
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    browser.set_rows(
        [
            row_with_url("a.rehu", "https://example.com/a"),
            row_with_url("b.rehu", "https://example.com/b"),
            row_with_url("c.rehu", "https://example.com/a"),
            row_with_url("d.rehu", "https://example.com/d"),
        ],
        [ROOT_ID],
    )
    select(browser, 2, 0, 1)

    open_entry(browser, monkeypatch).trigger()

    assert [call.args[0] for call in opened.call_args_list] == [
        QUrl("https://example.com/a"),
        QUrl("https://example.com/b"),
    ]


def test_a_record_with_no_web_page_adds_none_and_the_entry_is_disabled_when_none_is_left(
    browser: TableBrowser, monkeypatch: MonkeyPatch, mocker: MockerFixture
) -> None:
    """A blank URL, a file address and one with no scheme are skipped.

    **Test steps:**

    * show a record with a page and three without, and select all
    * choose the entry and verify only the one page opened
    * select only the three and verify the entry is disabled
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    browser.set_rows(
        [
            row_with_url("a.rehu", "  https://example.com/a  "),
            row_with_url("b.rehu", ""),
            row_with_url("c.rehu", "file:///C:/Windows/system32/calc.exe"),
            row_with_url("d.rehu", "example.com/d"),
        ],
        [ROOT_ID],
    )
    select(browser, 0, 1, 2, 3)
    entry = open_entry(browser, monkeypatch)
    assert entry.isEnabled()
    entry.trigger()
    opened.assert_called_once_with(QUrl("https://example.com/a"))

    select(browser, 1, 2, 3)
    assert not open_entry(browser, monkeypatch).isEnabled()


def pages_browser(browser: TableBrowser, count: int) -> None:
    """Show ``count`` records, each with a page of its own, and select them all.

    :param browser: the browser.
    :param count: how many records.
    """
    browser.set_rows([row_with_url(f"{n:03}.rehu", f"https://example.com/{n}") for n in range(count)], [ROOT_ID])
    select(browser, *range(count))


def test_up_to_the_limit_the_pages_open_without_asking(
    browser: TableBrowser, monkeypatch: MonkeyPatch, mocker: MockerFixture
) -> None:
    """Ten pages is what opens unasked.

    **Test steps:**

    * select as many records as the limit allows, with no answer ready for a question
    * choose the entry
    * verify every page opened and nothing was asked
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    asked = mocker.patch.object(web_pages, "confirm_open_pages")
    pages_browser(browser, PAGES_WITHOUT_ASKING)

    open_entry(browser, monkeypatch).trigger()

    assert opened.call_count == PAGES_WITHOUT_ASKING
    asked.assert_not_called()


def test_past_the_limit_the_pages_open_only_if_the_reader_agrees(
    browser: TableBrowser, monkeypatch: MonkeyPatch, mocker: MockerFixture
) -> None:
    """One more than the limit asks, and a refusal opens nothing.

    **Test steps:**

    * select one more record than the limit allows, and have the question answered no
    * choose the entry and verify it was asked with the count and nothing opened
    * have it answered yes, choose again and verify every page opened
    """
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    asked = mocker.patch.object(web_pages, "confirm_open_pages", return_value=False)
    count = PAGES_WITHOUT_ASKING + 1
    pages_browser(browser, count)

    open_entry(browser, monkeypatch).trigger()
    asked.assert_called_once_with(browser, count)
    opened.assert_not_called()

    asked.return_value = True
    open_entry(browser, monkeypatch).trigger()
    assert opened.call_count == count


def test_the_question_defaults_to_cancel_and_open_is_a_yes(browser: TableBrowser, mocker: MockerFixture) -> None:
    """Enter on the question does not open a dozen tabs.

    **Test steps:**

    * have the dialog answer Open, then Cancel
    * verify the answers, and that Cancel was the default button
    """
    buttons = QMessageBox.StandardButton
    question = mocker.patch.object(QMessageBox, "question", side_effect=[buttons.Open, buttons.Cancel])

    assert confirm_open_pages(browser, 12)
    assert not confirm_open_pages(browser, 12)

    assert question.call_args.args[2] == "Open 12 pages in the web browser?"
    assert question.call_args.args[-1] == buttons.Cancel


def test_a_row_out_of_range_has_no_url_and_a_stored_url_is_read_without_its_blanks(browser: TableBrowser) -> None:
    """The model answers for a row it lacks with nothing, as its other per-row reads do.

    **Test steps:**

    * ask an empty model for a URL
    * show a row whose URL has blanks around it
    * verify it reads without them, and the row after it reads empty
    """
    assert browser.model.url_of(0) == ""
    browser.set_rows([row_with_url("a.rehu", "  https://example.com/a ")], [ROOT_ID])

    assert browser.model.url_of(0) == "https://example.com/a"
    assert browser.model.url_of(1) == ""
