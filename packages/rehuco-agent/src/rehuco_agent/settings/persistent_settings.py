"""App-wide persistent settings storage, shared by every settings section (e.g. `DocumentSessionSettings`)."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings
from rehuco_core import AppFolders, app_folders

APPLICATION_NAME: Final = "rehuco-agent"

__settings_dir: Path | None = None  # pylint: disable=invalid-name


def set_settings_dir(folder: Path | None) -> None:
    """Keep this run's whole per-user state in ``folder`` instead of the platform's locations (#494).

    The ``.ini``, the durable state and the caches all go directly in ``folder`` -- the layout of Windows and macOS,
    since a settings dir roams nowhere. A module variable read at call time rather than a patched function: every
    caller imports the functions by name. Set it before anything reads a setting -- the ``shared_*`` loaders cache
    what they first read.

    :param folder: an absolute folder, or ``None`` for the platform's locations.
    """
    global __settings_dir  # pylint: disable=global-statement
    __settings_dir = folder


def settings_dir() -> Path | None:
    """The folder :func:`set_settings_dir` put this run's state in, or ``None`` for the platform's locations."""
    return __settings_dir


def folders() -> AppFolders:
    """The folders this run keeps its files in ([[packaging-deployment#app-folders]], #412).

    :returns: the settings dir's one folder when one is set, else the platform's folders.
    """
    if __settings_dir is not None:
        return AppFolders.single(__settings_dir)
    return app_folders()


def persistent_settings() -> QSettings:
    """A ``QSettings`` on rehuco-agent's ``.ini``, in the settings folder."""
    return QSettings(str(folders().settings / f"{APPLICATION_NAME}.ini"), QSettings.Format.IniFormat)


def config_folder() -> Path:
    """Where the durable files the app owns live, apart from the ``.ini`` itself -- the saved task queue, the
    session, the layouts, crash dumps, the scraper persona (#361, #412).

    The data folder: the same as the settings folder on Windows and macOS, `$XDG_DATA_HOME` on Linux.

    :returns: the folder. Not created by this call.
    """
    return folders().data


def cache_folder() -> Path:
    """Where a rebuildable file lives that must not sit on a network share, such as a ``.rehudb``
    ([[data-model#local-file-trio]], #377).

    :returns: the cache folder. Not created by this call; ``CatalogCache.open`` makes its own parent.
    """
    return folders().cache


STAGED_IMAGES_FOLDER_NAME: Final = "staged"
"""The cache subfolder an image dragged or copied out of the app is staged in (#395)."""

STAGED_IMAGES_MAX_AGE: Final = timedelta(days=7)
"""How long a staged image is kept after its last use: long enough for a paste days after the copy, short enough
that the folder never grows into a second library."""


def staging_folder() -> Path:
    """Where an image taken out of the app is staged -- under :func:`cache_folder`, since every file there is
    rebuildable and local ([[reference-images#modes]]).

    :returns: the folder. Not created by this call; ``stage_image`` makes it.
    """
    return cache_folder() / STAGED_IMAGES_FOLDER_NAME


def read_stored_strings(value: object) -> tuple[str, ...]:
    """Coerce a value read back out of `QSettings` into the strings it was stored as.

    Kept here rather than in either section that reads a list, because what it allows for is the
    *backend's* behaviour and not any one setting's: the ini format writes a single-element list as a
    plain string and hands it back that way, so a bare ``str`` is one entry rather than garbage. A
    non-string inside a stored list is skipped rather than stringified -- reading a stray ``7`` as
    ``"7"`` would invent an entry nobody typed. Anything else -- absent, or of a type a list was never
    stored as -- reads as no entries at all.

    What *no entries* then means is the caller's: an empty list resolves to the shipped defaults in
    both sections that use this today, but that is their rule, decided where the effective value is
    read, not here.

    :param value: the raw stored value.
    :returns: the stored strings, verbatim and in the order stored; empty when there are none to read.
    """
    entries: Sequence[object]
    if isinstance(value, str):
        entries = [value]
    elif isinstance(value, list | tuple):
        entries = value
    else:
        return ()
    return tuple(entry for entry in entries if isinstance(entry, str))
