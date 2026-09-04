"""Tests for LogsPage: the Logs settings category page (#200)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.logging import DEFAULT_LOG_LIMIT
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import logs_settings
from rehuco_agent.settings.logs_settings import APP_LIMIT_KEY, GROUP, RESOURCE_LIMIT_KEY, shared_logs_settings
from rehuco_agent.settings.ui import logs_page
from rehuco_agent.settings.ui.logs_page import LogsPage
from rehuco_agent.settings.ui.settings_page import SettingsPage


# region fixtures
# Mirrors test_videos_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_logs_settings.py`` for the full rationale)."""

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

    Patched in both modules that reach for it -- the page (which persists on save) and the settings
    section (which the shared instance loads through) -- and the shared instance is dropped either side,
    so neither this test's values nor another's leak.

    :returns: the stand-in both modules see.
    """
    fake = FakeSettings()
    shared_logs_settings.cache_clear()
    mocker.patch.object(logs_page, "persistent_settings", return_value=fake)
    mocker.patch.object(logs_settings, "persistent_settings", return_value=fake)
    yield fake
    shared_logs_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> LogsPage:
    """Provide a shown page seeded from the (empty) fake storage.

    Shown, because the clamp note's whole job is to be *visible* or not, which an unshown widget's
    ``isVisible()`` cannot answer -- it is false for every child of a hidden parent.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    logs_settings_page = LogsPage()
    qtbot.addWidget(logs_settings_page)
    logs_settings_page.show()
    qtbot.waitExposed(logs_settings_page)
    return logs_settings_page


def ui(page: LogsPage) -> Any:
    """Reach a page's generated UI object.

    :param page: the page to read.
    :returns: the UI object.
    """
    return page._LogsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


# endregion


# region the page contract


def test_satisfies_the_settings_page_protocol(page: LogsPage) -> None:
    """It is a settings page in the structural sense the dialog registers.

    **Test steps:**

    * Assert the page satisfies `SettingsPage`.
    """
    assert isinstance(page, SettingsPage)


def test_starts_showing_the_saved_limits(page: LogsPage) -> None:
    """A freshly opened page shows what the surfaces are actually keeping.

    **Test steps:**

    * Assert both spin boxes hold the defaults from empty storage.
    """
    assert ui(page).app_limit_spin_box.value() == DEFAULT_LOG_LIMIT
    assert ui(page).resource_limit_spin_box.value() == DEFAULT_LOG_LIMIT


def test_is_clean_until_something_is_typed(page: LogsPage) -> None:
    """Nothing staged is nothing to save.

    **Test steps:**

    * Assert the page is not dirty.
    """
    assert not page.is_dirty()


def test_reports_a_changed_app_limit_as_dirty(page: LogsPage) -> None:
    """A typed app limit is a staged change.

    **Test steps:**

    * Change the app limit spin box.
    * Assert the page is dirty.
    """
    ui(page).app_limit_spin_box.setValue(123)
    assert page.is_dirty()


def test_reports_a_changed_resource_limit_as_dirty(page: LogsPage) -> None:
    """A typed resource limit is a staged change too.

    **Test steps:**

    * Change the resource limit spin box.
    * Assert the page is dirty.
    """
    ui(page).resource_limit_spin_box.setValue(20)
    assert page.is_dirty()


# endregion


# region saving and dropping


def test_saving_pushes_both_limits_into_the_shared_settings(page: LogsPage) -> None:
    """Save is what every open surface re-caps off -- so it lands on the shared object.

    **Test steps:**

    * Type both limits and save.
    * Assert the shared settings hold them, and the page is clean again.
    """
    ui(page).app_limit_spin_box.setValue(900)
    ui(page).resource_limit_spin_box.setValue(30)

    page.save_changes()

    settings = shared_logs_settings()
    assert settings.app_limit == 900
    assert settings.resource_limit == 30
    assert not page.is_dirty()


def test_saving_persists_both_limits(page: LogsPage, fake_persistent_settings: FakeSettings) -> None:
    """The limits survive a restart.

    **Test steps:**

    * Type both limits and save.
    * Assert both are in storage under this section's group.
    """
    ui(page).app_limit_spin_box.setValue(64)
    ui(page).resource_limit_spin_box.setValue(16)

    page.save_changes()

    fake_persistent_settings.beginGroup(GROUP)
    assert fake_persistent_settings.value(APP_LIMIT_KEY) == 64
    assert fake_persistent_settings.value(RESOURCE_LIMIT_KEY) == 16


