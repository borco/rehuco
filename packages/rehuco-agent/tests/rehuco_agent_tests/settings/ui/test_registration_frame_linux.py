"""Tests for RegistrationFrameLinux: the Linux file-association frame of the System Integration page
(#209, #508).

No ``importorskip`` guard, unlike ``test_registration_frame_windows.py``: everything this frame touches is
mockable ``pathlib``/``subprocess`` code, so it constructs and behaves the same on any OS.
"""

from pathlib import Path
from typing import Any, Final

from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui import registration_frame_linux
from rehuco_agent.settings.ui.registration_frame_linux import RegistrationFrameLinux
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.system_integration_page import SystemIntegrationPage

LINUX_REGISTRATION: Final = "rehuco_agent.registration_linux"

EXE_PATH: Final = Path("/fake/home/.local/bin/rehuco-agent")
OTHER_COMMAND: Final = '"/fake/downloads/Rehuco-x86_64.AppImage" %F'
BLOCKER: Final = "Cannot register/unregister -- running inside Flatpak."


def build_frame(
    qtbot: QtBot,
    mocker: MockerFixture,
    register_blocker: str | None = None,
    unregister_blocker: str | None = None,
) -> tuple[RegistrationFrameLinux, Any]:
    """Construct the frame with its executable path and both blockers mocked out.

    :param qtbot: pytest-qt fixture, given ownership of the frame's widget.
    :param mocker: pytest-mock fixture.
    :param register_blocker: what ``registration_blocker`` should report; ``None`` allows registering.
    :param unregister_blocker: what ``unregistration_blocker`` should report; ``None`` allows
        unregistering/checking.
    :returns: the frame and its generated ``Ui_`` object, which every assertion below reads --
        typed ``Any`` because that class lives in a gitignored, generated module.
    """
    mocker.patch(f"{LINUX_REGISTRATION}.executable_path", return_value=EXE_PATH)
    mocker.patch(f"{LINUX_REGISTRATION}.registration_blocker", return_value=register_blocker)
    mocker.patch(f"{LINUX_REGISTRATION}.unregistration_blocker", return_value=unregister_blocker)

    frame = RegistrationFrameLinux()
    qtbot.addWidget(frame.frame)
    return frame, frame._RegistrationFrameLinux__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_status_starts_as_not_checked_when_registration_is_possible(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh frame with nothing blocking it starts "not checked yet", with every button enabled.

    **Test steps:**

    * construct the frame with no blocker
    * verify the status label and that every button is enabled
    """
    _, ui = build_frame(qtbot, mocker)

    assert ui.status_label.text() == registration_frame_linux.NOT_CHECKED_STATUS
    assert ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


def test_all_buttons_disabled_and_the_reason_shown_when_sandboxed(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A sandbox disables every button and shows why -- the app can't touch the host's XDG
    directories at all, register, unregister or check.

    The reason is `registration_linux`'s own sentence, not a copy -- a false "Registered." inside a
    sandbox would be worse than an honest refusal.

    **Test steps:**

    * construct the frame with both blockers reporting the sandbox
    * verify the status label repeats it and every button is disabled
    """
    _, ui = build_frame(qtbot, mocker, register_blocker=BLOCKER, unregister_blocker=BLOCKER)

    assert ui.status_label.text() == BLOCKER
    assert not ui.register_button.isEnabled()
    assert not ui.unregister_button.isEnabled()
    assert not ui.check_button.isEnabled()


def test_only_register_disabled_when_not_running_from_an_executable(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A source checkout disables only "Register" -- unregistering and checking status never
    depend on ``exe_path`` being launchable, only actually registering does.

    **Test steps:**

    * construct the frame with only ``registration_blocker`` reporting a reason
    * verify the status label repeats it, "Register" is disabled, and the other two stay enabled
    """
    _, ui = build_frame(qtbot, mocker, register_blocker=BLOCKER)

    assert ui.status_label.text() == BLOCKER
    assert not ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


def test_register_button_registers_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Register" registers the launched executable and shows the registered status.

    **Test steps:**

    * construct the frame and mock ``register``
    * click "Register"
    * verify ``register`` was called with the executable path and the status shows registered
    """
    register = mocker.patch(f"{LINUX_REGISTRATION}.register")
    _, ui = build_frame(qtbot, mocker)

    ui.register_button.click()

    register.assert_called_once_with(EXE_PATH)
    assert ui.status_label.text() == registration_frame_linux.REGISTERED_STATUS


def test_unregister_button_unregisters_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Unregister" removes the registration and shows the not-registered status.

    **Test steps:**

    * construct the frame and mock ``unregister``
    * click "Unregister"
    * verify ``unregister`` was called once and the status shows not registered
    """
    unregister = mocker.patch(f"{LINUX_REGISTRATION}.unregister")
    _, ui = build_frame(qtbot, mocker)

    ui.unregister_button.click()

    unregister.assert_called_once_with()
    assert ui.status_label.text() == registration_frame_linux.NOT_REGISTERED_STATUS


def test_check_button_shows_registered_when_everything_matches(qtbot: QtBot, mocker: MockerFixture) -> None:
    """ "Check registration" reports registered when all three installed files match.

    **Test steps:**

    * mock ``is_registered`` to report ``True``
    * construct the frame and click "Check registration"
    * verify the status shows registered
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=True)
    _, ui = build_frame(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_linux.REGISTERED_STATUS


def test_check_button_shows_not_registered_when_no_entry_exists(qtbot: QtBot, mocker: MockerFixture) -> None:
    """With no desktop entry installed at all, the status is a plain "not registered".

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` ``None``
    * construct the frame and click "Check registration"
    * verify the status shows not registered
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=None)
    _, ui = build_frame(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_linux.NOT_REGISTERED_STATUS


def test_check_button_names_the_other_location(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An entry launching something else is reported as such, naming it and the fix.

    The ordinary case for an AppImage, which the user may move, rename or replace with a newer
    download -- each of which silently invalidates the recorded ``Exec``.

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` to report another path
    * construct the frame and click "Check registration"
    * verify the status names that command
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=OTHER_COMMAND)
    _, ui = build_frame(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_linux.REGISTERED_ELSEWHERE_STATUS.format(command=OTHER_COMMAND)


def test_check_button_reports_a_stale_registration(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An entry launching *this* path but otherwise out of date is reported as stale, not as elsewhere.

    Happens after an app update that changed the icon or the MIME comment: the ``Exec`` still
    matches, so "a different location" would be a lie.

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` to report this page's own command
    * construct the frame and click "Check registration"
    * verify the status is the stale one
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=f'"{EXE_PATH}" %F')
    _, ui = build_frame(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == registration_frame_linux.STALE_STATUS


def test_the_page_adopts_the_frame_as_a_block_the_filter_finds_and_hides(qtbot: QtBot, mocker: MockerFixture) -> None:
    """On a `SystemIntegrationPage`, the frame is the first block, and a `SettingsFrameFilter` matches it by its
    text and hides it when nothing matches (#67, #508).

    **Test steps:**

    * build a page around the frame and a frame filter over it
    * verify the first block's text includes an action, then filter by nothing-matching text and check it hides
    """
    frame, _ = build_frame(qtbot, mocker)
    page = SystemIntegrationPage(None, [frame.frame])
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, "System Integration")

    assert frame_filter.blocks()[0] is frame.frame
    assert "Register" in frame_filter.field_labels()[0]

    frame_filter.apply("zzz", show_full_on_title_match=False)
    assert frame.frame.isVisibleTo(page) is False
