"""Tests for DesktopIntegrationPage: the Linux System Integration settings category page (#209).

No ``importorskip`` guard, unlike ``test_registry_page.py``: everything this page touches is
mockable ``pathlib``/``subprocess`` code, so it constructs and behaves the same on any OS.
"""

from pathlib import Path
from typing import Any, Final

from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui import desktop_integration_page
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter

LINUX_REGISTRATION: Final = "rehuco_agent.linux_registration"

EXE_PATH: Final = Path("/fake/home/.local/bin/rehuco-agent")
OTHER_COMMAND: Final = '"/fake/downloads/Rehuco-x86_64.AppImage" %F'
BLOCKER: Final = "Cannot register/unregister -- running inside Flatpak."


def build_page(
    qtbot: QtBot,
    mocker: MockerFixture,
    register_blocker: str | None = None,
    unregister_blocker: str | None = None,
) -> tuple[desktop_integration_page.DesktopIntegrationPage, Any]:
    """Construct the page with its executable path and both blockers mocked out.

    :param qtbot: pytest-qt fixture, given ownership of the widget.
    :param mocker: pytest-mock fixture.
    :param register_blocker: what ``registration_blocker`` should report; ``None`` allows registering.
    :param unregister_blocker: what ``unregistration_blocker`` should report; ``None`` allows
        unregistering/checking.
    :returns: the page and its generated ``Ui_`` object, which every assertion below reads --
        typed ``Any`` because that class lives in a gitignored, generated module.
    """
    mocker.patch(f"{LINUX_REGISTRATION}.executable_path", return_value=EXE_PATH)
    mocker.patch(f"{LINUX_REGISTRATION}.registration_blocker", return_value=register_blocker)
    mocker.patch(f"{LINUX_REGISTRATION}.unregistration_blocker", return_value=unregister_blocker)

    page = desktop_integration_page.DesktopIntegrationPage()
    qtbot.addWidget(page)
    return page, page._DesktopIntegrationPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_status_starts_as_not_checked_when_registration_is_possible(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A fresh page with nothing blocking it starts "not checked yet", with every button enabled.

    **Test steps:**

    * construct the page with no blocker
    * verify the status label and that every button is enabled
    """
    _, ui = build_page(qtbot, mocker)

    assert ui.status_label.text() == desktop_integration_page.NOT_CHECKED_STATUS
    assert ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


def test_all_buttons_disabled_and_the_reason_shown_when_sandboxed(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A sandbox disables every button and shows why -- the app can't touch the host's XDG
    directories at all, register, unregister or check.

    The reason is `linux_registration`'s own sentence, not a copy -- a false "Registered." inside a
    sandbox would be worse than an honest refusal.

    **Test steps:**

    * construct the page with both blockers reporting the sandbox
    * verify the status label repeats it and every button is disabled
    """
    _, ui = build_page(qtbot, mocker, register_blocker=BLOCKER, unregister_blocker=BLOCKER)

    assert ui.status_label.text() == BLOCKER
    assert not ui.register_button.isEnabled()
    assert not ui.unregister_button.isEnabled()
    assert not ui.check_button.isEnabled()


def test_only_register_disabled_when_not_running_from_an_executable(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A source checkout disables only "Register" -- unregistering and checking status never
    depend on ``exe_path`` being launchable, only actually registering does.

    **Test steps:**

    * construct the page with only ``registration_blocker`` reporting a reason
    * verify the status label repeats it, "Register" is disabled, and the other two stay enabled
    """
    _, ui = build_page(qtbot, mocker, register_blocker=BLOCKER)

    assert ui.status_label.text() == BLOCKER
    assert not ui.register_button.isEnabled()
    assert ui.unregister_button.isEnabled()
    assert ui.check_button.isEnabled()


def test_register_button_registers_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Register" registers the launched executable and shows the registered status.

    **Test steps:**

    * construct the page and mock ``register``
    * click "Register"
    * verify ``register`` was called with the executable path and the status shows registered
    """
    register = mocker.patch(f"{LINUX_REGISTRATION}.register")
    _, ui = build_page(qtbot, mocker)

    ui.register_button.click()

    register.assert_called_once_with(EXE_PATH)
    assert ui.status_label.text() == desktop_integration_page.REGISTERED_STATUS


def test_unregister_button_unregisters_and_updates_status(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Clicking "Unregister" removes the registration and shows the not-registered status.

    **Test steps:**

    * construct the page and mock ``unregister``
    * click "Unregister"
    * verify ``unregister`` was called once and the status shows not registered
    """
    unregister = mocker.patch(f"{LINUX_REGISTRATION}.unregister")
    _, ui = build_page(qtbot, mocker)

    ui.unregister_button.click()

    unregister.assert_called_once_with()
    assert ui.status_label.text() == desktop_integration_page.NOT_REGISTERED_STATUS


def test_check_button_shows_registered_when_everything_matches(qtbot: QtBot, mocker: MockerFixture) -> None:
    """ "Check registration" reports registered when all three installed files match.

    **Test steps:**

    * mock ``is_registered`` to report ``True``
    * construct the page and click "Check registration"
    * verify the status shows registered
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=True)
    _, ui = build_page(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == desktop_integration_page.REGISTERED_STATUS


def test_check_button_shows_not_registered_when_no_entry_exists(qtbot: QtBot, mocker: MockerFixture) -> None:
    """With no desktop entry installed at all, the status is a plain "not registered".

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` ``None``
    * construct the page and click "Check registration"
    * verify the status shows not registered
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=None)
    _, ui = build_page(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == desktop_integration_page.NOT_REGISTERED_STATUS


def test_check_button_names_the_other_location(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An entry launching something else is reported as such, naming it and the fix.

    The ordinary case for an AppImage, which the user may move, rename or replace with a newer
    download -- each of which silently invalidates the recorded ``Exec``.

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` to report another path
    * construct the page and click "Check registration"
    * verify the status names that command
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=OTHER_COMMAND)
    _, ui = build_page(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == desktop_integration_page.REGISTERED_ELSEWHERE_STATUS.format(command=OTHER_COMMAND)


def test_check_button_reports_a_stale_registration(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An entry launching *this* path but otherwise out of date is reported as stale, not as elsewhere.

    Happens after an app update that changed the icon or the MIME comment: the ``Exec`` still
    matches, so "a different location" would be a lie.

    **Test steps:**

    * mock ``is_registered`` ``False`` and ``registered_command`` to report this page's own command
    * construct the page and click "Check registration"
    * verify the status is the stale one
    """
    mocker.patch(f"{LINUX_REGISTRATION}.is_registered", return_value=False)
    mocker.patch(f"{LINUX_REGISTRATION}.registered_command", return_value=f'"{EXE_PATH}" %F')
    _, ui = build_page(qtbot, mocker)

    ui.check_button.click()

    assert ui.status_label.text() == desktop_integration_page.STALE_STATUS


def test_title_is_system_integration(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The page's category-tree title matches the Windows page's, since they fill the same slot (#76).

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page, _ = build_page(qtbot, mocker)

    assert page.title == "System Integration"


def test_frame_filter_discovers_the_registration_frame_and_its_text(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A `SettingsFrameFilter` finds the page's registration frame and filters it by its text (#67).

    Guards the page's ``.ui`` frame structure: the registration frame must be a discoverable
    top-level frame whose gathered caption text includes its actions.

    **Test steps:**

    * build a frame filter over the page
    * verify its text includes an action, then filter by nothing-matching text and check it hides
    """
    page, ui = build_page(qtbot, mocker)
    frame_filter = SettingsFrameFilter(page, page.title)

    assert any("register" in text for text in frame_filter.field_labels())

    frame_filter.apply("zzz", show_full_on_title_match=False)
    assert ui.registration_frame.isVisibleTo(page) is False


def test_is_dirty_is_always_false(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The page is never dirty -- register/unregister act immediately, nothing is staged.

    **Test steps:**

    * construct the page
    * verify ``is_dirty`` is ``False``
    """
    page, _ = build_page(qtbot, mocker)

    assert page.is_dirty() is False


def test_save_and_drop_changes_are_no_ops(qtbot: QtBot, mocker: MockerFixture) -> None:
    """``save_changes``/``drop_changes`` do nothing and don't raise.

    **Test steps:**

    * construct the page
    * call both methods
    * verify neither raises and the status label is untouched
    """
    page, ui = build_page(qtbot, mocker)

    page.save_changes()
    page.drop_changes()

    assert ui.status_label.text() == desktop_integration_page.NOT_CHECKED_STATUS
