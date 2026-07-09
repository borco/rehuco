"""Tests for the rehuco-agent CLI entry point (register/unregister/run dispatch)."""

from pathlib import Path
from typing import Final

import pytest

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from pytest import mark  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.__main__ import (  # noqa: E402  # pylint: disable=wrong-import-position
    AUMID,
    DIRECTORY_MENU_TEXT,
    DIRECTORY_SUB_KEY,
    EXTENSION,
    FRIENDLY_NAME,
    PROGID,
    main,
)

FAKE_EXE: Final = r"C:\fake\rehuco-agent-dev.exe"
FAKE_SCRIPT: Final = r"C:\fake\rehuco_agent\__main__.py"

FILE_ASSOCIATION_REGISTER: Final = "borco_core.platforms.windows.file_association.FileAssociation.register"
FILE_ASSOCIATION_UNREGISTER: Final = "borco_core.platforms.windows.file_association.FileAssociation.unregister"
DIRECTORY_CONTEXT_MENU: Final = "borco_core.platforms.windows.directory_context_menu.DirectoryContextMenu"
DIRECTORY_REGISTER_FOLDER: Final = f"{DIRECTORY_CONTEXT_MENU}.register_folder"
DIRECTORY_REGISTER_BACKGROUND: Final = f"{DIRECTORY_CONTEXT_MENU}.register_background"
DIRECTORY_UNREGISTER_FOLDER: Final = f"{DIRECTORY_CONTEXT_MENU}.unregister_folder"
DIRECTORY_UNREGISTER_BACKGROUND: Final = f"{DIRECTORY_CONTEXT_MENU}.unregister_background"


def expected_command_and_icon(exe: str) -> tuple[str, str, str]:
    """The file-association ``command``, directory ``command``, and shared ``icon`` derived from ``exe``.

    :param exe: the fake exe path argv[0] was set to.
    :returns: ``(file_command, directory_command, icon)`` -- the directory command has no trailing
        argument yet; :class:`DirectoryContextMenu` appends ``"%1"``/``"%V"`` itself.
    """
    resolved = Path(exe).resolve()
    return f'"{resolved}" "%1"', f'"{resolved}"', f"{resolved},0"


