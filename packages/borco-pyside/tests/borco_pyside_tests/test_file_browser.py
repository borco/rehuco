"""Tests for `~borco_pyside.file_browser.reveal_in_file_browser` (#314).

Every platform branch is exercised by forcing ``sys.platform`` rather than relying on the runner's real
OS -- the same dispatch-testing shape as `~borco_pyside.recycle_bin`'s own tests: which branch runs is
this module's own logic, and a forced value proves it without needing three runners.
"""

from pathlib import Path
from typing import Final

from borco_pyside.file_browser import reveal_in_file_browser
from pytest_mock import MockerFixture

FILE: Final = Path("/fake/tutorial/info.rehu")
PARENT: Final = FILE.parent


def exists_only(*paths: Path) -> object:
    """Build a ``Path.exists`` side effect that answers ``True`` only for the given paths.

    :param paths: the paths ``exists()`` should report as present.
    :returns: a callable suitable as ``mocker.patch.object(Path, "exists", side_effect=...)``.
    """
    return lambda self: self in paths


# region existing file


def test_windows_selects_an_existing_file(mocker: MockerFixture) -> None:
    """On Windows, an existing file is revealed selected with Explorer's ``/select`` switch.

    **Test steps:**

    * force Windows and an existing file
    * reveal it
    * verify Explorer was launched with ``/select,`` and the native-separator path as separate args
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "win32")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(FILE))
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(FILE) is True

    start.assert_called_once_with("explorer.exe", ["/select,", str(FILE)])


def test_macos_selects_an_existing_file(mocker: MockerFixture) -> None:
    """On macOS, an existing file is revealed selected with ``open -R``.

    **Test steps:**

    * force macOS and an existing file
    * reveal it
    * verify ``open -R <file>`` was launched
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "darwin")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(FILE))
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(FILE) is True

    start.assert_called_once_with("open", ["-R", str(FILE)])


def test_linux_selects_an_existing_file_over_dbus(mocker: MockerFixture) -> None:
    """On Linux, an existing file is revealed selected through ``FileManager1.ShowItems`` over D-Bus.

    **Test steps:**

    * force Linux, an existing file, and a D-Bus session bus that accepts the message
    * reveal it
    * verify ``ShowItems`` was called with the file's URI and ``xdg-open`` was never reached
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "linux")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(FILE))
    message = mocker.patch("PySide6.QtDBus.QDBusMessage.createMethodCall").return_value
    session_bus = mocker.patch("PySide6.QtDBus.QDBusConnection.sessionBus").return_value
    session_bus.send.return_value = True
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached")

    assert reveal_in_file_browser(FILE) is True

    message.setArguments.assert_called_once()
    args = message.setArguments.call_args[0][0]
    assert args[0] == [f"file://{FILE.as_posix()}"]
    start.assert_not_called()


def test_linux_falls_back_to_xdg_open_when_dbus_is_unreachable(mocker: MockerFixture) -> None:
    """On Linux, a D-Bus send that fails (no file manager answering) falls back to ``xdg-open``.

    **Test steps:**

    * force Linux, an existing file, and a D-Bus session bus that refuses the message
    * reveal it
    * verify ``xdg-open`` was launched against the file's folder -- on the file itself it would launch
      the file's own handler, not a file manager
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "linux")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(FILE))
    mocker.patch("PySide6.QtDBus.QDBusMessage.createMethodCall")
    session_bus = mocker.patch("PySide6.QtDBus.QDBusConnection.sessionBus").return_value
    session_bus.send.return_value = False
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(FILE) is True

    start.assert_called_once_with("xdg-open", [str(PARENT)])


def test_a_folder_is_opened_rather_than_selected_in_its_parent(mocker: MockerFixture) -> None:
    """A folder -- what the Files sub-dock hands in -- opens on its own contents; ``/select`` would open
    its parent with the folder merely highlighted, which is not where the reader was standing.

    **Test steps:**

    * force Windows and an existing folder
    * reveal it
    * verify Explorer was launched against the folder, with no ``/select`` switch
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "win32")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(PARENT))
    mocker.patch.object(Path, "is_dir", autospec=True, side_effect=exists_only(PARENT))
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(PARENT) is True

    start.assert_called_once_with("explorer.exe", [str(PARENT)])


def test_a_folder_is_opened_rather_than_selected_on_macos(mocker: MockerFixture) -> None:
    """The same folder-opens-on-its-own-contents rule on macOS: ``open`` with no ``-R`` switch.

    **Test steps:**

    * force macOS and an existing folder
    * reveal it
    * verify ``open`` was launched against the folder, with no ``-R`` switch
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "darwin")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(PARENT))
    mocker.patch.object(Path, "is_dir", autospec=True, side_effect=exists_only(PARENT))
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(PARENT) is True

    start.assert_called_once_with("open", [str(PARENT)])


# endregion

# region missing file


def test_a_missing_file_reveals_its_parent_instead(mocker: MockerFixture) -> None:
    """A file gone missing out-of-band reveals its parent folder plainly, not a selection of nothing.

    **Test steps:**

    * force Windows, a missing file whose parent exists
    * reveal it
    * verify Explorer was launched against the parent, with no ``/select`` switch
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "win32")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only(PARENT))
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached", return_value=(True, 0))

    assert reveal_in_file_browser(FILE) is True

    start.assert_called_once_with("explorer.exe", [str(PARENT)])


def test_a_missing_parent_attempts_nothing(mocker: MockerFixture) -> None:
    """A folder missing too (the whole resource is gone) launches nothing.

    **Test steps:**

    * force Windows, with neither the file nor its parent existing
    * reveal it
    * verify nothing was launched and the call reported no attempt
    """
    mocker.patch("borco_pyside.file_browser.sys.platform", "win32")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=exists_only())
    start = mocker.patch("borco_pyside.file_browser.QProcess.startDetached")

    assert reveal_in_file_browser(FILE) is False

    start.assert_not_called()


# endregion
