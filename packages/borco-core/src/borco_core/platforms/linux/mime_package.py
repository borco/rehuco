"""Generic per-user shared-mime-info package installation.

Linux resolves a file's type by content and name rather than by extension alone, so claiming
``*.rehu`` means *defining a MIME type* -- an XML package in ``<data home>/mime/packages/`` -- and
only then pointing a desktop entry's ``MimeType`` at it. Without this half, an entry declaring an
unknown MIME type claims nothing at all. Per-user, so no root: the same file a distro package
would install into ``/usr/share/mime/packages``.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape, quoteattr  # nosec B406  # escaping only -- nothing here parses XML

from . import xdg

LOG: Final = logging.getLogger(__name__)

DIRECTORY: Final = "mime"
"""Sub-directory of :func:`~borco_core.platforms.linux.xdg.data_home` holding the MIME database."""

PACKAGES_DIRECTORY: Final = "packages"
"""Sub-directory of :data:`DIRECTORY` holding the source XML packages."""

SUFFIX: Final = ".xml"
"""Filename suffix every MIME package carries."""

UPDATE_COMMAND: Final = "update-mime-database"
"""Command compiling the installed packages into the MIME database."""

NAMESPACE: Final = "http://www.freedesktop.org/standards/shared-mime-info"
"""XML namespace every shared-mime-info package declares."""


@dataclass(frozen=True)
class MimePackage:
    """One per-user shared-mime-info package: a MIME type and the filename globs that select it.

    A frozen dataclass for the same reason as
    :class:`~borco_core.platforms.linux.desktop_entry.DesktopEntry` -- the fields are shared by
    :meth:`content`, :meth:`install` and :meth:`is_installed`.

    :param file_name: basename without :data:`SUFFIX`; conventionally the MIME type with its
        slash replaced by a dash (``application-x-example``).
    :param mime_type: the type being defined, e.g. ``application/x-example``.
    :param comment: the human-readable type name file managers show.
    :param globs: filename patterns selecting this type, e.g. ``("*.example",)``.
    """

    file_name: str
    mime_type: str
    comment: str
    globs: Sequence[str] = field(default_factory=tuple)

    @classmethod
    def database_directory(cls) -> Path:
        """The per-user MIME database root, the argument :data:`UPDATE_COMMAND` expects.

        :returns: ``<data home>/mime``.
        """
        return xdg.data_home() / DIRECTORY

    @classmethod
    def directory(cls) -> Path:
        """The per-user directory MIME packages are installed into.

        :returns: ``<data home>/mime/packages``.
        """
        return cls.database_directory() / PACKAGES_DIRECTORY

    @classmethod
    def path(cls, file_name: str) -> Path:
        """Where the package named ``file_name`` lives.

        :param file_name: basename without :data:`SUFFIX`.
        :returns: the absolute path of that package's file.
        """
        return cls.directory() / f"{file_name}{SUFFIX}"

    @classmethod
    def remove(cls, file_name: str) -> None:
        """Delete the package named ``file_name`` and recompile the database.

        :param file_name: basename without :data:`SUFFIX`.
        """
        xdg.remove_file(cls.path(file_name))
        cls.update_database()
        LOG.info("removed MIME package %r", file_name)

    @classmethod
    def update_database(cls) -> None:
        """Recompile the per-user MIME database from its installed packages."""
        xdg.run_update_command(UPDATE_COMMAND, str(cls.database_directory()))

    def content(self) -> str:
        """Render this package as the text of its XML file.

        :returns: the full file contents, newline-terminated.
        """
        globs = "\n".join(f"    <glob pattern={quoteattr(pattern)}/>" for pattern in self.globs)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<mime-info xmlns={quoteattr(NAMESPACE)}>\n"
            f"  <mime-type type={quoteattr(self.mime_type)}>\n"
            f"    <comment>{escape(self.comment)}</comment>\n"
            f"{globs}\n"
            "  </mime-type>\n"
            "</mime-info>\n"
        )

    def install(self) -> None:
        """Write this package to :meth:`path` and recompile the database."""
        xdg.write_file(self.path(self.file_name), self.content().encode("utf-8"))
        self.update_database()
        LOG.info("installed MIME package %r for %r", self.file_name, self.mime_type)

    def is_installed(self) -> bool:
        """Whether the installed package is byte-for-byte what :meth:`install` would write.

        :returns: ``True`` iff a file exists at :meth:`path` and holds exactly :meth:`content`.
        """
        return xdg.read_file(self.path(self.file_name)) == self.content().encode("utf-8")
