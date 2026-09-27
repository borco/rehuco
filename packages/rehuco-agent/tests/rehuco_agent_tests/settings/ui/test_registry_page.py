"""Tests for RegistryPage: the Registry settings category page (#47), and its crash-dumps
frame (#363)."""

import sys
from pathlib import Path

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from PySide6.QtCore import QUrl  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from pytestqt.qtbot import QtBot  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.settings.tray_settings import (  # noqa: E402  # pylint: disable=wrong-import-position
    shared_tray_settings,
)
from rehuco_agent.settings.ui import registry_page  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.settings.ui.settings_frame_filter import (  # noqa: E402  # pylint: disable=wrong-import-position
    SettingsFrameFilter,
)

WINDOWS_REGISTRATION = "rehuco_agent.windows_registration"
CRASH_DUMPS = "rehuco_agent.crash_dumps"
DUMPS_FOLDER = Path("/fake/borco/rehuco-agent/crashdumps")


@mark.windows
def test_status_starts_as_not_checked_when_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh page, running from a real exe, starts with the "not checked yet" status and enabled
    buttons.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``True``
    * construct the page
    * verify the status label and that every button is enabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.status_label.text() == registry_page.NOT_CHECKED_STATUS
    assert ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


@mark.windows
def test_buttons_disabled_when_not_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """When not running from a real exe (e.g. ``python -m rehuco_agent``), every button starts
    disabled and the status explains why.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``False``
    * construct the page
    * verify the status label and that every button is disabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=False)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.status_label.text() == registry_page.NOT_RUNNING_FROM_EXE_STATUS
    assert not ui.register_button.isEnabled()
    assert not ui.unregister_button.isEnabled()
    assert not ui.check_button.isEnabled()


@mark.windows
def test_register_button_registers_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Register" calls ``windows_registration.register`` and shows the registered status.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``register``
    * construct the page and click "Register"
    * verify ``register`` was called once and the status shows registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    register = mocker.patch(f"{WINDOWS_REGISTRATION}.register")

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.register_button.click()

    register.assert_called_once()
    assert ui.status_label.text() == registry_page.REGISTERED_STATUS


@mark.windows
def test_unregister_button_unregisters_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Unregister" calls ``windows_registration.unregister`` and shows the
    not-registered status.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``unregister``
    * construct the page and click "Unregister"
    * verify ``unregister`` was called once and the status shows not registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    unregister = mocker.patch(f"{WINDOWS_REGISTRATION}.unregister")

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.unregister_button.click()

    unregister.assert_called_once()
    assert ui.status_label.text() == registry_page.NOT_REGISTERED_STATUS


@mark.windows
def test_check_button_shows_registered_when_true(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Check registration" shows the registered status when ``is_registered`` reports
    ``True``.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``is_registered`` (``True``)
    * construct the page and click "Check registration"
    * verify the status shows registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_registered", return_value=True)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.check_button.click()

    assert ui.status_label.text() == registry_page.REGISTERED_STATUS


@mark.windows
def test_check_button_shows_not_registered_when_false(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Check registration" shows the not-registered status when ``is_registered``
    reports ``False``.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``is_registered`` (``False``)
    * construct the page and click "Check registration"
    * verify the status shows not registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_registered", return_value=False)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.check_button.click()

    assert ui.status_label.text() == registry_page.NOT_REGISTERED_STATUS


@mark.windows
def test_frame_filter_discovers_the_registration_frame_and_its_text(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A `SettingsFrameFilter` finds the page's registration frame and filters it by its text (#67).

    Guards the page's ``.ui`` frame structure: the registration frame must be a discoverable
    top-level frame whose gathered caption text includes its actions.

    **Test steps:**

    * build a frame filter over the page
    * verify its text includes an action, then filter by nothing-matching text and check it hides
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "System Integration")

    assert any("register" in text for text in frame_filter.field_labels())

    frame_filter.apply("zzz", show_full_on_title_match=False)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.registration_frame.isVisibleTo(page) is False


@mark.windows
def test_is_dirty_is_false_with_the_tray_checkbox_untouched(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A freshly-built page is clean: the registration buttons stage nothing, and the tray checkbox
    starts on what is saved (#205).

    **Test steps:**

    * construct the page
    * verify ``is_dirty`` is ``False``
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    assert page.is_dirty() is False


@mark.windows
def test_is_dirty_follows_the_tray_checkbox(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Toggling the tray checkbox makes the page dirty -- it is this page's one staged control
    since Tray merged into System Integration (#205).

    **Test steps:**

    * construct the page and toggle the tray checkbox
    * verify ``is_dirty`` is ``True``
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.enabled_check_box.setChecked(True)

    assert page.is_dirty() is True


@mark.windows
def test_save_changes_applies_the_tray_choice_and_drop_changes_reverts_it(qtbot: QtBot, mocker: MockerFixture) -> None:
    """``save_changes`` pushes the staged tray choice into the shared settings; ``drop_changes``
    puts the checkbox back. Neither disturbs the registration controls above them (#205).

    **Test steps:**

    * construct the page, check the tray box and save
    * verify the shared settings took it and the page is clean
    * toggle again and drop
    * verify the checkbox is back and the status label was never touched
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.enabled_check_box.setChecked(True)
    page.save_changes()

    assert shared_tray_settings().enabled is True
    assert page.is_dirty() is False

    ui.enabled_check_box.setChecked(False)
    page.drop_changes()

    assert ui.enabled_check_box.isChecked() is True
    assert ui.status_label.text() == registry_page.NOT_CHECKED_STATUS


@mark.windows
def test_seed_defaults_stages_the_tray_off_over_a_saved_on(qtbot: QtBot, mocker: MockerFixture) -> None:
    """``seed_defaults`` shows the factory value -- tray off -- as a staged edit against a saved on,
    and leaves the registration controls alone (#342).

    **Test steps:**

    * save the tray on and construct the page
    * call ``seed_defaults``
    * verify the box is unchecked, the page is dirty, and the status label was never touched
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    shared_tray_settings().enabled = True
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.enabled_check_box.isChecked() is True

    page.seed_defaults()

    assert ui.enabled_check_box.isChecked() is False
    assert page.is_dirty() is True
    assert ui.status_label.text() == registry_page.NOT_CHECKED_STATUS


@mark.windows
def test_dumps_status_starts_as_not_checked_when_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh page, running from a real exe, starts the crash-dumps frame with "not checked yet" and
    every crash-dump button enabled.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``True``
    * construct the page
    * verify the crash-dumps status label and that every crash-dump button is enabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.crash_dumps_status_label.text() == registry_page.NOT_CHECKED_DUMPS_STATUS
    assert ui.enable_dumps_button.isEnabled()
    assert ui.disable_dumps_button.isEnabled()
    assert ui.check_dumps_button.isEnabled()


@mark.windows
def test_dumps_buttons_disabled_when_not_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """When not running from a real exe, every crash-dump button starts disabled and the status
    explains why -- the same guard as the file-association buttons, since either would name
    ``python.exe`` instead of the app.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``False``
    * construct the page
    * verify the crash-dumps status label and that every crash-dump button is disabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=False)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.crash_dumps_status_label.text() == registry_page.NOT_RUNNING_FROM_EXE_DUMPS_STATUS
    assert not ui.enable_dumps_button.isEnabled()
    assert not ui.disable_dumps_button.isEnabled()
    assert not ui.check_dumps_button.isEnabled()


