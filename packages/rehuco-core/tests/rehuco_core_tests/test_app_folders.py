"""Tests for where the agent and the node keep their files ([[packaging-deployment#app-folders]], #412)."""

from pathlib import Path, PurePosixPath
from typing import Final

from pytest import MonkeyPatch, mark
from rehuco_core import AppFolders, app_folders

HOME: Final = Path("/home/user")
"""A home folder no test touches on disk: nothing in :func:`app_folders` creates a folder."""

OWN: Final = PurePosixPath("borco", "rehuco")
"""The organization and app folders every answer ends in."""

PLATFORM_VARIABLES: Final = ("LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
"""Every environment variable some platform's answer reads."""


def posix(folders: AppFolders) -> tuple[str, str, str]:
    """The three folders in forward slashes, so one expectation holds whichever OS runs the test.

    :param folders: the folders to spell.
    :returns: settings, data and cache, in that order.
    """
    return folders.settings.as_posix(), folders.data.as_posix(), folders.cache.as_posix()


def test_windows_keeps_everything_in_one_folder_under_local_app_data() -> None:
    """Local, not Roaming: the folder holds this machine's caches and retained screenshots.

    **Test steps:**

    * ask for the folders on Windows with ``LOCALAPPDATA`` set
    * verify all three are ``borco/rehuco`` under it
    """
    folders = app_folders("win32", {"LOCALAPPDATA": "/local"}, HOME)

    assert posix(folders) == (f"/local/{OWN}",) * 3


def test_windows_falls_back_to_the_profiles_local_folder_without_local_app_data() -> None:
    """A process started with a stripped environment still lands where ``LOCALAPPDATA`` would point.

    **Test steps:**

    * ask for the folders on Windows with an empty environment
    * verify all three are ``AppData/Local/borco/rehuco`` under the home folder
    """
    folders = app_folders("win32", {}, HOME)

    assert posix(folders) == (f"/home/user/AppData/Local/{OWN}",) * 3


def test_macos_keeps_everything_in_one_folder_under_application_support() -> None:
    """macOS separates no settings from data by convention, so there is one answer to where the files are.

    **Test steps:**

    * ask for the folders on macOS
    * verify all three are ``Library/Application Support/borco/rehuco`` under the home folder
    """
    folders = app_folders("darwin", {}, HOME)

    assert posix(folders) == (f"/home/user/Library/Application Support/{OWN}",) * 3


def test_linux_splits_settings_data_and_cache_by_the_xdg_defaults() -> None:
    """With no ``XDG_*`` variable set, the specification's defaults apply.

    **Test steps:**

    * ask for the folders on Linux with an empty environment
    * verify ``~/.config``, ``~/.local/share`` and ``~/.cache``, each with ``borco/rehuco``
    """
    folders = app_folders("linux", {}, HOME)

    assert posix(folders) == (
        f"/home/user/.config/{OWN}",
        f"/home/user/.local/share/{OWN}",
        f"/home/user/.cache/{OWN}",
    )


def test_linux_honors_absolute_xdg_variables() -> None:
    """Each variable moves its own folder only.

    **Test steps:**

    * ask for the folders on Linux with all three ``XDG_*`` variables set to absolute paths
    * verify each folder is ``borco/rehuco`` under its variable
    """
    environ = {"XDG_CONFIG_HOME": "/xdg/config", "XDG_DATA_HOME": "/xdg/data", "XDG_CACHE_HOME": "/xdg/cache"}

    folders = app_folders("linux", environ, HOME)

    assert posix(folders) == (f"/xdg/config/{OWN}", f"/xdg/data/{OWN}", f"/xdg/cache/{OWN}")


@mark.parametrize("value", ["relative/config", ""])
def test_linux_ignores_a_relative_or_empty_xdg_variable(value: str) -> None:
    """The specification says to ignore a relative value; an empty one is unset.

    **Test steps:**

    * ask for the folders on Linux with ``XDG_CONFIG_HOME`` set to ``value``
    * verify the settings folder is the default
    """
    folders = app_folders("linux", {"XDG_CONFIG_HOME": value}, HOME)

    assert folders.settings.as_posix() == f"/home/user/.config/{OWN}"


def test_any_other_platform_follows_xdg() -> None:
    """The BSDs and the rest are told apart from nothing: XDG is their convention too.

    **Test steps:**

    * ask for the folders on ``freebsd14``
    * verify the Linux defaults
    """
    assert posix(app_folders("freebsd14", {}, HOME)) == posix(app_folders("linux", {}, HOME))


def test_the_defaults_read_this_process_and_user(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Called bare, the folders come from this process's environment and this user's home.

    **Test steps:**

    * point the home folder and every variable the platforms read at a temporary folder
    * verify the bare call answers what the explicit call does
    """
    environ = {variable: str(tmp_path / variable) for variable in PLATFORM_VARIABLES}
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for variable, value in environ.items():
        monkeypatch.setenv(variable, value)

    assert app_folders() == app_folders(environ=environ, home=tmp_path)


def test_a_single_folder_is_all_three() -> None:
    """The layout of Windows, macOS and a settings dir.

    **Test steps:**

    * make the folders from one folder
    * verify settings, data and cache are each that folder
    """
    folder = Path("/one")

    assert AppFolders.single(folder) == AppFolders(settings=folder, data=folder, cache=folder)
