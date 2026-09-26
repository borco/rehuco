"""App-wide persistent settings storage, shared by every settings section (e.g. `DocumentSessionSettings`)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings

ORGANIZATION_NAME: Final = "borco"
APPLICATION_NAME: Final = "rehuco-agent"


def persistent_settings() -> QSettings:
    """A ``QSettings`` pointed at rehuco-agent's persistent per-user storage."""
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
