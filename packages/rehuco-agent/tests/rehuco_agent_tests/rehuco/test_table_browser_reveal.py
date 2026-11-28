"""Tests for a table browser's *Open in Explorer* entry (#720): its text, what it asks for, and when it asks first."""

from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from borco_pyside.file_browser import FILE_BROWSER_NAME
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox
from pytest import LogCaptureFixture, MonkeyPatch
from pytest_mock import MockerFixture
from rehuco_agent.rehuco import TableBrowser, file_reveals
from rehuco_agent.rehuco.catalog_table_model import CatalogColumn
from rehuco_agent.rehuco.file_reveals import OPEN_IN_FILE_BROWSER_TEXT, confirm_open_places, reveal_places
from rehuco_agent.rehuco.table_browser import OPEN_PAGES_TEXT
from rehuco_agent.rehuco.web_pages import PAGES_WITHOUT_ASKING
from rehuco_core import CatalogRow

from .test_table_browser import (  # noqa: F401  # pylint: disable=unused-import
    ROOT_ID,
    fixture_browser,
    right_click,
    row,
    select,
)


def reveal_entry(actions: list[QAction]) -> QAction:
    """The *Open in Explorer* entry among a menu's actions.

    :param actions: the menu's actions.
    :returns: the entry.
    """
    return next(action for action in actions if action.text() == OPEN_IN_FILE_BROWSER_TEXT)


def test_the_entry_is_named_for_the_platforms_file_browser_and_leads_the_page_entry(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """*Open in Explorer*, *Open in Finder* or *Open in file manager*, just before *Open in Web Browser*.

    **Test steps:**

    * show a record, select it and right-click it
    * verify the entry reads as the platform's file browser is named
    * verify it is enabled and sits directly before *Open in Web Browser*
    """
    browser.set_rows([row("a.rehu", 1)], [ROOT_ID])
    select(browser, 0)

    actions = right_click(browser, CatalogColumn.TITLE, monkeypatch)

    entry = reveal_entry(actions)
    assert entry.text() == f"Open in {FILE_BROWSER_NAME}"
    assert entry.isEnabled()
    assert actions[actions.index(entry) + 1].text() == OPEN_PAGES_TEXT


def test_choosing_the_entry_asks_for_the_selected_rows_in_the_tables_order(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """The browser cannot resolve a key to a place, so it names the rows and the dock resolves them.

    **Test steps:**

    * show three records and select the third, then the first
    * choose the entry
    * verify the first and the third were asked for, in the table's order
    """
    browser.set_rows([row("a.rehu", 1), row("b.rehu", 2), row("c.rehu", 3)], [ROOT_ID])
    select(browser, 2, 0)
    asked: list[object] = []
    browser.reveal_requested.connect(asked.append)

    reveal_entry(right_click(browser, CatalogColumn.TITLE, monkeypatch)).trigger()

    assert asked == [((ROOT_ID, "a.rehu"), (ROOT_ID, "c.rehu"))]


def test_the_entry_is_disabled_while_every_selected_row_is_under_a_root_that_cannot_be_reached(
    browser: TableBrowser, monkeypatch: MonkeyPatch
) -> None:
    """A selection with nowhere to open offers nothing to choose; one reachable row is enough.

    **Test steps:**

    * show a record under the test root and one under another root, and mark the test root offline
    * select the offline row alone and verify the entry is disabled
    * select both and verify it is enabled
    """
    other = row("b.rehu", 2)
    elsewhere = UUID(int=1)
    browser.set_rows(
        [row("a.rehu", 1), CatalogRow(other.resource_id, elsewhere, "Other", other.record, 0.0)], [ROOT_ID, elsewhere]
    )
    browser.model.set_offline_roots({ROOT_ID: "share off"})

    select(browser, 0)
    assert not reveal_entry(right_click(browser, CatalogColumn.TITLE, monkeypatch)).isEnabled()

    select(browser, 0, 1)
    assert reveal_entry(right_click(browser, CatalogColumn.TITLE, monkeypatch)).isEnabled()


def test_a_place_that_is_gone_with_its_folder_is_logged(
    browser: TableBrowser, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A record the cache still lists but the disk lost opens nothing, and says so.

    **Test steps:**

    * have the file browser refuse a place
    * reveal it
    * verify the place was named in the log at INFO
    """
    mocker.patch.object(file_reveals, "reveal_in_file_browser", return_value=False)

    with caplog.at_level("INFO"):
        reveal_places(browser, [Path("gone")])

    assert "gone is not opened in the file browser: neither it nor its folder was found" in caplog.text


def places(count: int) -> list[Path]:
    """Places to reveal.

    :param count: how many.
    :returns: that many distinct paths.
    """
    return [Path(f"place{n}") for n in range(count)]


def test_up_to_the_limit_the_places_open_without_asking(browser: TableBrowser, mocker: MockerFixture) -> None:
    """Ten places is what opens unasked.

    **Test steps:**

    * reveal as many places as the limit allows, with no answer ready for a question
    * verify every place was revealed, in order, and nothing was asked
    """
    revealed: Mock = mocker.patch.object(file_reveals, "reveal_in_file_browser")
    asked = mocker.patch.object(file_reveals, "confirm_open_places")
    wanted = places(PAGES_WITHOUT_ASKING)

    reveal_places(browser, wanted)

    assert [call.args[0] for call in revealed.call_args_list] == wanted
    asked.assert_not_called()


def test_past_the_limit_the_places_open_only_if_the_reader_agrees(browser: TableBrowser, mocker: MockerFixture) -> None:
    """One more than the limit asks, and a refusal opens nothing.

    **Test steps:**

    * reveal one more place than the limit allows, with the question answered no
    * verify it was asked with the count and nothing was revealed
    * have it answered yes, reveal again and verify every place was revealed
    """
    revealed: Mock = mocker.patch.object(file_reveals, "reveal_in_file_browser")
    asked = mocker.patch.object(file_reveals, "confirm_open_places", return_value=False)
    wanted = places(PAGES_WITHOUT_ASKING + 1)

    reveal_places(browser, wanted)
    asked.assert_called_once_with(browser, len(wanted))
    revealed.assert_not_called()

    asked.return_value = True
    reveal_places(browser, wanted)
    assert revealed.call_count == len(wanted)


def test_the_question_defaults_to_cancel_and_open_is_a_yes(browser: TableBrowser, mocker: MockerFixture) -> None:
    """Enter on the question does not open a dozen windows.

    **Test steps:**

    * have the dialog answer Open, then Cancel
    * verify the answers, the question's count and that Cancel was the default button
    """
    buttons = QMessageBox.StandardButton
    question = mocker.patch.object(QMessageBox, "question", side_effect=[buttons.Open, buttons.Cancel])

    assert confirm_open_places(browser, 12)
    assert not confirm_open_places(browser, 12)

    assert question.call_args.args[2] == f"Open 12 places in {FILE_BROWSER_NAME}?"
    assert question.call_args.args[-1] == buttons.Cancel
