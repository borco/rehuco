"""Tests for TasksPage: the Tasks settings category page (#202)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.tasks_settings import TasksSettings
from rehuco_agent.settings.ui import tasks_page
from rehuco_agent.settings.ui.settings_page import SettingsPage
from rehuco_agent.settings.ui.tasks_page import TasksPage


# region fixtures
# Mirrors test_logs_page.py's FakeSettings exactly -- kept as a separate copy, matching this
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
    mocker.patch.object(tasks_page, "persistent_settings", return_value=fake)
    yield fake


@fixture
def page(qtbot: QtBot) -> TasksPage:
    """Provide a page seeded from the (empty) fake storage.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    built = TasksPage()
    qtbot.addWidget(built)
    return built


def ui(page: TasksPage) -> Any:
    """Reach a page's generated UI object.

    :param page: the page to read.
    :returns: the UI object.
    """
    return page._TasksPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


def test_satisfies_the_settings_page_protocol(page: TasksPage) -> None:
    """It is a settings page in the structural sense the dialog registers.

    **Test steps:**

    * Assert the page satisfies `SettingsPage`.
    """
    assert isinstance(page, SettingsPage)


def test_is_titled_tasks(page: TasksPage) -> None:
    """The category tree calls it Tasks.

    **Test steps:**

    * Assert the title.
    """
    assert page.title == "Tasks"


def test_all_three_checkboxes_start_unchecked(page: TasksPage) -> None:
    """A freshly opened page shows the shipped default: nothing is swept or restarted unless asked.

    **Test steps:**

    * Assert all three checkboxes are unchecked.
    """
    assert not ui(page).clear_done_check_box.isChecked()
    assert not ui(page).clear_failed_check_box.isChecked()
    assert not ui(page).resume_check_box.isChecked()


def test_is_clean_until_something_is_toggled(page: TasksPage) -> None:
    """Nothing staged is nothing to save.

    **Test steps:**

    * Assert the page is not dirty.
    """
    assert not page.is_dirty()


def test_toggling_any_checkbox_is_reported_as_dirty(page: TasksPage) -> None:
    """A toggled checkbox is a staged change.

    **Test steps:**

    * Check the resume checkbox.
    * Assert the page is dirty.
    """
    ui(page).resume_check_box.setChecked(True)
    assert page.is_dirty()


def test_saving_persists_all_three_choices(page: TasksPage, fake_persistent_settings: FakeSettings) -> None:
    """Save writes every checkbox to storage.

    **Test steps:**

    * Check all three boxes and save.
    * Assert a freshly loaded `TasksSettings` reads them all back true.
    """
    ui(page).clear_done_check_box.setChecked(True)
    ui(page).clear_failed_check_box.setChecked(True)
    ui(page).resume_check_box.setChecked(True)

    page.save_changes()

    loaded = TasksSettings()
    loaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert loaded.clear_done_on_restart is True
    assert loaded.clear_failed_on_restart is True
    assert loaded.resume_on_restart is True
    assert not page.is_dirty()


def test_dropping_changes_re_seeds_from_storage(page: TasksPage) -> None:
    """Cancelling puts back what is actually saved.

    **Test steps:**

    * Check a box, then drop the changes.
    * Assert it came back unchecked and the page is clean.
    """
    ui(page).clear_done_check_box.setChecked(True)

    page.drop_changes()

    assert not ui(page).clear_done_check_box.isChecked()
    assert not page.is_dirty()
