"""Tests for RegistrationFrameWindows: the Windows file-association frame of the System Integration page
(#47, #508)."""

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from pytestqt.qtbot import QtBot  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.settings.ui import registration_frame_windows  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.settings.ui.registration_frame_windows import (  # noqa: E402  # pylint: disable=wrong-import-position
    RegistrationFrameWindows,
)
from rehuco_agent.settings.ui.settings_frame_filter import (  # noqa: E402  # pylint: disable=wrong-import-position
    SettingsFrameFilter,
)
from rehuco_agent.settings.ui.system_integration_page import (  # noqa: E402  # pylint: disable=wrong-import-position
    SystemIntegrationPage,
)

WINDOWS_REGISTRATION = "rehuco_agent.registration_windows"


@mark.windows
def test_status_starts_as_not_checked_when_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh frame, running from a real exe, starts with the "not checked yet" status and enabled
    buttons.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``True``
    * construct the frame
    * verify the status label and that every button is enabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)

    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.status_label.text() == registration_frame_windows.NOT_CHECKED_STATUS
    assert ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


@mark.windows
def test_buttons_disabled_when_not_running_from_exe(qtbot: QtBot, mocker: MockerFixture) -> None:
    """When not running from a real exe (e.g. ``python -m rehuco_agent``), every button starts
    disabled and the status explains why.

    **Test steps:**

    * mock ``is_running_from_exe`` to report ``False``
    * construct the frame
    * verify the status label and that every button is disabled
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=False)

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)

    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.status_label.text() == registration_frame_windows.NOT_RUNNING_FROM_EXE_STATUS
    assert not ui.register_button.isEnabled()
    assert not ui.unregister_button.isEnabled()
    assert not ui.check_button.isEnabled()


@mark.windows
def test_register_button_registers_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Register" calls ``registration_windows.register`` and shows the registered status.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``register``
    * construct the frame and click "Register"
    * verify ``register`` was called once and the status shows registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    register = mocker.patch(f"{WINDOWS_REGISTRATION}.register")

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)
    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.register_button.click()

    register.assert_called_once()
    assert ui.status_label.text() == registration_frame_windows.REGISTERED_STATUS


@mark.windows
def test_unregister_button_unregisters_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Unregister" calls ``registration_windows.unregister`` and shows the
    not-registered status.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``unregister``
    * construct the frame and click "Unregister"
    * verify ``unregister`` was called once and the status shows not registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    unregister = mocker.patch(f"{WINDOWS_REGISTRATION}.unregister")

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)
    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.unregister_button.click()

    unregister.assert_called_once()
    assert ui.status_label.text() == registration_frame_windows.NOT_REGISTERED_STATUS


@mark.windows
def test_check_button_shows_registered_when_true(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Check registration" shows the registered status when ``is_registered`` reports
    ``True``.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``is_registered`` (``True``)
    * construct the frame and click "Check registration"
    * verify the status shows registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_registered", return_value=True)

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)
    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_windows.REGISTERED_STATUS


@mark.windows
def test_check_button_shows_not_registered_when_false(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Check registration" shows the not-registered status when ``is_registered``
    reports ``False``.

    **Test steps:**

    * mock ``is_running_from_exe`` (``True``) and ``is_registered`` (``False``)
    * construct the frame and click "Check registration"
    * verify the status shows not registered
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_registered", return_value=False)

    frame = registration_frame_windows.RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)
    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_windows.NOT_REGISTERED_STATUS


@mark.windows
def test_the_frame_is_titled_for_what_it_does(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The frame is titled "Windows File Explorer integration" (#363 put a second Windows frame under it).

    **Test steps:**

    * construct the frame
    * verify its title
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)

    frame = RegistrationFrameWindows((".zip",))
    qtbot.addWidget(frame.frame)
    ui = frame._RegistrationFrameWindows__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.frame_label.text() == "Windows File Explorer integration"


@mark.windows
def test_the_page_adopts_the_frame_as_a_block_the_filter_finds_and_hides(qtbot: QtBot, mocker: MockerFixture) -> None:
    """On a `SystemIntegrationPage`, the frame is the first block, and a `SettingsFrameFilter` matches it by its
    text and hides it when nothing matches (#67, #508).

    **Test steps:**

    * build a page around the frame and a frame filter over it
    * verify the first block's text includes an action, then filter by nothing-matching text and check it hides
    """
    mocker.patch(f"{WINDOWS_REGISTRATION}.is_running_from_exe", return_value=True)
    frame = RegistrationFrameWindows((".zip",))
    page = SystemIntegrationPage(None, [frame.frame])
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "System Integration")

    assert frame_filter.blocks()[0] is frame.frame
    assert "Register" in frame_filter.field_labels()[0]

    frame_filter.apply("zzz", show_full_on_title_match=False)
    assert frame.frame.isVisibleTo(page) is False
