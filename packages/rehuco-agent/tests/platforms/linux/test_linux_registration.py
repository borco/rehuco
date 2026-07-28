"""Tests for linux_registration: rehuco's own XDG identity + register/unregister/is_registered.

No ``importorskip`` guard, unlike the Windows sibling: `rehuco_agent.linux_registration` and the
``borco_core.platforms.linux.*`` modules it wraps are ``pathlib``/``subprocess`` underneath, so
they import and behave the same wherever these tests run -- which is what keeps this code measured
on a non-Linux developer machine.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent import linux_registration

MODULE: Final = "rehuco_agent.linux_registration"

EXE_PATH: Final = Path("/fake/home/.local/bin/rehuco-agent")
APPIMAGE_PATH: Final = "/fake/downloads/Rehuco-x86_64.AppImage"
SOURCE_PATH: Final = Path("/fake/src/rehuco_agent/__main__.py")

DESKTOP_ENTRY: Final = "borco_core.platforms.linux.desktop_entry.DesktopEntry"
MIME_PACKAGE: Final = "borco_core.platforms.linux.mime_package.MimePackage"
ICON_THEME: Final = "borco_core.platforms.linux.icon_theme.IconTheme"

ICON: Final = b"<svg/>"


# region identity and preconditions


def test_executable_path_prefers_the_appimage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside an AppImage the registered path is ``$APPIMAGE``, not ``sys.argv[0]``.

    ``sys.argv[0]`` points into ``$APPDIR``, a temporary mount that is gone once the process
    exits -- an ``Exec=`` written from it is dead on arrival.

    **Test steps:**

    * set ``APPIMAGE`` and point ``sys.argv[0]`` at the mount instead
    * read ``executable_path``
    * verify it is the AppImage, taken verbatim
    """
    monkeypatch.setenv(linux_registration.APPIMAGE_VARIABLE, APPIMAGE_PATH)
    monkeypatch.setattr("sys.argv", ["/fake/mount/usr/bin/rehuco-agent"])

    assert linux_registration.executable_path() == Path(APPIMAGE_PATH)


