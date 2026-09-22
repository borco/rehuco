"""Tests for ScrapersPage: the Scrapers settings category page (#269)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.scraping.registry import LoadedScraperModule
from rehuco_agent.settings import scrapers_settings
from rehuco_agent.settings.scrapers_settings import shared_scrapers_settings
from rehuco_agent.settings.ui import scrapers_page
from rehuco_agent.settings.ui.scrapers_page import ScrapersPage

CHOSEN_FOLDER = "/my/scrapers"


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
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)

    def fileName(self) -> str:  # noqa: N802
        return "/fake/borco/rehuco-agent.ini"


# pylint: enable=duplicate-code


class FakeRegistry:  # pylint: disable=missing-function-docstring,too-few-public-methods
    """Stands in for the shared `ScraperRegistry`: fixed rows, and a count of reloads asked for."""

    def __init__(self) -> None:
        self.modules: tuple[LoadedScraperModule, ...] = (
            LoadedScraperModule(path=Path("/fake/scrapers/foo_scraper.py"), scrapers=(), error=None),
        )
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


def page_ui(page: ScrapersPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_ScrapersPage`` instance.
    """
    return page._ScrapersPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


def test_a_fresh_install_shows_an_empty_folder_the_default_scan_and_the_registrys_rows(qtbot: QtBot) -> None:
    """With nothing persisted the field is empty, the header names the default folder actually
    scanned, and the table shows what the shared registry loaded (#269).

    **Test steps:**

    * build the page against empty persistent storage
    * verify the folder field is empty and the page is clean
    * verify the scanned label names the default folder and the table has the registry's one row
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.folder_edit.text() == ""
    assert page.is_dirty() is False
    assert str(shared_scrapers_settings().effective_scripts_folder) in ui.scanned_label.text()
    assert ui.scrapers_table.model().rowCount() == 1


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


def test_save_persists_the_folder_and_reloads_the_shared_registry(
    qtbot: QtBot, registry: FakeRegistry, fake_persistent_settings: FakeSettings
) -> None:
    """Save is what makes a new folder take effect: it is written to storage, the shared registry is
    reloaded, and the header now names the saved folder (#269).

    **Test steps:**

    * build the page, type a folder, save
    * verify the value reached persistent storage and the shared settings
    * verify the registry was reloaded exactly once, and the page is clean again
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    page_ui(page).folder_edit.setText(CHOSEN_FOLDER)

    page.save_changes()

    assert fake_persistent_settings.value("scrapers/scripts_folder") == CHOSEN_FOLDER
    assert shared_scrapers_settings().scripts_folder == CHOSEN_FOLDER
    assert registry.reloads == 1
    assert page.is_dirty() is False
    assert str(Path(CHOSEN_FOLDER)) in page_ui(page).scanned_label.text()


def test_drop_changes_restores_the_saved_folder(qtbot: QtBot) -> None:
    """Discarding a staged edit puts the saved value back in the field (#269).

    **Test steps:**

    * build the page, type a folder, drop the change
    * verify the field is back to the saved value and the page is clean
    """
    page = ScrapersPage()
    qtbot.addWidget(page)
    page_ui(page).folder_edit.setText(CHOSEN_FOLDER)

    page.drop_changes()

    assert page_ui(page).folder_edit.text() == ""
    assert page.is_dirty() is False


def test_seed_defaults_stages_the_empty_folder_over_a_saved_one(qtbot: QtBot, registry: FakeRegistry) -> None:
    """``seed_defaults`` shows the factory value -- no folder, meaning the default location -- as a
    staged edit against a saved one, and leaves the table's saved-folder scan alone (#342).

    **Test steps:**

    * save a folder and build the page
    * call ``seed_defaults``
    * verify the field is empty, the page is dirty, and nothing was rescanned
    """
    shared_scrapers_settings().scripts_folder = CHOSEN_FOLDER
    page = ScrapersPage()
    qtbot.addWidget(page)
    assert page_ui(page).folder_edit.text() == CHOSEN_FOLDER

    page.seed_defaults()

    assert page_ui(page).folder_edit.text() == ""
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
    assert str(Path(CHOSEN_FOLDER)) not in ui.scanned_label.text()
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
