"""App-wide persistent settings storage, shared by every settings section (e.g. `DocumentSessionSettings`)."""

import logging
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings, QStandardPaths

LOG: Final = logging.getLogger(__name__)

ORGANIZATION_NAME: Final = "borco"
APPLICATION_NAME: Final = "rehuco-agent"

CONFIG_CACHE_FOLDER_NAME: Final = "cache"
"""The subfolder of :func:`config_folder` that :func:`cache_folder` answers when the cache does not get a
location of its own: under a settings dir, or on a host with no known cache location."""

__settings_dir: Path | None = None  # pylint: disable=invalid-name


def set_settings_dir(folder: Path | None) -> None:
    """Keep this run's whole per-user state under ``folder`` instead of the platform's locations (#494).

    The ``.ini`` becomes ``folder/rehuco-agent.ini``, so :func:`config_folder` follows it to
    ``folder/rehuco-agent/``, and :func:`cache_folder` answers ``folder/rehuco-agent/cache/`` -- the layout of
    the platform's settings folder, the cache in it rather than in a location of its own, since a settings dir
    roams nowhere. A module variable read at call time rather than a patched function: every caller imports the
    three functions by name. Set it before anything reads a setting -- the ``shared_*`` loaders cache what they
    first read.

    :param folder: an absolute folder, or ``None`` for the platform's locations.
    """
    global __settings_dir  # pylint: disable=global-statement
    __settings_dir = folder


def settings_dir() -> Path | None:
    """The folder :func:`set_settings_dir` put this run's state under, or ``None`` for the platform's locations."""
    return __settings_dir


def persistent_settings() -> QSettings:
    """A ``QSettings`` pointed at rehuco-agent's persistent per-user storage."""
    if __settings_dir is not None:
        return QSettings(str(__settings_dir / f"{APPLICATION_NAME}.ini"), QSettings.Format.IniFormat)
    return QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORGANIZATION_NAME, application=APPLICATION_NAME
    )


def config_folder() -> Path:
    """This app's own config directory -- where every file the app owns lives, apart from the ``.ini``
    itself (#361).

    Derived from `persistent_settings`'s own `.ini` location rather than `QStandardPaths.AppConfigLocation`
    -- that call needs an organization/application name set on `QCoreApplication`, which nothing in this
    app does today, while the `.ini`'s path already carries both. Its *parent* alone is the
    **organization** directory (``…/borco/``, shared by every borco app), so the application name is
    appended here to land under this app's own config directory specifically. A file written straight into
    the parent would sit loose among other apps' settings.

    :returns: this app's config directory. Not created by this call.
    """
    return Path(persistent_settings().fileName()).parent / APPLICATION_NAME


def cache_folder() -> Path:
    """This app's local cache directory -- where a rebuildable file lives that must not roam or sit on a
    network share, such as a ``.rehudb`` ([[data-model#local-file-trio]], #377).

    Not :func:`config_folder`: that one follows the ``.ini``, which a roaming profile carries between
    machines, and a SQLite cache is neither portable nor safe there. Named like the config folder
    (organization, then application) so a reader finds the two side by side.

    :returns: the cache directory. Not created by this call; ``CatalogCache.open`` makes its own parent.
    """
    if __settings_dir is not None:
        return config_folder() / CONFIG_CACHE_FOLDER_NAME
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    if not base:
        # Qt answers nothing on a host with no known cache location; a relative path would then put the
        # cache wherever the app was launched from, so the config folder is the lesser evil
        LOG.warning("No cache location is known on this host; the cache goes under the config folder.")
        return config_folder() / CONFIG_CACHE_FOLDER_NAME
    return Path(base) / ORGANIZATION_NAME / APPLICATION_NAME


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
