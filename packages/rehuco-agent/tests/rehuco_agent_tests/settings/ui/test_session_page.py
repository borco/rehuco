"""Tests for SessionPage: the Session settings category page (#65)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings
from rehuco_agent.settings.ui import session_page
from rehuco_agent.settings.ui.session_page import SessionPage
from rehuco_agent.settings.ui.settings_page import SettingsPage


# region fixtures
# Mirrors test_tasks_page.py's FakeSettings exactly -- kept as a separate copy, matching this
# codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

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


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> Iterator[FakeSettings]:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    :returns: the stand-in the page sees.
    """
    fake = FakeSettings()
    mocker.patch.object(session_page, "persistent_settings", return_value=fake)
    yield fake


@fixture
def page(qtbot: QtBot) -> SessionPage:
    """Provide a page seeded from the (empty) fake storage.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    built = SessionPage()
    qtbot.addWidget(built)
    return built


def ui(page: SessionPage) -> Any:
    """Reach a page's generated UI object.

    :param page: the page to read.
    :returns: the UI object.
    """
    return page._SessionPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


def test_satisfies_the_settings_page_protocol(page: SessionPage) -> None:
    """It is a settings page in the structural sense the dialog registers.

    **Test steps:**

    * Assert the page satisfies `SettingsPage`.
    """
    assert isinstance(page, SettingsPage)


def test_checkbox_starts_checked(page: SessionPage) -> None:
    """A freshly opened page shows the shipped default: restore on.

    **Test steps:**

    * Assert the checkbox is checked.
    """
    assert ui(page).restore_on_startup_check_box.isChecked()


def test_is_clean_until_something_is_toggled(page: SessionPage) -> None:
    """Nothing staged is nothing to save.

    **Test steps:**

    * Assert the page is not dirty.
    """
    assert not page.is_dirty()


def test_toggling_the_checkbox_is_reported_as_dirty(page: SessionPage) -> None:
    """A toggled checkbox is a staged change.

    **Test steps:**

    * Uncheck the checkbox.
    * Assert the page is dirty.
    """
    ui(page).restore_on_startup_check_box.setChecked(False)
    assert page.is_dirty()


def test_saving_persists_the_choice(page: SessionPage, fake_persistent_settings: FakeSettings) -> None:
    """Save writes the checkbox to storage.

    **Test steps:**

    * Uncheck the box and save.
    * Assert a freshly loaded `SessionRestoreSettings` reads it back off.
    """
    ui(page).restore_on_startup_check_box.setChecked(False)

    page.save_changes()

    loaded = SessionRestoreSettings()
    loaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert loaded.restore_on_startup is False
    assert not page.is_dirty()


def test_dropping_changes_re_seeds_from_storage(page: SessionPage) -> None:
    """Cancelling puts back what is actually saved.

    **Test steps:**

    * Uncheck the box, then drop the changes.
    * Assert it came back checked and the page is clean.
    """
    ui(page).restore_on_startup_check_box.setChecked(False)

    page.drop_changes()

    assert ui(page).restore_on_startup_check_box.isChecked()
    assert not page.is_dirty()