def test_dropping_changes_re_seeds_from_the_shared_settings(page: LogsPage) -> None:
    """Cancelling puts back what the surfaces are really keeping.

    **Test steps:**

    * Type a limit, then drop the changes.
    * Assert the spin box came back and the page is clean.
    """
    ui(page).app_limit_spin_box.setValue(11)

    page.drop_changes()

    assert ui(page).app_limit_spin_box.value() == DEFAULT_LOG_LIMIT
    assert not page.is_dirty()


# endregion


# region the clamp note


def test_says_nothing_while_the_resource_limit_fits(page: LogsPage) -> None:
    """With the resource limit under the app one there is nothing to warn about.

    **Test steps:**

    * Assert the note is neither shown nor holding text at the defaults, where the two are equal.
    """
    assert not ui(page).clamp_note_label.isVisible()
    assert ui(page).clamp_note_label.text() == ""


def test_says_which_limit_actually_applies_when_the_resource_one_is_higher(page: LogsPage) -> None:
    """A resource limit above the app one is reported rather than silently corrected.

    The typed value is kept, so raising the app limit later gives the resource logs the number they were
    already asked for -- but a page showing a limit nothing honours would be lying about its own Save.

    **Test steps:**

    * Set the resource limit above the app one.
    * Assert the note is shown and names the app limit.
    """
    ui(page).app_limit_spin_box.setValue(200)
    ui(page).resource_limit_spin_box.setValue(5000)

    assert ui(page).clamp_note_label.isVisible()
    assert "200" in ui(page).clamp_note_label.text()
    assert ui(page).resource_limit_spin_box.value() == 5000


def test_the_note_clears_once_the_app_limit_is_raised(page: LogsPage) -> None:
    """Raising the app limit resolves it, and the note goes away.

    Checked against the staged values, not the saved ones: what a reader wants to know while typing a
    number is whether the number they are typing will apply.

    **Test steps:**

    * Put the resource limit above the app one, then raise the app one past it.
    * Assert the note is empty.
    """
    ui(page).app_limit_spin_box.setValue(200)
    ui(page).resource_limit_spin_box.setValue(5000)
    ui(page).app_limit_spin_box.setValue(6000)

    assert ui(page).clamp_note_label.text() == ""


# endregion


# region keeping everything


def test_the_resource_limit_goes_down_to_zero_and_the_app_one_does_not(page: LogsPage) -> None:
    """Only the per-resource surface can be asked to keep everything (#236).

    **Test steps:**

    * Assert each spin box's smallest value.
    """
    assert ui(page).resource_limit_spin_box.minimum() == 0
    assert ui(page).app_limit_spin_box.minimum() == 1


def test_zero_reads_as_words_rather_than_a_number(page: LogsPage) -> None:
    """A bare ``0`` in a *records kept* box reads as *keep none* -- the opposite of what it means.

    **Test steps:**

    * Set the resource limit to zero.
    * Assert the box shows wording instead of the digit.
    """
    ui(page).resource_limit_spin_box.setValue(0)

    assert ui(page).resource_limit_spin_box.specialValueText() != ""
    assert ui(page).resource_limit_spin_box.text() == ui(page).resource_limit_spin_box.specialValueText()
    assert "0" not in ui(page).resource_limit_spin_box.text()


def test_the_clamp_note_stays_quiet_at_zero(page: LogsPage) -> None:
    """*Keep everything* is never *above* the app limit, so there is nothing to hold it down to (#236).

    The note would otherwise be the page's loudest element in the one case where nothing is wrong: zero
    is honoured exactly as typed, unlike the number it shares a comparison with.

    **Test steps:**

    * Set the resource limit to zero, under an app limit that would clamp a number.
    * Assert the note is neither shown nor holding text.
    """
    ui(page).app_limit_spin_box.setValue(200)
    ui(page).resource_limit_spin_box.setValue(0)

    assert not ui(page).clamp_note_label.isVisible()
    assert ui(page).clamp_note_label.text() == ""


def test_zero_saves_through_to_the_shared_settings(page: LogsPage) -> None:
    """Zero is a value like any other on the way out of this page.

    **Test steps:**

    * Set the resource limit to zero and save.
    * Assert the shared settings hold it, and hand out no cap.
    """
    ui(page).resource_limit_spin_box.setValue(0)

    page.save_changes()

    settings = shared_logs_settings()
    assert settings.resource_limit == 0
    assert settings.effective_resource_limit is None


# endregion
