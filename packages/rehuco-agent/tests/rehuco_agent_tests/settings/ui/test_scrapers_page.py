"""Tests for ScrapersPage: the Scrapers settings category page (#269, #278)."""

import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtWidgets import QMessageBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.settings import scrapers_settings
from rehuco_agent.settings.scrapers_settings import Browser, shared_scrapers_settings
from rehuco_agent.settings.ui import scrapers_page
from rehuco_agent.settings.ui.scrapers_page import ScrapersPage
from rehuco_agent.settings.ui.scrapers_scraper_column_delegate import ScrapersScraperColumnDelegate
from rehuco_agent.settings.ui.scrapers_table_model import SCRAPER_COLUMN
from rehuco_agent.settings.ui.settings_dialog import SettingsDialog
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.web_search_engines_model import ACTIVE_COLUMN, NAME_COLUMN
from rehuco_agent.settings.web_search_settings import (
    DEFAULT_ENGINES,
    SearchEngine,
    WebSearchSettings,
    shared_web_search_settings,
)

HREF_PATTERN = re.compile(r'href="([^"]+)"')

CHOSEN_FOLDER = "/my/scrapers"
TICKED_KEY = "rehuco_user_scrapers.foo.Foo"
TICKED_ROW = ScraperRow(
    key=TICKED_KEY,
    label="Foo",
    publisher="Foo Co",
    site_name="Foo",
    site_url="https://foo.example.com",
    source="foo.py",
    needs_browser=False,
    error=None,
)
GATED_ROW = ScraperRow(
    key="rehuco_user_scrapers.gated.Gated",
    label="Gated",
    publisher="Gated Co",
    site_name="Gated",
    site_url="",
    source="gated.py",
    needs_browser=True,
    error=None,
)


# region fixtures
# Mirrors every other settings-page test's FakeSettings exactly -- kept as a separate copy rather than
# a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API, plus ``fileName`` -- what
    `default_scripts_folder` derives its default from."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        # importing QMessageBox in this module confuses pylint's own inference of this unrelated
        # `self.__data`'s type (dict); harmless
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)

    def fileName(self) -> str:  # noqa: N802
        return "/fake/borco/rehuco-agent.ini"


# pylint: enable=duplicate-code


class FakeRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Stands in for the shared `ScraperRegistry`: fixed rows, and a count of reloads asked for."""

    def __init__(self) -> None:
        self.rows: tuple[ScraperRow, ...] = (TICKED_ROW, GATED_ROW)
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module (used
    by :func:`shared_scrapers_settings`'s lazy load) and the page module itself (used by
    :meth:`ScrapersPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(scrapers_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(scrapers_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def registry(mocker: MockerFixture) -> FakeRegistry:
    """Stand in for the shared registry, so the page scans no real folder.

    :returns: the fake, for asserting on what the page asked of it.
    """
    fake = FakeRegistry()
    mocker.patch.object(scrapers_page, "shared_scraper_registry", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_scrapers_settings.cache_clear()
    yield
    shared_scrapers_settings.cache_clear()


@fixture(autouse=True)
def web_search_save(mocker: MockerFixture) -> Any:
    """Stand in for `WebSearchSettings.save`, whose array writes the fake above does not implement.

    :returns: the mock, for asserting on what the page saved.
    """
    return mocker.patch.object(WebSearchSettings, "save")


def page_ui(page: ScrapersPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_ScrapersPage`` instance.
    """
    return page._ScrapersPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def path_link_href(label: ElidedLabel) -> str:
    """The full (never elided) target of a path link, read off its rendered ``href`` -- the visible
    text may be elided in the small, unshown width a test widget gets, but the link target never is.

    :param label: the `~borco_pyside.widgets.ElidedLabel` to read.
    :returns: the ``href``, or ``""`` if the label carries no link.
    """
    match = HREF_PATTERN.search(label.text())
    return match.group(1) if match else ""


def model_of(page: ScrapersPage) -> Any:
    """The page's table model, for asserting on the staged Use browser set.

    :param page: the page to reach into.
    :returns: the ``ScrapersTableModel`` instance.
    """
    return page._ScrapersPage__model  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