def test_executable_path_falls_back_to_argv0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside an AppImage the registered path is the running ``sys.argv[0]``, resolved.

    **Test steps:**

    * unset ``APPIMAGE`` and point ``sys.argv[0]`` at a shim
    * read ``executable_path``
    * verify it is that shim's resolved path
    """
    monkeypatch.delenv(linux_registration.APPIMAGE_VARIABLE, raising=False)
    monkeypatch.setattr("sys.argv", [str(EXE_PATH)])

    assert linux_registration.executable_path() == Path(str(EXE_PATH)).resolve()


def test_executable_path_upgrades_a_py_argv0_to_the_venv_shim(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """``python -m rehuco_agent`` (or running ``__main__.py`` directly) is upgraded to the venv's
    own ``rehuco-agent`` console-script shim, when one sits next to the running interpreter --
    ``uv sync``/``pip install -e .`` always installs it there, so it is never a guess.

    **Test steps:**

    * unset ``APPIMAGE``, point ``sys.argv[0]`` at a ``.py`` source path and ``sys.executable`` at
      a fake venv interpreter
    * report the sibling ``rehuco-agent`` as executable
    * read ``executable_path``
    * verify it is that sibling shim, not the source path
    """
    monkeypatch.delenv(linux_registration.APPIMAGE_VARIABLE, raising=False)
    monkeypatch.setattr("sys.argv", [str(SOURCE_PATH)])
    monkeypatch.setattr("sys.executable", "/fake/venv/bin/python3.14")
    mocker.patch(f"{MODULE}.os.access", return_value=True)

    assert linux_registration.executable_path() == Path("/fake/venv/bin/rehuco-agent")


def test_executable_path_keeps_the_source_path_without_a_venv_shim(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """With no venv shim next to the interpreter, the ``.py`` source path is kept as-is, for
    :func:`registration_blocker` to refuse.

    **Test steps:**

    * unset ``APPIMAGE``, point ``sys.argv[0]`` at a ``.py`` source path and ``sys.executable`` at
      a fake venv interpreter
    * report the sibling ``rehuco-agent`` as not executable (missing)
    * read ``executable_path``
    * verify it is the source path, resolved
    """
    monkeypatch.delenv(linux_registration.APPIMAGE_VARIABLE, raising=False)
    monkeypatch.setattr("sys.argv", [str(SOURCE_PATH)])
    monkeypatch.setattr("sys.executable", "/fake/venv/bin/python3.14")
    mocker.patch(f"{MODULE}.os.access", return_value=False)

    assert linux_registration.executable_path() == SOURCE_PATH.resolve()


def test_is_running_from_executable_accepts_an_executable(mocker: MockerFixture) -> None:
    """A non-``.py`` file the user may execute is something a desktop entry can launch.

    **Test steps:**

    * report the file as executable
    * check the shim path
    * verify it returns ``True``
    """
    mocker.patch(f"{MODULE}.os.access", return_value=True)

    assert linux_registration.is_running_from_executable(EXE_PATH)


def test_is_running_from_executable_rejects_a_py_source_path(mocker: MockerFixture) -> None:
    """A ``.py`` source path (``python -m rehuco_agent``'s argv[0]) is refused even if executable.

    **Test steps:**

    * report the file as executable
    * check a ``__main__.py`` path
    * verify it returns ``False``
    """
    mocker.patch(f"{MODULE}.os.access", return_value=True)

    assert not linux_registration.is_running_from_executable(SOURCE_PATH)


def test_is_running_from_executable_rejects_a_non_executable_file(mocker: MockerFixture) -> None:
    """A file without the execute bit cannot be an ``Exec=`` target either.

    **Test steps:**

    * report the file as not executable
    * check the shim path
    * verify it returns ``False``
    """
    mocker.patch(f"{MODULE}.os.access", return_value=False)

    assert not linux_registration.is_running_from_executable(EXE_PATH)


def test_sandbox_name_detects_flatpak(mocker: MockerFixture) -> None:
    """A Flatpak sandbox is recognized by its marker file.

    **Test steps:**

    * report the marker file as present
    * read ``sandbox_name``
    * verify it names Flatpak
    """
    mocker.patch(f"{MODULE}.FLATPAK_MARKER").exists.return_value = True

    assert linux_registration.sandbox_name() == "Flatpak"


def test_sandbox_name_detects_snap(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Snap confinement is recognized by its environment variable.

    **Test steps:**

    * report the Flatpak marker as absent and set ``SNAP``
    * read ``sandbox_name``
    * verify it names Snap
    """
    mocker.patch(f"{MODULE}.FLATPAK_MARKER").exists.return_value = False
    monkeypatch.setenv(linux_registration.SNAP_VARIABLE, "/snap/rehuco-agent/current")

    assert linux_registration.sandbox_name() == "Snap"


def test_sandbox_name_is_none_when_unconfined(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary install reports no sandbox at all.

    **Test steps:**

    * report the Flatpak marker as absent and unset ``SNAP``
    * read ``sandbox_name``
    * verify it is ``None``
    """
    mocker.patch(f"{MODULE}.FLATPAK_MARKER").exists.return_value = False
    monkeypatch.delenv(linux_registration.SNAP_VARIABLE, raising=False)

    assert linux_registration.sandbox_name() is None


def test_registration_blocker_refuses_inside_a_sandbox(mocker: MockerFixture) -> None:
    """Inside Flatpak/Snap registration is refused by name -- a false "Registered." would be worse.

    **Test steps:**

    * report a Flatpak sandbox
    * ask for the blocker
    * verify it names the sandbox
    """
    mocker.patch(f"{MODULE}.sandbox_name", return_value="Flatpak")

    blocker = linux_registration.registration_blocker(EXE_PATH)

    assert blocker == linux_registration.SANDBOXED_BLOCKER.format(sandbox="Flatpak")


def test_registration_blocker_refuses_a_source_checkout(mocker: MockerFixture) -> None:
    """Running via ``python -m rehuco_agent`` is refused, naming the path it would have registered.

    **Test steps:**

    * report no sandbox and a non-executable source path
    * ask for the blocker
    * verify it names that path
    """
    mocker.patch(f"{MODULE}.sandbox_name", return_value=None)
    mocker.patch(f"{MODULE}.is_running_from_executable", return_value=False)

    blocker = linux_registration.registration_blocker(SOURCE_PATH)

    assert blocker == linux_registration.NOT_AN_EXECUTABLE_BLOCKER.format(path=SOURCE_PATH)


def test_registration_blocker_is_none_when_registration_can_work(mocker: MockerFixture) -> None:
    """An unsandboxed run from a real executable has nothing blocking it.

    **Test steps:**

    * report no sandbox and an executable path
    * ask for the blocker
    * verify it is ``None``
    """
    mocker.patch(f"{MODULE}.sandbox_name", return_value=None)
    mocker.patch(f"{MODULE}.is_running_from_executable", return_value=True)

    assert linux_registration.registration_blocker(EXE_PATH) is None


def test_unregistration_blocker_refuses_inside_a_sandbox(mocker: MockerFixture) -> None:
    """Inside Flatpak/Snap unregistering is refused too -- the app can't touch the host's XDG
    directories at all, register or not.

    **Test steps:**

    * report a Flatpak sandbox
    * ask for the unregistration blocker
    * verify it names the sandbox
    """
    mocker.patch(f"{MODULE}.sandbox_name", return_value="Flatpak")

    assert linux_registration.unregistration_blocker() == linux_registration.SANDBOXED_BLOCKER.format(sandbox="Flatpak")


def test_unregistration_blocker_is_none_outside_a_sandbox(mocker: MockerFixture) -> None:
    """Unlike registration, an unsandboxed source checkout has nothing blocking unregistration --
    it never depends on ``exe_path`` being launchable.

    **Test steps:**

    * report no sandbox
    * ask for the unregistration blocker
    * verify it is ``None``
    """
    mocker.patch(f"{MODULE}.sandbox_name", return_value=None)

    assert linux_registration.unregistration_blocker() is None


def test_launch_command_quotes_the_path_and_opens_local_files() -> None:
    """The ``Exec`` value quotes the executable and takes a list of local paths.

    **Test steps:**

    * build the launch command for the shim
    * verify the path is quoted and the field code is ``%F``
    """
    assert linux_registration.launch_command(EXE_PATH) == f'"{EXE_PATH}" %F'


def test_desktop_entry_carries_rehucos_identity() -> None:
    """The launcher entry names rehuco's desktop file id, icon, MIME type and window class.

    **Test steps:**

    * build the entry for the shim
    * verify every identity field, and that the icon and window class both use the desktop file id
    """
    entry = linux_registration.desktop_entry(EXE_PATH)

    assert entry.file_name == linux_registration.DESKTOP_FILE_NAME
    assert entry.name == linux_registration.APPLICATION_NAME
    assert entry.exec_command == linux_registration.launch_command(EXE_PATH)
    assert entry.icon == linux_registration.DESKTOP_FILE_NAME
    assert entry.startup_wm_class == linux_registration.DESKTOP_FILE_NAME
    assert entry.mime_types == (linux_registration.MIME_TYPE,)
    assert entry.categories == linux_registration.CATEGORIES


def test_mime_package_globs_every_registered_extension() -> None:
    """The MIME package claims ``.rehu`` *and* ``.tc``, so a legacy file opens into its locked view.

    **Test steps:**

    * build the MIME package
    * verify its type, and one glob per extension
    """
    package = linux_registration.mime_package()

    assert package.mime_type == linux_registration.MIME_TYPE
    assert package.file_name == linux_registration.MIME_FILE_NAME
    assert package.globs == tuple(f"*.{extension}" for extension in linux_registration.EXTENSIONS)


def test_icon_data_reads_the_app_icon_resource(mocker: MockerFixture) -> None:
    """The installed icon comes from the compiled Qt resources, read lazily.

    **Test steps:**

    * mock ``read_resource_bytes``
    * call ``icon_data``
    * verify it read this app's icon resource and returned its bytes
    """
    read_resource_bytes = mocker.patch("borco_pyside.theming.read_resource_bytes", return_value=ICON)

    assert linux_registration.icon_data() == ICON
    read_resource_bytes.assert_called_once_with(linux_registration.ICON_RESOURCE)


# endregion

# region register / unregister / is_registered


def test_register_installs_the_icon_mime_package_and_desktop_entry(mocker: MockerFixture) -> None:
    """``register`` writes all three files a Linux association needs, with rehuco's identity.

    **Test steps:**

    * mock ``icon_data`` and the three install calls
    * call ``register``
    * verify the icon was installed under the desktop file id, and that the package and entry
      installed are exactly the ones ``mime_package``/``desktop_entry`` describe for this path
    """
    mocker.patch(f"{MODULE}.icon_data", return_value=ICON)
    install_icon = mocker.patch(f"{ICON_THEME}.install")
    install_package = mocker.patch(f"{MIME_PACKAGE}.install", autospec=True)
    install_entry = mocker.patch(f"{DESKTOP_ENTRY}.install", autospec=True)

    linux_registration.register(EXE_PATH)

    install_icon.assert_called_once_with(linux_registration.DESKTOP_FILE_NAME, ICON)
    install_package.assert_called_once_with(linux_registration.mime_package())
    install_entry.assert_called_once_with(linux_registration.desktop_entry(EXE_PATH))


def test_unregister_removes_all_three(mocker: MockerFixture) -> None:
    """``unregister`` removes exactly what ``register`` wrote, keyed by the same names.

    **Test steps:**

    * mock the three remove calls
    * call ``unregister``
    * verify each was called once with rehuco's own file name
    """
    remove_entry = mocker.patch(f"{DESKTOP_ENTRY}.remove")
    remove_package = mocker.patch(f"{MIME_PACKAGE}.remove")
    remove_icon = mocker.patch(f"{ICON_THEME}.remove")

    linux_registration.unregister()

    remove_entry.assert_called_once_with(linux_registration.DESKTOP_FILE_NAME)
    remove_package.assert_called_once_with(linux_registration.MIME_FILE_NAME)
    remove_icon.assert_called_once_with(linux_registration.DESKTOP_FILE_NAME)


def test_is_registered_is_true_when_all_three_report_installed(mocker: MockerFixture) -> None:
    """``is_registered`` reports ``True`` only when every one of the three checks does.

    **Test steps:**

    * mock ``icon_data`` and all three ``is_installed`` checks to report ``True``
    * call ``is_registered``
    * verify it returns ``True``
    """
    mocker.patch(f"{MODULE}.icon_data", return_value=ICON)
    mocker.patch(f"{DESKTOP_ENTRY}.is_installed", return_value=True)
    mocker.patch(f"{MIME_PACKAGE}.is_installed", return_value=True)
    mocker.patch(f"{ICON_THEME}.is_installed", return_value=True)

    assert linux_registration.is_registered(EXE_PATH)


def test_is_registered_is_false_when_the_icon_is_stale(mocker: MockerFixture) -> None:
    """``is_registered`` reports ``False`` if even one of the three checks does -- an app update
    that changed the icon is a re-register, not "already registered".

    **Test steps:**

    * mock ``icon_data`` and report the entry and package installed but the icon not
    * call ``is_registered``
    * verify it returns ``False``
    """
    mocker.patch(f"{MODULE}.icon_data", return_value=ICON)
    mocker.patch(f"{DESKTOP_ENTRY}.is_installed", return_value=True)
    mocker.patch(f"{MIME_PACKAGE}.is_installed", return_value=True)
    mocker.patch(f"{ICON_THEME}.is_installed", return_value=False)

    assert not linux_registration.is_registered(EXE_PATH)


def test_registered_command_reads_the_installed_exec(mocker: MockerFixture) -> None:
    """``registered_command`` reports whatever the installed entry currently launches.

    This is what tells "not registered" apart from "registered, but pointing somewhere else" --
    the ordinary state for an AppImage the user moved or replaced.

    **Test steps:**

    * mock ``installed_value``
    * call ``registered_command``
    * verify it read the ``Exec`` key of rehuco's own entry and returned its value
    """
    installed_value = mocker.patch(f"{DESKTOP_ENTRY}.installed_value", return_value='"/elsewhere/app" %F')

    assert linux_registration.registered_command() == '"/elsewhere/app" %F'
    installed_value.assert_called_once_with(linux_registration.DESKTOP_FILE_NAME, "Exec")


# endregion
