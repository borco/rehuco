"""Generic per-user icon installation into the ``hicolor`` icon theme.

A desktop entry's ``Icon=`` is a *name*, resolved against the icon themes on
``$XDG_DATA_HOME``/``$XDG_DATA_DIRS``. ``hicolor`` is the fallback theme every other theme
inherits from, so an icon dropped there is what makes that name resolve for every desktop
environment at once. Per-user, so no root: ``<data home>/icons/hicolor/<size>/<context>/``.

No cache rebuild: ``gtk-update-icon-cache`` writes an ``icon-theme.cache`` that only exists for
themes that ship one, and a per-user ``hicolor`` directory is read directly.
"""

import logging
from pathlib import Path
from typing import Final

from . import xdg

LOG: Final = logging.getLogger(__name__)

DIRECTORY: Final = "icons"
"""Sub-directory of :func:`~borco_core.platforms.linux.xdg.data_home` holding icon themes."""

THEME: Final = "hicolor"
"""The fallback theme every other icon theme inherits from."""

SCALABLE_SIZE: Final = "scalable"
"""The size directory vector icons belong in, as opposed to ``48x48`` and friends."""

APPLICATIONS_CONTEXT: Final = "apps"
"""The context directory holding application icons (as opposed to ``mimetypes``, ``places``, ...)."""

SVG_EXTENSION: Final = "svg"
"""Filename extension matching :data:`SCALABLE_SIZE`."""


class IconTheme:
    """Namespace for per-user ``hicolor`` icon installation.

    Grouped as a class of classmethods -- unlike this package's dataclass-shaped
    :class:`~borco_core.platforms.linux.desktop_entry.DesktopEntry` and
    :class:`~borco_core.platforms.linux.mime_package.MimePackage` -- because an installed icon has
    no structure worth carrying: it is a name, its bytes, and where in the theme it goes.
    """

    @classmethod
    def path(
        cls,
        name: str,
        *,
        size: str = SCALABLE_SIZE,
        context: str = APPLICATIONS_CONTEXT,
        extension: str = SVG_EXTENSION,
    ) -> Path:
        """Where the icon called ``name`` lives inside the per-user theme.

        :param name: the icon name, as a desktop entry's ``Icon=`` would reference it.
        :param size: theme size directory, e.g. ``scalable`` or ``48x48``.
        :param context: theme context directory, e.g. ``apps`` or ``mimetypes``.
        :param extension: the file's extension, without its dot.
        :returns: the absolute path of that icon's file.
        """
        return xdg.data_home() / DIRECTORY / THEME / size / context / f"{name}.{extension}"

    @classmethod
    def install(
        cls,
        name: str,
        data: bytes,
        *,
        size: str = SCALABLE_SIZE,
        context: str = APPLICATIONS_CONTEXT,
        extension: str = SVG_EXTENSION,
    ) -> None:
        """Write ``data`` as the icon called ``name``.

        :param name: same as :meth:`path`.
        :param data: the icon file's full contents.
        :param size: same as :meth:`path`.
        :param context: same as :meth:`path`.
        :param extension: same as :meth:`path`.
        """
        xdg.write_file(cls.path(name, size=size, context=context, extension=extension), data)
        LOG.info("installed theme icon %r", name)

    @classmethod
    def is_installed(
        cls,
        name: str,
        data: bytes,
        *,
        size: str = SCALABLE_SIZE,
        context: str = APPLICATIONS_CONTEXT,
        extension: str = SVG_EXTENSION,
    ) -> bool:
        """Whether the installed icon is byte-for-byte what :meth:`install` would write.

        :param name: same as :meth:`path`.
        :param data: the icon contents to compare against.
        :param size: same as :meth:`path`.
        :param context: same as :meth:`path`.
        :param extension: same as :meth:`path`.
        :returns: ``True`` iff a file exists at :meth:`path` and holds exactly ``data``.
        """
        return xdg.read_file(cls.path(name, size=size, context=context, extension=extension)) == data

    @classmethod
    def remove(
        cls,
        name: str,
        *,
        size: str = SCALABLE_SIZE,
        context: str = APPLICATIONS_CONTEXT,
        extension: str = SVG_EXTENSION,
    ) -> None:
        """Delete the icon called ``name``.

        :param name: same as :meth:`path`.
        :param size: same as :meth:`path`.
        :param context: same as :meth:`path`.
        :param extension: same as :meth:`path`.
        """
        xdg.remove_file(cls.path(name, size=size, context=context, extension=extension))
        LOG.info("removed theme icon %r", name)
