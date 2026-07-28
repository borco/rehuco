"""Generic per-user XDG desktop-entry installation.

A ``.desktop`` file in ``<data home>/applications/`` is what makes an application visible to a
Linux desktop at all -- its launcher entry, its icon, the MIME types it claims, and the window
identity (``StartupWMClass`` on X11) that ties a running window back to that entry. Nothing here
needs root: it is the per-user half of what a distro package would install into ``/usr/share``.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from . import xdg

LOG: Final = logging.getLogger(__name__)

DIRECTORY: Final = "applications"
"""Sub-directory of :func:`~borco_core.platforms.linux.xdg.data_home` holding desktop entries."""

SUFFIX: Final = ".desktop"
"""Filename suffix every desktop entry carries."""

UPDATE_COMMAND: Final = "update-desktop-database"
"""Command rebuilding the MIME-to-application cache for :data:`DIRECTORY`."""

SECTION: Final = "[Desktop Entry]"
"""The one group header a launcher entry needs."""


# eight fields, one per desktop-entry key this writes -- a data carrier, not an object growing state
@dataclass(frozen=True)
class DesktopEntry:  # pylint: disable=too-many-instance-attributes
    """One per-user ``.desktop`` launcher entry, and the operations that install or check it.

    A frozen dataclass rather than the classmethod namespace its Windows counterparts use
    (:class:`~borco_core.platforms.windows.file_association.FileAssociation` and friends): an
    entry has eight fields that :meth:`content`, :meth:`install` and :meth:`is_installed` all
    need, so passing them to each call -- the Windows shape, where three or four arguments fit --
    would repeat the whole identity three times per caller.

    :param file_name: basename without :data:`SUFFIX`. This is also the entry's *desktop file id*,
        so it should be the application's reverse-DNS identity (e.g. ``org.example.app``) -- it is
        what ``QGuiApplication.setDesktopFileName()`` must be given for the running window to
        resolve back to this entry.
    :param name: the user-visible application name.
    :param exec_command: the ``Exec`` value, including any field code (``%F``, ``%U``, ...) and
        already quoted where the desktop-entry spec requires it.
    :param comment: one-line tooltip/description; omitted from the file when empty.
    :param icon: icon name (looked up in the icon theme) or absolute path; omitted when empty.
    :param mime_types: MIME types this application claims; omitted when empty.
    :param categories: freedesktop menu categories; omitted when empty.
    :param startup_wm_class: the window's ``WM_CLASS`` on X11, matched to give the window this
        entry's icon; omitted when empty.
    """

    file_name: str
    name: str
    exec_command: str
    comment: str = ""
    icon: str = ""
    mime_types: Sequence[str] = field(default_factory=tuple)
    categories: Sequence[str] = field(default_factory=tuple)
    startup_wm_class: str = ""

    @classmethod
    def directory(cls) -> Path:
        """The per-user directory desktop entries are installed into.

        :returns: ``<data home>/applications``.
        """
        return xdg.data_home() / DIRECTORY

    @classmethod
    def path(cls, file_name: str) -> Path:
        """Where the entry named ``file_name`` lives.

        A classmethod, not a property: reading or removing an entry needs only its name, so a
        caller checking "is anything registered at all?" doesn't have to reconstruct the full
        identity first.

        :param file_name: basename without :data:`SUFFIX`.
        :returns: the absolute path of that entry's file.
        """
        return cls.directory() / f"{file_name}{SUFFIX}"

    @classmethod
    def installed_value(cls, file_name: str, key: str) -> str | None:
        """Read one key's value out of the installed entry named ``file_name``.

        Deliberately a flat scan rather than a full desktop-entry parse: the file has a single
        group, and the question this answers ("what does the installed entry currently point at?")
        needs no more. A key repeated in a malformed file resolves to its first occurrence.

        :param file_name: basename without :data:`SUFFIX`.
        :param key: the key to read, e.g. ``"Exec"``.
        :returns: the value, or ``None`` if the entry or the key is absent.
        """
        data = xdg.read_file(cls.path(file_name))
        if data is None:
            return None
        for line in data.decode("utf-8", errors="replace").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == key:
                return value.strip()
        return None

    @classmethod
    def remove(cls, file_name: str) -> None:
        """Delete the entry named ``file_name`` and refresh the desktop's cache.

        :param file_name: basename without :data:`SUFFIX`.
        """
        xdg.remove_file(cls.path(file_name))
        cls.update_database()
        LOG.info("removed desktop entry %r", file_name)

    @classmethod
    def update_database(cls) -> None:
        """Rebuild the MIME-to-application cache over the per-user applications directory."""
        xdg.run_update_command(UPDATE_COMMAND, str(cls.directory()))

    def content(self) -> str:
        """Render this entry as the text of its ``.desktop`` file.

        Optional fields are left out entirely when empty rather than written blank -- an
        ``Icon=`` with no value is a lookup for the empty icon name, not "no icon".

        :returns: the full file contents, newline-terminated.
        """
        lines = [SECTION, "Type=Application", "Version=1.0", f"Name={self.name}"]
        if self.comment:
            lines.append(f"Comment={self.comment}")
        lines.append(f"Exec={self.exec_command}")
        if self.icon:
            lines.append(f"Icon={self.icon}")
        lines.append("Terminal=false")
        if self.categories:
            lines.append(f"Categories={''.join(f'{category};' for category in self.categories)}")
        if self.mime_types:
            lines.append(f"MimeType={''.join(f'{mime_type};' for mime_type in self.mime_types)}")
        if self.startup_wm_class:
            lines.append(f"StartupWMClass={self.startup_wm_class}")
        lines.append("StartupNotify=true")
        return "\n".join(lines) + "\n"

    def install(self) -> None:
        """Write this entry to :meth:`path` and refresh the desktop's cache."""
        xdg.write_file(self.path(self.file_name), self.content().encode("utf-8"))
        self.update_database()
        LOG.info("installed desktop entry %r", self.file_name)

    def is_installed(self) -> bool:
        """Whether the installed entry is byte-for-byte what :meth:`install` would write.

        :returns: ``True`` iff a file exists at :meth:`path` and holds exactly :meth:`content`.
        """
        return xdg.read_file(self.path(self.file_name)) == self.content().encode("utf-8")