@mark.windows
def test_register_rejects_non_exe_argv0(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--register`` refuses to run when ``sys.argv[0]`` isn't a real executable path.

    Covers being invoked via ``python -m rehuco_agent --register`` -- argv[0] is then the
    ``__main__.py`` source file, and registering it would write a broken, unusable
    ``shell\\open\\command``.

    **Test steps:**

    * set ``sys.argv`` so argv[0] is a ``.py`` path, with ``--register``
    * mock ``FileAssociation.register`` and ``DirectoryContextMenu.register_folder`` (neither must be called)
    * verify ``main()`` returns ``1`` and neither was called
    """
    monkeypatch.setattr("sys.argv", [FAKE_SCRIPT, "--register"])
    register = mocker.patch(FILE_ASSOCIATION_REGISTER)
    register_folder = mocker.patch(DIRECTORY_REGISTER_FOLDER)

    assert main() == 1
    register.assert_not_called()
    register_folder.assert_not_called()


@mark.windows
def test_unregister_rejects_non_exe_argv0(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--unregister`` refuses to run when ``sys.argv[0]`` isn't a real executable path too.

    ``unregister()`` doesn't actually use the exe path, but treating both flags identically
    avoids a confusing "register refuses this, unregister silently accepts it" asymmetry.

    **Test steps:**

    * set ``sys.argv`` so argv[0] is a ``.py`` path, with ``--unregister``
    * mock ``FileAssociation.unregister`` and ``DirectoryContextMenu.unregister_folder`` (neither
      must be called)
    * verify ``main()`` returns ``1`` and neither was called
    """
    monkeypatch.setattr("sys.argv", [FAKE_SCRIPT, "--unregister"])
    unregister = mocker.patch(FILE_ASSOCIATION_UNREGISTER)
    unregister_folder = mocker.patch(DIRECTORY_UNREGISTER_FOLDER)

    assert main() == 1
    unregister.assert_not_called()
    unregister_folder.assert_not_called()


@mark.windows
def test_register_registers_the_running_exe(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--register`` registers whatever exe is actually running (``sys.argv[0]``), using rehuco's
    own ProgID/extension/friendly-name/AUMID identity, and registers the folder + folder-background
    "Open in Rehuco" shell verbs (#43) alongside it.

    **Test steps:**

    * set ``sys.argv`` so argv[0] is a fake ``.exe`` path, with ``--register``
    * mock ``FileAssociation.register`` and ``DirectoryContextMenu.register_folder``/``register_background``
    * verify ``main()`` returns ``0`` and all three were called with rehuco's identity plus the
      command/icon derived from the resolved exe path
    """
    monkeypatch.setattr("sys.argv", [FAKE_EXE, "--register"])
    register = mocker.patch(FILE_ASSOCIATION_REGISTER)
    register_folder = mocker.patch(DIRECTORY_REGISTER_FOLDER)
    register_background = mocker.patch(DIRECTORY_REGISTER_BACKGROUND)

    assert main() == 0
    file_command, directory_command, icon = expected_command_and_icon(FAKE_EXE)
    register.assert_called_once_with(PROGID, EXTENSION, FRIENDLY_NAME, file_command, icon, AUMID)
    register_folder.assert_called_once_with(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon)
    register_background.assert_called_once_with(DIRECTORY_SUB_KEY, DIRECTORY_MENU_TEXT, directory_command, icon)


@mark.windows
def test_unregister_calls_file_association(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--unregister`` calls through to ``FileAssociation.unregister`` with rehuco's identity, and
    removes the folder + folder-background shell verbs (#43) alongside it.

    **Test steps:**

    * set ``sys.argv`` to ``--unregister``
    * mock ``FileAssociation.unregister`` and ``DirectoryContextMenu.unregister_folder``/``unregister_background``
    * verify ``main()`` returns ``0`` and all three were called with the ProgID/extension or sub-key
    """
    monkeypatch.setattr("sys.argv", [FAKE_EXE, "--unregister"])
    unregister = mocker.patch(FILE_ASSOCIATION_UNREGISTER)
    unregister_folder = mocker.patch(DIRECTORY_UNREGISTER_FOLDER)
    unregister_background = mocker.patch(DIRECTORY_UNREGISTER_BACKGROUND)

    assert main() == 0
    unregister.assert_called_once_with(PROGID, EXTENSION)
    unregister_folder.assert_called_once_with(DIRECTORY_SUB_KEY)
    unregister_background.assert_called_once_with(DIRECTORY_SUB_KEY)


@mark.windows
def test_register_not_offered_on_non_windows(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--register``/``--unregister`` aren't defined on the parser at all on non-Windows.

    The parser only adds these flags when ``sys.platform == "win32"``, so elsewhere argparse
    itself rejects ``--register`` as an unrecognized argument (exits via ``SystemExit``)
    rather than this code making a runtime platform check.

    **Test steps:**

    * force ``sys.platform`` to a non-Windows value
    * set ``sys.argv`` to ``--register``
    * verify ``main()`` raises ``SystemExit`` (argparse's own unrecognized-argument exit)
      without ever importing ``FileAssociation``
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_EXE, "--register"])
    register = mocker.patch(FILE_ASSOCIATION_REGISTER)

    with pytest.raises(SystemExit):
        main()
    register.assert_not_called()


@mark.windows
def test_no_flags_sets_aumid_and_delegates_to_run(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """With no ``--register``/``--unregister``, the AUMID is set and ``run`` is called with argv + paths.

    **Test steps:**

    * set ``sys.argv`` to argv[0] plus two ``.rehu`` paths, no flags
    * mock ``SetCurrentProcessExplicitAppUserModelID`` and ``run``
    * verify the AUMID call happened and ``run`` received ``[exe_path, *paths]``
    * verify ``main()`` returns whatever ``run`` returned
    """
    monkeypatch.setattr("sys.argv", [FAKE_EXE, "a.rehu", "b.rehu"])
    set_aumid = mocker.patch("ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID")
    run = mocker.patch("rehuco_agent.__main__.run", return_value=42)

    assert main() == 42
    set_aumid.assert_called_once_with(AUMID)
    run.assert_called_once_with([str(Path(FAKE_EXE).resolve()), "a.rehu", "b.rehu"])
