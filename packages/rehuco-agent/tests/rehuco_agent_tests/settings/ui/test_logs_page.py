"""Tests for LogsPage: the Logs settings category page (#200), and its run log file frame (#362)."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

from borco_pyside.logging import DEFAULT_LOG_LIMIT
from PySide6.QtCore import QUrl
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import logs_settings
from rehuco_agent.settings.logs_settings import (
    APP_LIMIT_KEY,
    DEFAULT_FILE_BACKUPS,
    DEFAULT_FILE_SIZE_MB,
    FILE_BACKUPS_KEY,
    FILE_SIZE_MB_KEY,
    GROUP,
    RESOURCE_LIMIT_KEY,
    shared_logs_settings,
)
from rehuco_agent.settings.ui import logs_page
from rehuco_agent.settings.ui.logs_page import NO_LOG_FILES, LogsPage
from rehuco_agent.settings.ui.settings_page import SettingsPage

FAKE_LOG_PATH: Final = str(Path("/fake/borco/rehuco-agent/rehuco-agent.log"))


# region fixtures
# Mirrors test_videos_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's settings-test convention.
# unsupported-assignment-operation: a false positive on the plain dict below, seen only once this module
# imports from PySide6.QtCore -- the same astroid misreading conftest.py's FakeSettings notes.
# pylint: disable=duplicate-code,unsupported-assignment-operation
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


# pylint: enable=duplicate-code,unsupported-assignment-operation


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


def make_log_file(exists: bool = True) -> MagicMock:
    """A stand-in for one of the handler's log files.

    :param exists: what it reports ``exists()`` as.
    :returns: the stand-in.
    """
    file = MagicMock(spec=Path)
    file.exists.return_value = exists
    return file


@fixture(autouse=True)
def handler(mocker: MockerFixture) -> MagicMock:
    """Stand in for the run log's handler, so the page never reads or clears a real log file.

    Starts with nothing written, the state of a freshly cleared log.

    :returns: the stand-in.
    """
    stand_in = mocker.MagicMock()
    stand_in.baseFilename = FAKE_LOG_PATH
    stand_in.log_files.return_value = [make_log_file(exists=False)]
    stand_in.used_bytes.return_value = 0
    mocker.patch.object(logs_page, "shared_run_log").return_value.handler = stand_in
    return stand_in


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


def test_seed_defaults_stages_the_factory_limits_over_saved_ones(page: LogsPage) -> None:
    """``seed_defaults`` shows the shipped limits as a staged edit against whatever is saved (#342).

    **Test steps:**

    * save two other limits and drop into them
    * call ``seed_defaults``
    * verify both spin boxes show the shipped limit and the page is dirty
    """
    settings = shared_logs_settings()
    settings.app_limit = 11
    settings.resource_limit = 7
    page.drop_changes()

    page.seed_defaults()

    assert ui(page).app_limit_spin_box.value() == DEFAULT_LOG_LIMIT
    assert ui(page).resource_limit_spin_box.value() == DEFAULT_LOG_LIMIT
    assert page.is_dirty()


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


# region the log file's size and backups


def test_starts_showing_the_saved_log_file_size_and_backups(page: LogsPage) -> None:
    """The log file frame opens on the values the running handler is using.

    **Test steps:**

    * Assert both spin boxes hold the defaults from empty storage.
    """
    assert ui(page).log_file_size_spin_box.value() == DEFAULT_FILE_SIZE_MB
    assert ui(page).log_file_backups_spin_box.value() == DEFAULT_FILE_BACKUPS


def test_offers_only_the_ranges_the_settings_accept(page: LogsPage) -> None:
    """The spin boxes cannot stage a value that loading would clamp away.

    **Test steps:**

    * Assert each spin box's range.
    """
    assert (ui(page).log_file_size_spin_box.minimum(), ui(page).log_file_size_spin_box.maximum()) == (1, 100)
    assert (ui(page).log_file_backups_spin_box.minimum(), ui(page).log_file_backups_spin_box.maximum()) == (1, 10)


def test_reports_a_changed_log_file_size_or_backup_count_as_dirty(page: LogsPage) -> None:
    """Either of the file's values typed is a staged change.

    **Test steps:**

    * Change the size, check dirty, drop it, then change the backup count and check again.
    """
    ui(page).log_file_size_spin_box.setValue(5)
    assert page.is_dirty()

    page.drop_changes()
    ui(page).log_file_backups_spin_box.setValue(4)
    assert page.is_dirty()


def test_saving_pushes_and_persists_the_log_file_values(page: LogsPage, fake_persistent_settings: FakeSettings) -> None:
    """Save lands on the shared settings, which the run log's handler follows, and in storage.

    **Test steps:**

    * Type both values and save.
    * Assert the shared settings and storage hold them, and the page is clean.
    """
    ui(page).log_file_size_spin_box.setValue(7)
    ui(page).log_file_backups_spin_box.setValue(3)

    page.save_changes()

    settings = shared_logs_settings()
    assert (settings.file_size_mb, settings.file_backups) == (7, 3)
    fake_persistent_settings.beginGroup(GROUP)
    assert fake_persistent_settings.value(FILE_SIZE_MB_KEY) == 7
    assert fake_persistent_settings.value(FILE_BACKUPS_KEY) == 3
    assert not page.is_dirty()


def test_seed_defaults_stages_the_factory_log_file_values(page: LogsPage) -> None:
    """``seed_defaults`` covers the log file frame too (#342).

    **Test steps:**

    * Save other values and drop into them, then seed the defaults.
    * Assert both spin boxes show the factory values and the page is dirty.
    """
    settings = shared_logs_settings()
    settings.file_size_mb = 50
    settings.file_backups = 9
    page.drop_changes()

    page.seed_defaults()

    assert ui(page).log_file_size_spin_box.value() == DEFAULT_FILE_SIZE_MB
    assert ui(page).log_file_backups_spin_box.value() == DEFAULT_FILE_BACKUPS
    assert page.is_dirty()


# endregion


# region the log file's location and usage


def test_shows_the_log_file_path_as_a_link(page: LogsPage) -> None:
    """The location is the handler's own file, shown as a link that reveals it.

    Read off the rendered ``href`` rather than the visible text, which may be elided in the small width
    a test widget gets -- the same reading ``test_scrapers_page.py`` gives its path links.

    **Test steps:**

    * Assert the link carries the handler's file as its target.
    """
    assert f'href="{QUrl.fromLocalFile(FAKE_LOG_PATH).toString()}"' in ui(page).log_file_path_link.text()


def test_the_path_link_reveals_the_log_file(page: LogsPage, mocker: MockerFixture) -> None:
    """Clicking the location opens the OS file browser on the file, rather than opening the file.

    **Test steps:**

    * Stand in for the reveal, and activate the link with the file's URL.
    * Assert the file was revealed.
    """
    reveal = mocker.patch.object(logs_page, "reveal_in_file_browser")

    ui(page).log_file_path_link.linkActivated.emit(QUrl.fromLocalFile(FAKE_LOG_PATH).toString())

    reveal.assert_called_once_with(Path(FAKE_LOG_PATH))


def test_says_nothing_is_written_when_no_file_exists(page: LogsPage) -> None:
    """A cleared log, before its next record, has no size to report.

    **Test steps:**

    * Assert the usage line says nothing is written.
    """
    assert ui(page).log_file_usage_label.text() == NO_LOG_FILES


def test_shows_the_space_used_and_the_number_of_files(page: LogsPage, handler: MagicMock) -> None:
    """The usage line is the total size across the file and its backups, and how many there are.

    Re-read on show, since the file grows while the page sits unopened in the dialog.

    **Test steps:**

    * Make the handler report three files and a total size, then hide and show the page.
    * Assert the usage line names both.
    """
    handler.log_files.return_value = [make_log_file(), make_log_file(), make_log_file()]
    handler.used_bytes.return_value = 2_500_000

    page.hide()
    page.show()

    assert ui(page).log_file_usage_label.text() == "2.5 MB in 3 files"


def test_a_single_file_is_named_in_the_singular(page: LogsPage, handler: MagicMock) -> None:
    """One file reads as *1 file*, not *1 files*.

    **Test steps:**

    * Make the handler report one file, then hide and show the page.
    * Assert the usage line is singular.
    """
    handler.log_files.return_value = [make_log_file()]
    handler.used_bytes.return_value = 1_000

    page.hide()
    page.show()

    assert ui(page).log_file_usage_label.text() == "1.0 kB in 1 file"


# endregion


# region clearing the log files


def test_clear_empties_the_log_files_and_rereads_the_usage(
    page: LogsPage, handler: MagicMock, caplog: LogCaptureFixture
) -> None:
    """Clear goes through the handler -- the one thing that can empty a file another process may hold
    -- and the usage line follows at once.

    **Test steps:**

    * Show some usage, then click Clear with the handler reporting nothing left.
    * Assert the handler cleared, the clear was logged, and the usage line says nothing is written.
    """
    handler.log_files.return_value = [make_log_file()]
    handler.used_bytes.return_value = 1_000
    page.hide()
    page.show()

    def clear() -> None:
        handler.log_files.return_value = [make_log_file(exists=False)]

    handler.clear.side_effect = clear
    with caplog.at_level(logging.INFO, logger="rehuco_agent.settings.ui.logs_page"):
        ui(page).clear_log_files_button.click()

    handler.clear.assert_called_once_with()
    assert any(record.message == "Log files cleared" for record in caplog.records)
    assert ui(page).log_file_usage_label.text() == NO_LOG_FILES


def test_a_failed_clear_is_logged_and_still_rereads_the_usage(
    page: LogsPage, handler: MagicMock, caplog: LogCaptureFixture
) -> None:
    """A clear that fails leaves the usage line saying what is still there, and a warning saying why.

    **Test steps:**

    * Make the clear fail, with a file still reported, and click Clear.
    * Assert a warning was logged and the usage line shows the file.
    """
    handler.clear.side_effect = OSError("locked")
    handler.log_files.return_value = [make_log_file()]
    handler.used_bytes.return_value = 1_000

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.settings.ui.logs_page"):
        ui(page).clear_log_files_button.click()

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert ui(page).log_file_usage_label.text() == "1.0 kB in 1 file"


# endregion
