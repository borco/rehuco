"""Tests for windows_registration: rehuco's own identity + register/unregister/is_registered."""

from pathlib import Path
from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent import windows_registration  # noqa: E402  # pylint: disable=wrong-import-position

EXE_PATH: Final = Path(r"C:\fake\rehuco-agent.exe")
ARCHIVE_EXTENSIONS: Final = (".zip",)

FILE_ASSOCIATION: Final = "borco_core.platforms.windows.file_association.FileAssociation"
DIRECTORY_CONTEXT_MENU: Final = "borco_core.platforms.windows.directory_context_menu.DirectoryContextMenu"
FILE_EXTENSION_CONTEXT_MENU: Final = "borco_core.platforms.windows.file_extension_context_menu.FileExtensionContextMenu"


def expected_commands_and_icon() -> tuple[str, str, str]:
    """The file-association command, directory command, and shared icon derived from ``EXE_PATH``.

    :returns: ``(file_command, directory_command, icon)`` -- the directory command has no trailing
        argument yet; ``DirectoryContextMenu`` appends ``"%1"``/``"%V"`` itself.
    """
    return f'"{EXE_PATH}" "%1"', f'"{EXE_PATH}"', f"{EXE_PATH},0"


@mark.windows
def test_is_running_from_exe_accepts_an_exe_path() -> None:
    """A path ending in ``.exe`` (any case) is recognized as a real executable.

    **Test steps:**

    * check a lowercase and an uppercase ``.exe`` path
    * verify both return ``True``
    """
    assert windows_registration.is_running_from_exe(Path(r"C:\fake\app.exe"))
    assert windows_registration.is_running_from_exe(Path(r"C:\fake\app.EXE"))


@mark.windows
def test_is_running_from_exe_rejects_a_py_source_path() -> None:
    """A ``.py`` source path (``python -m rehuco_agent``'s argv[0]) is not a real executable.

    **Test steps:**

    * check a ``__main__.py`` path
    * verify it returns ``False``
    """
    assert not windows_registration.is_running_from_exe(Path(r"C:\fake\rehuco_agent\__main__.py"))


@mark.windows
def test_register_registers_both_extensions_and_all_shell_verbs(mocker: MockerFixture) -> None:
    """``register`` calls the file association once per extension (``.rehu`` and ``.tc``), plus both
    directory verbs and the archive verb, all with rehuco's own identity and the command/icon derived
    from ``exe_path``.

    **Test steps:**

    * mock ``register``/``register_folder``/``register_background`` classmethods
    * call ``register``
    * verify the file association was called once per extension with rehuco's identity plus the
      derived command/icon, and the other three verbs were each called once
    """
    register = mocker.patch(f"{FILE_ASSOCIATION}.register")
    register_folder = mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.register_folder")
    register_background = mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.register_background")
    register_archive = mocker.patch(f"{FILE_EXTENSION_CONTEXT_MENU}.register")

    windows_registration.register(EXE_PATH, ARCHIVE_EXTENSIONS)

    file_command, directory_command, icon = expected_commands_and_icon()
    assert register.call_count == len(windows_registration.EXTENSIONS)
    for extension in windows_registration.EXTENSIONS:
        register.assert_any_call(
            windows_registration.PROGID,
            extension,
            windows_registration.FRIENDLY_NAME,
            file_command,
            icon,
            windows_registration.AUMID,
        )
    register_folder.assert_called_once_with(
        windows_registration.DIRECTORY_SUB_KEY, windows_registration.DIRECTORY_MENU_TEXT, directory_command, icon
    )
    register_background.assert_called_once_with(
        windows_registration.DIRECTORY_SUB_KEY, windows_registration.DIRECTORY_MENU_TEXT, directory_command, icon
    )
    register_archive.assert_called_once_with(
        ARCHIVE_EXTENSIONS,
        windows_registration.ARCHIVE_SUB_KEY,
        windows_registration.ARCHIVE_MENU_TEXT,
        directory_command,
        icon,
    )


@mark.windows
def test_unregister_unregisters_both_extensions_and_all_shell_verbs(mocker: MockerFixture) -> None:
    """``unregister`` calls the file association once per extension (``.rehu`` and ``.tc``), plus both
    directory verbs and the archive verb.

    **Test steps:**

    * mock ``unregister``/``unregister_folder``/``unregister_background`` classmethods
    * call ``unregister``
    * verify the file association was called once per extension with rehuco's identity, and the
      other three verbs were each called once
    """
    unregister = mocker.patch(f"{FILE_ASSOCIATION}.unregister")
    unregister_folder = mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.unregister_folder")
    unregister_background = mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.unregister_background")
    unregister_archive = mocker.patch(f"{FILE_EXTENSION_CONTEXT_MENU}.unregister")

    windows_registration.unregister(ARCHIVE_EXTENSIONS)

    assert unregister.call_count == len(windows_registration.EXTENSIONS)
    for extension in windows_registration.EXTENSIONS:
        unregister.assert_any_call(windows_registration.PROGID, extension)
    unregister_folder.assert_called_once_with(windows_registration.DIRECTORY_SUB_KEY)
    unregister_background.assert_called_once_with(windows_registration.DIRECTORY_SUB_KEY)
    unregister_archive.assert_called_once_with(ARCHIVE_EXTENSIONS, windows_registration.ARCHIVE_SUB_KEY)


@mark.windows
def test_is_registered_is_true_when_all_four_report_registered(mocker: MockerFixture) -> None:
    """``is_registered`` reports ``True`` only when every one of the four checks does.

    **Test steps:**

    * mock all four ``is_registered``/``is_folder_registered``/``is_background_registered`` to
      report ``True``
    * call ``is_registered``
    * verify it returns ``True``
    """
    mocker.patch(f"{FILE_ASSOCIATION}.is_registered", return_value=True)
    mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.is_folder_registered", return_value=True)
    mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.is_background_registered", return_value=True)
    mocker.patch(f"{FILE_EXTENSION_CONTEXT_MENU}.is_registered", return_value=True)

    assert windows_registration.is_registered(EXE_PATH, ARCHIVE_EXTENSIONS)


@mark.windows
def test_is_registered_is_false_when_any_one_check_fails(mocker: MockerFixture) -> None:
    """``is_registered`` reports ``False`` if even one of the four checks does.

    **Test steps:**

    * mock three checks ``True`` and the archive-verb check ``False``
    * call ``is_registered``
    * verify it returns ``False``
    """
    mocker.patch(f"{FILE_ASSOCIATION}.is_registered", return_value=True)
    mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.is_folder_registered", return_value=True)
    mocker.patch(f"{DIRECTORY_CONTEXT_MENU}.is_background_registered", return_value=True)
    mocker.patch(f"{FILE_EXTENSION_CONTEXT_MENU}.is_registered", return_value=False)

    assert not windows_registration.is_registered(EXE_PATH, ARCHIVE_EXTENSIONS)