@mark.windows
def test_enable_dumps_button_enables_then_shows_the_read_back_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Enable crash dumps" calls ``crash_dumps.enable`` for the running exe's own name,
    then shows the status from a fresh ``is_enabled`` read-back -- never from the subprocess call's
    own (unobserved) result.

    **Test steps:**

    * mock ``is_running_from_exe``, ``enable`` and ``is_enabled`` (reporting enabled, expected folder)
    * construct the page and click "Enable crash dumps"
    * verify ``enable`` was called with the running exe's file name and the status shows kept
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    enable = mocker.patch(f"{CRASH_DUMPS}.enable")
    mocker.patch(f"{CRASH_DUMPS}.is_enabled", return_value=(True, DUMPS_FOLDER))

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.enable_dumps_button.click()

    enable.assert_called_once_with(Path(sys.argv[0]).resolve().name)
    assert ui.crash_dumps_status_label.text() == registry_page.ENABLED_DUMPS_STATUS


@mark.windows
def test_disable_dumps_button_disables_then_shows_the_read_back_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Disable crash dumps" calls ``crash_dumps.disable``, then shows "not kept" from a
    fresh ``is_enabled`` read-back.

    **Test steps:**

    * mock ``is_running_from_exe``, ``disable`` and ``is_enabled`` (reporting not enabled)
    * construct the page and click "Disable crash dumps"
    * verify ``disable`` was called once and the status shows not kept
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    disable = mocker.patch(f"{CRASH_DUMPS}.disable")
    mocker.patch(f"{CRASH_DUMPS}.is_enabled", return_value=(False, None))

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.disable_dumps_button.click()

    disable.assert_called_once()
    assert ui.crash_dumps_status_label.text() == registry_page.DISABLED_DUMPS_STATUS