def test_a_fresh_install_shows_an_empty_folder_firefox_and_the_registrys_rows(qtbot: QtBot) -> None:
    """With nothing persisted the folder field is empty, Firefox is selected, showing is unticked, the
    header names the default folder actually scanned, and the table shows the registry's rows (#269,
    #278).

    **Test steps:**

    * build the page against empty persistent storage
    * verify the folder field, the browser combo, the show-browser check and the page's clean state
    * verify the scanned label names the default folder and the table has the registry's two rows
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.folder_edit.text() == ""
    assert ui.browser_combo.currentIndex() == 0
    assert ui.show_browser_check.isChecked() is False
    assert page.is_dirty() is False
    assert (
        path_link_href(ui.scanned_path_link)
        == QUrl.fromLocalFile(str(shared_scrapers_settings().effective_scripts_folder)).toString()
    )
    assert ui.scrapers_table.model().rowCount() == 2


def test_typing_a_folder_dirties_the_page_without_touching_the_registry(qtbot: QtBot, registry: FakeRegistry) -> None:
    """A staged edit is only staged: dirty, but nothing saved and nothing re-scanned (#269).

    **Test steps:**

    * build the page and type a folder
    * verify the page is dirty, the settings still hold the old value, and no reload happened
    """
    page = ScrapersPage()
    qtbot.addWidget(page)

    page_ui(page).folder_edit.setText(CHOSEN_FOLDER)

    assert page.is_dirty() is True
    assert shared_scrapers_settings().scripts_folder == ""
    assert registry.reloads == 0


def test_choosing_chrome_dirties_the_page(qtbot: QtBot) -> None:
    """Picking a different browser in the combo is a staged edit like any other (#278).

    **Test steps:**

    * build the page and select Chrome
    * verify the page is dirty and the settings still hold Firefox
    """
    page = ScrapersPage()
    qtbot.addWidget(page)

    page_ui(page).browser_combo.setCurrentIndex(1)

    assert page.is_dirty() is True
    assert shared_scrapers_settings().browser == Browser.FIREFOX


def test_ticking_a_row_dirties_the_page(qtbot: QtBot) -> None:
    """Ticking the plain scraper's Use browser cell is a staged edit (#278).

    **Test steps:**

    * build the page and stage the plain scraper's key through the model
    * verify the page is dirty and the saved settings still hold nothing
    """
    page = ScrapersPage()
    qtbot.addWidget(page)

    model_of(page).set_browser_scrapers(frozenset({TICKED_KEY}))

    assert page.is_dirty() is True
    assert shared_scrapers_settings().browser_scrapers == frozenset()


def test_save_persists_every_staged_value_and_reloads_the_shared_registry(
    qtbot: QtBot, registry: FakeRegistry, fake_persistent_settings: FakeSettings
) -> None:
    """Save is what makes a new folder, browser, show-browser flag or ticked scraper take effect: every
    value is written to storage, the shared registry is reloaded, and the page is clean again (#269,
    #278).

    **Test steps:**

    * build the page, stage every value, save
    * verify each value reached persistent storage and the shared settings
    * verify the registry was reloaded exactly once, and the page is clean again
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.folder_edit.setText(CHOSEN_FOLDER)
    ui.browser_combo.setCurrentIndex(1)
    ui.show_browser_check.setChecked(True)
    model_of(page).set_browser_scrapers(frozenset({TICKED_KEY}))

    page.save_changes()

    assert fake_persistent_settings.value("scrapers/scripts_folder") == CHOSEN_FOLDER
    assert fake_persistent_settings.value("scrapers/browser") == Browser.CHROME.value
    assert fake_persistent_settings.value("scrapers/show_browser") is True
    assert fake_persistent_settings.value("scrapers/browser_scrapers") == [TICKED_KEY]
    settings = shared_scrapers_settings()
    assert settings.scripts_folder == CHOSEN_FOLDER
    assert settings.browser == Browser.CHROME
    assert settings.show_browser is True
    assert settings.browser_scrapers == frozenset({TICKED_KEY})
    assert registry.reloads == 1
    assert page.is_dirty() is False


def test_drop_changes_restores_every_saved_value(qtbot: QtBot) -> None:
    """Discarding staged edits puts every saved value back (#269, #278).

    **Test steps:**

    * build the page, stage every value, drop the changes
    * verify every field is back to the saved value and the page is clean
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.folder_edit.setText(CHOSEN_FOLDER)
    ui.browser_combo.setCurrentIndex(1)
    ui.show_browser_check.setChecked(True)
    model_of(page).set_browser_scrapers(frozenset({TICKED_KEY}))

    page.drop_changes()

    assert ui.folder_edit.text() == ""
    assert ui.browser_combo.currentIndex() == 0
    assert ui.show_browser_check.isChecked() is False
    assert model_of(page).browser_scrapers() == frozenset()
    assert page.is_dirty() is False


def test_seed_defaults_stages_every_factory_value_over_saved_ones(qtbot: QtBot, registry: FakeRegistry) -> None:
    """``seed_defaults`` shows every factory value as a staged edit against saved ones, and leaves the
    table's saved-folder scan alone (#342, #278).

    **Test steps:**

    * save non-default values and build the page
    * call ``seed_defaults``
    * verify every field is back to its factory value, the page is dirty, and nothing was rescanned
    """
    settings = shared_scrapers_settings()
    settings.scripts_folder = CHOSEN_FOLDER
    settings.browser = Browser.CHROME
    settings.show_browser = True
    settings.browser_scrapers = frozenset({TICKED_KEY})
    page = ScrapersPage()
    qtbot.addWidget(page)

    page.seed_defaults()

    ui = page_ui(page)
    assert ui.folder_edit.text() == ""
    assert ui.browser_combo.currentIndex() == 0
    assert ui.show_browser_check.isChecked() is False
    assert model_of(page).browser_scrapers() == frozenset()
    assert page.is_dirty() is True
    assert registry.reloads == 0


def test_reload_rescans_without_saving_a_typed_folder(qtbot: QtBot, registry: FakeRegistry) -> None:
    """Reload re-scans the saved folder, never the one being typed -- so a dirty field is never
    mistaken for what the table shows (#269).

    **Test steps:**

    * build the page, type a folder, press Reload
    * verify the registry was reloaded, the typed folder was not saved, and the header still names
      the saved (default) folder
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.folder_edit.setText(CHOSEN_FOLDER)

    ui.reload_button.click()

    assert registry.reloads == 1
    assert shared_scrapers_settings().scripts_folder == ""
    assert page.is_dirty() is True


def test_browse_puts_the_chosen_folder_in_the_field(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Browse fills the field with the folder picked, opening on what was typed (#269).

    **Test steps:**

    * build the page and stand in for the folder dialog
    * press Browse
    * verify the dialog opened on the field's text and its answer landed in the field
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    dialog = mocker.patch(
        "rehuco_agent.settings.ui.scrapers_page.QFileDialog.getExistingDirectory", return_value=CHOSEN_FOLDER
    )

    page_ui(page).browse_button.click()

    assert page_ui(page).folder_edit.text() == CHOSEN_FOLDER
    assert dialog.call_args.args[2] == ""


def test_a_cancelled_browse_leaves_the_field_alone(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Cancelling the folder dialog changes nothing (#269).

    **Test steps:**

    * build the page with a typed folder and a dialog that answers nothing
    * press Browse
    * verify the field still holds what was typed
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    page_ui(page).folder_edit.setText(CHOSEN_FOLDER)
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.QFileDialog.getExistingDirectory", return_value="")

    page_ui(page).browse_button.click()

    assert page_ui(page).folder_edit.text() == CHOSEN_FOLDER


def test_the_persona_path_label_follows_the_staged_browser(qtbot: QtBot) -> None:
    """The read-only persona path label names the currently staged browser's own folder, not the saved
    one, so a browser choice mid-edit is never confused with another browser's persona (#278).

    **Test steps:**

    * build the page and select Chrome
    * verify the label names Chrome's persona folder
    """
    page = ScrapersPage()
    qtbot.addWidget(page)

    page_ui(page).browser_combo.setCurrentIndex(1)

    assert "chrome" in path_link_href(page_ui(page).persona_path_link)


def test_open_the_browser_runs_off_the_gui_thread_and_disables_the_controls_meanwhile(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Open the browser disables the controls it could race with the instant it is clicked, and
    re-enables them once the (real, pooled) worker thread reports back -- never freezing the GUI
    thread for however long starting a browser takes (#278).

    **Test steps:**

    * build the page, select Chrome without saving, and make ``open_for_login`` block until released
    * click Open the browser
    * verify the controls are disabled while the call is still blocked
    * release it, wait for the controls to come back, and verify Chrome was asked for
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.browser_combo.setCurrentIndex(1)
    release = threading.Event()
    persona_browser = mocker.Mock()
    persona_browser.open_for_login.side_effect = lambda _browser: release.wait(timeout=5)
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)

    ui.open_browser_button.click()

    assert not ui.open_browser_button.isEnabled()
    assert not ui.reset_persona_button.isEnabled()
    assert not ui.browser_combo.isEnabled()
    release.set()
    qtbot.waitUntil(ui.open_browser_button.isEnabled)

    assert ui.reset_persona_button.isEnabled()
    assert ui.browser_combo.isEnabled()
    persona_browser.open_for_login.assert_called_once_with(Browser.CHROME)


def test_open_the_browser_shows_a_warning_on_failure(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A `FetchError` opening the persona is shown as a warning, not left to crash the page (#278).

    **Test steps:**

    * build the page, stand in for the persona browser raising `FetchError` and for the message box
    * press Open the browser and wait for the worker thread to report back
    * verify a warning was shown
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    persona_browser = mocker.Mock()
    persona_browser.open_for_login.side_effect = FetchError("no Firefox installed")
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)
    warning = mocker.patch("rehuco_agent.settings.ui.scrapers_page.QMessageBox.warning")

    ui.open_browser_button.click()
    qtbot.waitUntil(ui.open_browser_button.isEnabled)

    warning.assert_called_once()


def test_reset_persona_asks_for_confirmation_and_resets_on_yes(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Reset persona confirms before deleting the staged browser's profile, and resets it on yes, off
    the GUI thread -- quitting a live session can itself hang, exactly when it is a stuck browser
    process the reset was reached for (#278).

    **Test steps:**

    * build the page and stand in for the persona browser and a confirming question box
    * press Reset persona… and wait for the worker thread to report back
    * verify the persona was reset for the staged (Firefox) browser
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    persona_browser = mocker.Mock()
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)
    mocker.patch(
        "rehuco_agent.settings.ui.scrapers_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    )

    ui.reset_persona_button.click()
    qtbot.waitUntil(ui.reset_persona_button.isEnabled)

    persona_browser.reset.assert_called_once_with(Browser.FIREFOX)


def test_reset_persona_does_nothing_on_no(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Declining the confirmation leaves the persona alone (#278).

    **Test steps:**

    * build the page and stand in for the persona browser and a declining question box
    * press Reset persona…
    * verify nothing was reset
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    persona_browser = mocker.Mock()
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)
    mocker.patch(
        "rehuco_agent.settings.ui.scrapers_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    )

    page_ui(page).reset_persona_button.click()

    persona_browser.reset.assert_not_called()


def test_reset_persona_shows_a_warning_when_deleting_fails(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A failed delete (e.g. a file still locked by a stray process) is shown as a warning (#278).

    **Test steps:**

    * build the page and stand in for a confirming question box and a persona browser whose reset raises
    * press Reset persona… and wait for the worker thread to report back
    * verify a warning was shown
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    persona_browser = mocker.Mock()
    persona_browser.reset.side_effect = OSError("file in use")
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)
    mocker.patch(
        "rehuco_agent.settings.ui.scrapers_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    )
    warning = mocker.patch("rehuco_agent.settings.ui.scrapers_page.QMessageBox.warning")

    ui.reset_persona_button.click()
    qtbot.waitUntil(ui.reset_persona_button.isEnabled)

    warning.assert_called_once()


def test_the_scrapers_frame_gets_a_header_and_ticking_a_row_dirties_it(qtbot: QtBot) -> None:
    """Registered through a real `SettingsDialog`, the Scrapers table frame gets an Apply/Reset
    saved/Reset defaults header (its ``scrapers_frame_label`` names it, and the promoted
    `~rehuco_agent.settings.ui.scrapers_table_view.ScrapersTableView` gives
    `~rehuco_agent.settings.ui.settings_frame_filter.SettingsFrameFilter` something to snapshot), and
    ticking a row's **Use browser** box tints the frame the same way any other edited value does
    (#278, #342).

    **Test steps:**

    * register the page on a real dialog
    * verify the frame has a header naming it "Scrapers"
    * tick the plain scraper's row and refresh the dirty state
    * verify the frame is now tinted dirty
    """
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = ScrapersPage()

    dialog.add_page("Scrapers", page)

    ui = page_ui(page)
    headers = dialog._SettingsDialog__frame_headers  # type: ignore[attr-defined]  # pylint: disable=protected-access
    header = headers.get(ui.scrapers_frame)
    assert header is not None
    assert ui.scrapers_frame_label.text() == "Scrapers"
    assert ui.scrapers_frame.property("dirty") is False

    model_of(page).set_browser_scrapers(frozenset({TICKED_KEY}))
    dialog._SettingsDialog__refresh_dirty_ui()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.scrapers_frame.property("dirty") is True


def test_the_scraper_column_uses_the_link_delegate(qtbot: QtBot) -> None:
    """The Scraper column has its own delegate, which renders and hit-tests a row's site link -- see
    `test_scrapers_scraper_column_delegate.py` for how it does either (#278).

    **Test steps:**

    * build the page
    * verify the Scraper column's delegate is a `ScrapersScraperColumnDelegate`
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    delegate = ui.scrapers_table.itemDelegateForColumn(SCRAPER_COLUMN)

    assert isinstance(delegate, ScrapersScraperColumnDelegate)


def test_activating_a_scraper_cells_link_opens_it_in_the_persona_browser(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The delegate's `link_activated` signal opens the clicked URL in the persona browser, on the
    staged browser -- the same un-automated window **Open the browser** opens (#278).

    **Test steps:**

    * build the page and stand in for the persona browser
    * emit the Scraper column delegate's `link_activated` signal
    * verify `open_for_login` was called with the staged browser and that URL
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    persona_browser = mocker.Mock()
    mocker.patch("rehuco_agent.settings.ui.scrapers_page.shared_persona_browser", return_value=persona_browser)
    delegate = ui.scrapers_table.itemDelegateForColumn(SCRAPER_COLUMN)
    assert isinstance(delegate, ScrapersScraperColumnDelegate)

    delegate.link_activated.emit(TICKED_ROW.site_url)
    qtbot.waitUntil(lambda: persona_browser.open_for_login.called)

    persona_browser.open_for_login.assert_called_once_with(Browser.FIREFOX, TICKED_ROW.site_url)


def test_activating_a_path_link_reveals_it_in_the_file_browser(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Activating either path link -- the persona folder or the scanned scripts folder -- reveals it
    in the OS file browser, never opened *into* (#278).

    **Test steps:**

    * build the page and stand in for the OS reveal call
    * activate the persona path link
    * verify the reveal call got the folder the link's own href carried
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    reveal = mocker.patch("rehuco_agent.settings.ui.scrapers_page.reveal_in_file_browser")
    href = path_link_href(ui.persona_path_link)

    ui.persona_path_link.linkActivated.emit(href)

    reveal.assert_called_once_with(Path(QUrl(href).toLocalFile()))


# region web search engines (#388)
MINE = SearchEngine("Mine", "https://example.com/find?q={query}")


def engines_model(page: ScrapersPage) -> Any:
    """The engine table's model, for driving its radio column like a click would.

    :param page: the page to reach into.
    :returns: the model behind the engines editor.
    """
    return page_ui(page).web_search_engines_editor.model


def test_a_fresh_install_shows_the_shipped_engines_with_google_active_and_nothing_to_apply(qtbot: QtBot) -> None:
    """The shipped list, its first engine's radio on, and a clean page.

    **Test steps:**

    * build the page
    * verify the list, the active row and the dirty state
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    assert page_ui(page).web_search_engines_editor.values == DEFAULT_ENGINES
    assert page.is_dirty() is False


def test_the_radio_leads_the_row_on_screen_while_add_still_opens_the_name(qtbot: QtBot) -> None:
    """The radio is the first *visual* column only: `ItemListEditor` opens model column 0 on Add and
    abandons a row whose column 0 stays blank, so that column has to be the name.

    **Test steps:**

    * verify the radio section is shown first and the name is model column 0
    * add a row through the editor protocol, verify it counts as blank, name it, verify it no longer does
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    editor = page_ui(page).web_search_engines_editor
    header = editor.view.horizontalHeader()
    assert header.visualIndex(ACTIVE_COLUMN) == 0
    assert NAME_COLUMN == 0

    model = engines_model(page)
    row = model.insert(-1)
    assert editor.row_is_blank(row)
    model.setData(model.index(row, NAME_COLUMN), "Mine", Qt.ItemDataRole.EditRole)
    assert not editor.row_is_blank(row)


def test_the_editors_reset_target_can_be_read_and_replaced(qtbot: QtBot) -> None:
    """Reset goes back to the shipped engines unless the owner says otherwise.

    **Test steps:**

    * verify the editor's defaults are the shipped engines
    * replace them and verify the new ones are read back
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    editor = page_ui(page).web_search_engines_editor
    assert editor.defaults == DEFAULT_ENGINES

    editor.defaults = (MINE,)

    assert editor.defaults == (MINE,)


def test_the_radio_delegate_paints_and_a_click_on_the_radio_checks_the_row(qtbot: QtBot) -> None:
    """The Use column draws a radio and a click on it -- and only on it -- makes the row the active one.

    **Test steps:**

    * show the page's engine table and grab it, which paints every cell
    * click beside the second row's radio and verify nothing changed
    * click on the second row's radio and verify that row is active
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    page.resize(700, 900)
    page.show()
    view = page_ui(page).web_search_engines_editor.view
    assert not view.grab().isNull()
    model = engines_model(page)
    cell = view.visualRect(model.index(1, ACTIVE_COLUMN))

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=cell.topLeft() + QPoint(1, 1))
    assert [engine.active for engine in page_ui(page).web_search_engines_editor.values] == [True, False, False]

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=cell.center())
    assert [engine.active for engine in page_ui(page).web_search_engines_editor.values] == [False, True, False]


def test_checking_another_radio_switches_the_active_engine_and_dirties_the_page(qtbot: QtBot) -> None:
    """One radio is on at a time: picking a row turns the previous one off.

    **Test steps:**

    * check the second row's radio through the model, as a click on it does
    * verify only that row is active and the page is dirty
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    model = engines_model(page)

    assert model.setData(model.index(1, ACTIVE_COLUMN), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    assert [engine.active for engine in page_ui(page).web_search_engines_editor.values] == [False, True, False]
    assert page.is_dirty() is True


def test_saving_pushes_the_engines_and_the_active_one_into_the_shared_settings(
    qtbot: QtBot, web_search_save: Any
) -> None:
    """Apply stores the list with its active row, and the page is clean again.

    **Test steps:**

    * add an engine and make it the active one
    * save
    * verify the shared settings, the persisted save and the clean page
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.web_search_engines_editor.values = (*DEFAULT_ENGINES, MINE)
    model = engines_model(page)
    model.setData(model.index(3, ACTIVE_COLUMN), True, Qt.ItemDataRole.EditRole)
    assert page.is_dirty() is True

    page.save_changes()

    settings = shared_web_search_settings()
    assert settings.selected.name == "Mine"
    assert [engine.name for engine in settings.engines] == ["Google", "DuckDuckGo", "Bing", "Mine"]
    web_search_save.assert_called_once()
    assert page.is_dirty() is False


def test_a_frame_reset_puts_back_the_saved_list_and_its_active_radio(qtbot: QtBot) -> None:
    """The Web search frame's own Reset restores the rows *and* which of them was active.

    **Test steps:**

    * save the shipped list with the second engine active, and capture the frame baseline
    * add an engine at the top and make it active
    * restore the frame's saved values and verify the list and the second row's radio are back
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    model = engines_model(page)
    model.setData(model.index(1, ACTIVE_COLUMN), True, Qt.ItemDataRole.EditRole)
    page.save_changes()
    frame_filter = SettingsFrameFilter(page, "Scrapers")
    ui.web_search_engines_editor.values = (MINE._replace(active=True), *DEFAULT_ENGINES)
    assert frame_filter.dirty_frames() == [ui.web_search_frame]

    frame_filter.restore_saved(ui.web_search_frame)

    assert [(engine.name, engine.active) for engine in ui.web_search_engines_editor.values] == [
        ("Google", False),
        ("DuckDuckGo", True),
        ("Bing", False),
    ]
    assert not frame_filter.dirty_frames()


def test_drop_and_defaults_restore_the_saved_and_the_shipped_engines(qtbot: QtBot) -> None:
    """Drop goes back to what is saved; Defaults stages the shipped list and its active engine.

    **Test steps:**

    * save a custom list, then stage another edit and drop it, verifying the saved list is back
    * seed the defaults and verify the shipped list is staged and the page dirty
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.web_search_engines_editor.values = (MINE,)
    page.save_changes()
    ui.web_search_engines_editor.values = ()
    page.drop_changes()
    assert ui.web_search_engines_editor.values == (MINE._replace(active=True),)

    page.seed_defaults()

    assert ui.web_search_engines_editor.values == WebSearchSettings().engines
    assert page.is_dirty() is True


# endregion
