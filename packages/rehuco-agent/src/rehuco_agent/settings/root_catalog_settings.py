"""How the Root Catalog dock behaves while it is browsed (#457)."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from .persistent_settings import persistent_settings

GROUP: Final = "root_catalog"
AUTO_PREVIEW_KEY: Final = "auto_preview"

DEFAULT_AUTO_PREVIEW: Final = True
"""Whether the Roots view previews the record of the row it stands on, on a fresh install with nothing persisted. On:
a folder with an ``info.rehu`` showing its record as soon as it is entered is what browsing a catalog is for, and the
switch is for the reader who wants the preview to stay where it is."""


class RootCatalogSettings(QObject):
    """How the Root Catalog dock behaves while it is browsed.

    A reactive ``QObject`` (``SimpleProperty`` fields), like
    :class:`~rehuco_agent.settings.image_viewer_settings.ImageViewerSettings`, because one choice has several views at
    once: the Root Catalog menu's entry, the settings page's checkbox and the dock all read it, and a change made in
    any of them has to reach the others as it is made. :func:`shared_root_catalog_settings` is the single,
    process-wide instance every consumer reads and subscribes to.

    :attr:`auto_preview` is written back **by the menu's own toggle** the moment it is clicked, which has no Apply
    behind it; the settings page stages its checkbox and writes on Apply, as every page does, and both end in the same
    property -- so the menu follows an applied page, and an unapplied page follows the menu.

    :param parent: optional Qt parent.
    """

    auto_preview_changed = Signal(object)

    auto_preview = SimpleProperty(DEFAULT_AUTO_PREVIEW)
    """Whether the Documents preview follows the Roots view's current row: its record -- a folder's ``info.rehu``, a
    file's same-name ``.rehu`` -- shown as the row is reached. The browsers' selection is not governed by it."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what is in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.auto_preview = cast(bool, settings.value(AUTO_PREVIEW_KEY, DEFAULT_AUTO_PREVIEW, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(AUTO_PREVIEW_KEY, self.auto_preview)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_root_catalog_settings() -> RootCatalogSettings:
    """The single, process-wide `RootCatalogSettings` instance, loaded from persistent storage on first call.

    The same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.image_viewer_settings.shared_image_viewer_settings`: the page's Apply and the menu's
    toggle must reach the one object the dock reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = RootCatalogSettings()
    settings.load(persistent_settings())
    return settings
