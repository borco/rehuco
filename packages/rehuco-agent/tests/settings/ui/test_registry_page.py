"""Tests for RegistryPage: the Registry settings category page (#47)."""

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

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
def test_title_is_system_integration(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The page's category-tree title is "System Integration" (#76).

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    page = registry_page.RegistryPage((".zip",))
    qtbot.addWidget(page)

    assert page.title == "System Integration"


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
    frame_filter = SettingsFrameFilter(page, page.title)

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
