"""Where the agent and the node keep their files on this machine ([[packaging-deployment#app-folders]], #412).

Qt-free, so the node finds the same folders the agent does. Windows and macOS keep everything in one folder; Linux
follows XDG. Every function takes the platform, environment and home folder as parameters, so a test drives each
platform from any OS.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

ORGANIZATION_FOLDER_NAME: Final = "borco"
"""The folder every borco app keeps its own folder in."""

APP_FOLDER_NAME: Final = "rehuco"
"""The folder, under :data:`ORGANIZATION_FOLDER_NAME`, shared by the agent and the node."""


@dataclass(frozen=True)
class AppFolders:
    """The three folders an app's files are spread over; the same folder on Windows and macOS.

    :param settings: where settings files live.
    :param data: where durable local state lives -- what deleting would lose.
    :param cache: where a rebuildable file lives, such as a ``.rehudb``.
    """

    settings: Path
    data: Path
    cache: Path

    @classmethod
    def single(cls, folder: Path) -> Self:
        """All three folders as ``folder`` -- the layout of Windows and macOS, and of a settings dir.

        :param folder: the one folder.
        :returns: the folders.
        """
        return cls(settings=folder, data=folder, cache=folder)


def base_folder(environ: Mapping[str, str], variable: str, default: Path) -> Path:
    """A base folder named by an environment variable: its value when that is an absolute path, else ``default``.

    The XDG specification says to ignore a relative value; ``LOCALAPPDATA`` is treated the same.

    :param environ: the environment to read.
    :param variable: ``LOCALAPPDATA``, ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` or ``XDG_CACHE_HOME``.
    :param default: the folder when the variable is unset, empty or relative (the specification says to ignore it).
    :returns: the base folder, without the app's own part.
    """
    value = environ.get(variable, "")
    # a leading slash counts too: an XDG value is a POSIX path, absolute even when judged from Windows
    return Path(value) if value and (value.startswith("/") or Path(value).is_absolute()) else default


def app_folders(
    platform: str = sys.platform, environ: Mapping[str, str] | None = None, home: Path | None = None
) -> AppFolders:
    """The folders for this machine and OS user. Nothing is created.

    :param platform: a ``sys.platform`` value; ``win32`` and ``darwin`` are told apart, anything else follows XDG.
    :param environ: the environment to read ``LOCALAPPDATA`` and the ``XDG_*`` variables from; this process's
        when ``None``.
    :param home: the user's home folder; this user's own when ``None``.
    :returns: the folders, each ending in ``borco/rehuco``.
    """
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    own = Path(ORGANIZATION_FOLDER_NAME) / APP_FOLDER_NAME
    if platform == "win32":
        return AppFolders.single(base_folder(environ, "LOCALAPPDATA", home / "AppData" / "Local") / own)
    if platform == "darwin":
        return AppFolders.single(home / "Library" / "Application Support" / own)
    return AppFolders(
        settings=base_folder(environ, "XDG_CONFIG_HOME", home / ".config") / own,
        data=base_folder(environ, "XDG_DATA_HOME", home / ".local" / "share") / own,
        cache=base_folder(environ, "XDG_CACHE_HOME", home / ".cache") / own,
    )