@mark.windows
def test_check_dumps_button_reports_a_key_pointing_elsewhere(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Check crash dumps" reports a key that points somewhere other than the expected
    folder (e.g. set by hand), and shows that other folder instead.

    **Test steps:**

    * mock ``is_running_from_exe`` and ``is_enabled`` (reporting enabled, a different folder)
    * construct the page and click "Check crash dumps"
    * verify the status names the other folder, and the shown folder switches to it
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    other_folder = Path("/fake/elsewhere/dumps")
    mocker.patch(f"{CRASH_DUMPS}.is_enabled", return_value=(True, other_folder))

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.check_dumps_button.click()

    assert ui.crash_dumps_status_label.text() == registry_page.ENABLED_ELSEWHERE_DUMPS_STATUS.format(
        folder=other_folder
    )
    shown_folder = page._RegistryPage__shown_dumps_folder  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert shown_folder == other_folder


@mark.windows
def test_dumps_usage_says_no_dumps_yet_and_disables_clear_by_default(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh page, before any dump exists, shows "No dumps yet" and starts Clear disabled.

    **Test steps:**

    * mock ``is_running_from_exe``
    * construct the page
    * verify the usage label and that Clear is disabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.crash_dumps_usage_label.text() == registry_page.NO_DUMPS_YET
    assert not ui.clear_dumps_button.isEnabled()


@mark.windows
def test_dumps_usage_sums_dump_file_sizes_and_enables_clear(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The usage line sums the reported dump files' sizes, and Clear becomes enabled once there is
    something to clear.

    **Test steps:**

    * mock ``is_running_from_exe`` and ``dump_files`` to report two files
    * construct the page
    * verify the usage label names both, and Clear is enabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    first = mocker.Mock(stat=mocker.Mock(return_value=mocker.Mock(st_size=1_000_000)))
    second = mocker.Mock(stat=mocker.Mock(return_value=mocker.Mock(st_size=2_000_000)))
    mocker.patch(f"{CRASH_DUMPS}.dump_files", return_value=[first, second])

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.crash_dumps_usage_label.text() == "3.0 MB in 2 dumps"
    assert ui.clear_dumps_button.isEnabled()


@mark.windows
def test_showing_the_page_re_reads_the_dumps_usage(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Showing the page re-reads the crash-dumps usage, since the folder grows while the page sits
    unopened in the dialog -- the same reason `LogsPage` re-reads its own log-file usage on show.

    **Test steps:**

    * construct the page with no dumps, then make ``dump_files`` report one and show the page
    * verify the usage label picks up the new count
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    dump_files = mocker.patch(f"{CRASH_DUMPS}.dump_files", return_value=[])

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.crash_dumps_usage_label.text() == registry_page.NO_DUMPS_YET

    one_file = mocker.Mock(stat=mocker.Mock(return_value=mocker.Mock(st_size=42)))
    dump_files.return_value = [one_file]
    page.show()

    assert "1 dump" in ui.crash_dumps_usage_label.text()


@mark.windows
def test_clear_dumps_button_clears_then_shows_what_is_left(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Clear crash dumps" calls ``crash_dumps.clear_dumps`` on the shown folder, then
    re-reads the usage.

    **Test steps:**

    * mock ``is_running_from_exe``, ``dump_files`` (one file) and a ``clear_dumps`` that empties it
    * construct the page and click "Clear crash dumps"
    * verify ``clear_dumps`` was called with the shown folder, and the usage line and Clear button
      show the emptied folder
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    one_file = mocker.Mock(stat=mocker.Mock(return_value=mocker.Mock(st_size=42)))
    dump_files = mocker.patch(f"{CRASH_DUMPS}.dump_files", return_value=[one_file])
    clear_dumps = mocker.patch(
        f"{CRASH_DUMPS}.clear_dumps", side_effect=lambda _folder: dump_files.configure_mock(return_value=[])
    )

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.clear_dumps_button.isEnabled()

    ui.clear_dumps_button.click()

    clear_dumps.assert_called_once_with(DUMPS_FOLDER)
    assert ui.crash_dumps_usage_label.text() == registry_page.NO_DUMPS_YET
    assert not ui.clear_dumps_button.isEnabled()


@mark.windows
def test_dumps_path_link_is_plain_text_before_the_folder_exists(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Before Windows creates the dumps folder, its path is shown as plain text, not a link.

    **Test steps:**

    * mock ``is_running_from_exe`` and a ``dumps_folder`` that never exists on this machine
    * construct the page
    * verify the label holds the plain path, not a rich-text anchor
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert "<a href" not in ui.crash_dumps_path_link.text()


@mark.windows
def test_dumps_path_link_reveals_the_folder_once_it_exists(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Once the dumps folder exists, its (possibly elided) path becomes a link, and activating it
    reveals that folder in the OS file browser.

    **Test steps:**

    * mock ``dumps_folder`` to a folder that really exists on this machine (this test file's own
      directory), and ``reveal_in_file_browser``
    * construct the page, then activate the link with its own ``href``
    * verify the reveal call received that same folder
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    real_folder = Path(__file__).resolve().parent
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=real_folder)
    reveal = mocker.patch("rehuco_agent.settings.ui.registry_page.reveal_in_file_browser")

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert "<a href" in ui.crash_dumps_path_link.text()

    ui.crash_dumps_path_link.linkActivated.emit(QUrl.fromLocalFile(str(real_folder)).toString())

    reveal.assert_called_once_with(real_folder)


@mark.windows
def test_showing_the_page_turns_the_path_into_a_link_once_the_folder_exists(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A folder that Windows creates (with the first dump) while the page sits unopened is picked up on
    show: the plain path becomes a link, alongside the re-read usage.

    **Test steps:**

    * stand in for the dumps folder with a path that does not exist at construction
    * make it exist, then show the page
    * verify the label went from plain text to a link
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    folder = mocker.MagicMock()
    folder.configure_mock(**{"__str__.return_value": str(DUMPS_FOLDER), "exists.return_value": False})
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=folder)
    mocker.patch(f"{CRASH_DUMPS}.dump_files", return_value=[])

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert "<a href" not in ui.crash_dumps_path_link.text()

    folder.exists.return_value = True
    page.show()

    assert f'href="{QUrl.fromLocalFile(str(DUMPS_FOLDER)).toString()}"' in ui.crash_dumps_path_link.text()


@mark.windows
def test_enable_status_comes_from_the_read_back_even_when_the_subprocess_failed(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A failed outer PowerShell (a cancelled UAC prompt, say) followed by a read-back that finds the
    key reports *kept*: the exit code is never what the status is built from.

    **Test steps:**

    * mock ``subprocess.run`` to fail and ``is_enabled`` to find the key at the expected folder
    * construct the page and click "Enable crash dumps"
    * verify the real ``enable`` ran the subprocess, and the status still shows kept
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    run = mocker.patch(f"{CRASH_DUMPS}.subprocess.run", return_value=mocker.Mock(returncode=1))
    mocker.patch(f"{CRASH_DUMPS}.is_enabled", return_value=(True, DUMPS_FOLDER))

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.enable_dumps_button.click()

    run.assert_called_once()
    assert ui.crash_dumps_status_label.text() == registry_page.ENABLED_DUMPS_STATUS


@mark.windows
def test_disable_status_comes_from_the_read_back_even_when_the_subprocess_succeeded(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The reverse: a subprocess that reports success followed by a read-back that still finds the key
    reports *kept* -- what the registry holds wins over what the subprocess claimed.

    **Test steps:**

    * mock ``subprocess.run`` to succeed and ``is_enabled`` to still find the key
    * construct the page and click "Disable crash dumps"
    * verify the real ``disable`` ran the subprocess, and the status shows kept
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{CRASH_DUMPS}.dumps_folder", return_value=DUMPS_FOLDER)
    run = mocker.patch(f"{CRASH_DUMPS}.subprocess.run", return_value=mocker.Mock(returncode=0))
    mocker.patch(f"{CRASH_DUMPS}.is_enabled", return_value=(True, DUMPS_FOLDER))

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.disable_dumps_button.click()

    run.assert_called_once()
    assert ui.crash_dumps_status_label.text() == registry_page.ENABLED_DUMPS_STATUS


@mark.windows
def test_frame_titles_name_file_explorer_integration_and_crash_dumps(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The first frame is titled for what it does now that a second Windows frame sits under it, and
    the second frame carries its own title (#363).

    **Test steps:**

    * construct the page
    * verify both frame titles
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)

    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.registration_frame_label.text() == "Windows File Explorer integration"
    assert ui.crash_dumps_frame_label.text() == "Windows crash dumps"


@mark.windows
def test_frame_filter_discovers_the_crash_dumps_frame_and_its_text(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A `SettingsFrameFilter` finds the crash-dumps frame as a top-level frame of its own and filters
    it by its text (#67) -- guarding the ``.ui`` structure the same way the registration frame's test does.

    **Test steps:**

    * build a frame filter over the page
    * verify its text includes a crash-dump action, then filter by nothing-matching text and check the
      frame hides
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "System Integration")

    assert any("crash dumps" in text for text in frame_filter.field_labels())

    frame_filter.apply("zzz", show_full_on_title_match=False)
    ui = page._RegistryPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.crash_dumps_frame.isVisibleTo(page) is False
