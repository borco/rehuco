"""How the Root Catalog dock behaves while it is browsed (#457), and the layouts a new root can start with (#578)."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import DEFAULT_LAYOUTS, Layouts, read_layouts

from .persistent_settings import persistent_settings

LOG: Final = logging.getLogger(__name__)

GROUP: Final = "root_catalog"
AUTO_PREVIEW_KEY: Final = "auto_preview"
SCAN_AFTER_ADDING_KEY: Final = "scan_after_adding"
DEFAULT_LAYOUTS_KEY: Final = "default_layouts"
LABEL_KEY: Final = "label"
LAYOUTS_KEY: Final = "layouts"
FALLBACKS_KEY: Final = "fallbacks"


@dataclass(frozen=True, slots=True)
class RootLayout:
    """One of the default root layouts: what a root made from a folder can start with
    ([[mounts-and-storage#rehuroot]]).

    :param label: the name the Add Roots dialog's combo shows.
    :param layouts: the path templates of each type's main key, ``*`` for any type not named, in offer order (#638).
    :param fallbacks: what each placeholder renders as when a record leaves it empty.
    """

    label: str
    layouts: Layouts = field(default_factory=lambda: dict(DEFAULT_LAYOUTS))
    fallbacks: Mapping[str, str] = field(default_factory=dict)


DEFAULT_ROOT_LAYOUTS: Final = (RootLayout("Keep folder names"),)
"""The shipped seed: any record, under its current name, at the root's top -- what every root had before #578."""

DEFAULT_AUTO_PREVIEW: Final = True
"""Whether the Roots view previews the record of the row it stands on, on a fresh install with nothing persisted. On:
a folder with an ``info.rehu`` showing its record as soon as it is entered is what browsing a catalog is for, and the
switch is for the reader who wants the preview to stay where it is."""

DEFAULT_SCAN_AFTER_ADDING: Final = True
"""Whether adding a root scans it, on a fresh install with nothing persisted. On: a root added and left empty looks
like a failed add, and a scan is what fills it."""


class RootCatalogSettings(QObject):
    """How the Root Catalog dock behaves while it is browsed.

    A reactive ``QObject`` (``SimpleProperty`` fields), like
    :class:`~rehuco_agent.settings.image_viewer_settings.ImageViewerSettings`, because one choice has several views at
    once: the Root Catalog menu's entry, the settings page's checkbox and the dock all read it, and a change made in
    any of them has to reach the others as it is made. :func:`shared_root_catalog_settings` is the single,
    process-wide instance every consumer reads and subscribes to.

    :attr:`scan_after_adding` is written back, and saved to the settings ``.ini``, **by the Add Roots dialog** when it
    closes.

    :attr:`auto_preview` is written back **by the menu's own toggle** the moment it is clicked, which has no Apply
    behind it; the settings page stages its checkbox and writes on Apply, as every page does, and both end in the same
    property -- so the menu follows an applied page, and an unapplied page follows the menu.

    :attr:`default_layouts` is the settings page's, and also grows **from the Add Roots dialog's** *New layout…*, which
    saves at once.

    :param parent: optional Qt parent.
    """

    auto_preview_changed = Signal(object)
    scan_after_adding_changed = Signal(object)
    default_layouts_changed = Signal(object)

    auto_preview = SimpleProperty(DEFAULT_AUTO_PREVIEW)
    """Whether the Documents preview follows the Roots view's current row: its record -- a folder's ``info.rehu``, a
    file's same-name ``.rehu`` -- shown as the row is reached. The browsers' selection is not governed by it."""

    scan_after_adding = SimpleProperty(DEFAULT_SCAN_AFTER_ADDING)
    """Whether adding a root queues a scan of it. The Add Roots dialog shows it and writes it back when it closes."""

    default_layouts = SimpleProperty[tuple[RootLayout, ...]](default_factory=lambda: DEFAULT_ROOT_LAYOUTS)
    """The layouts a root made from a folder can start with, in the order the Add Roots dialog offers them; never
    empty -- a folder always needs one -- so an empty list stored reads back as :data:`DEFAULT_ROOT_LAYOUTS`."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what is in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        try:
            self.auto_preview = cast(bool, settings.value(AUTO_PREVIEW_KEY, DEFAULT_AUTO_PREVIEW, type=bool))
            self.scan_after_adding = cast(
                bool, settings.value(SCAN_AFTER_ADDING_KEY, DEFAULT_SCAN_AFTER_ADDING, type=bool)
            )
            layouts: list[RootLayout] = []
            for index in range(settings.beginReadArray(DEFAULT_LAYOUTS_KEY)):
                settings.setArrayIndex(index)
                layouts.append(
                    RootLayout(
                        str(settings.value(LABEL_KEY, "")),
                        RootCatalogSettings.__read_layouts(settings),
                        RootCatalogSettings.__read_fallbacks(settings),
                    )
                )
            settings.endArray()
            self.default_layouts = tuple(layouts) or DEFAULT_ROOT_LAYOUTS
        finally:
            settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        try:
            settings.setValue(AUTO_PREVIEW_KEY, self.auto_preview)
            settings.setValue(SCAN_AFTER_ADDING_KEY, self.scan_after_adding)
            # the array writer never deletes the indexed keys a longer list left behind
            settings.remove(DEFAULT_LAYOUTS_KEY)
            settings.beginWriteArray(DEFAULT_LAYOUTS_KEY)
            for index, layout in enumerate(self.default_layouts):
                settings.setArrayIndex(index)
                settings.setValue(LABEL_KEY, layout.label)
                stored = {key: list(templates) for key, templates in layout.layouts.items()}
                settings.setValue(LAYOUTS_KEY, json.dumps(stored, ensure_ascii=False))
                settings.setValue(FALLBACKS_KEY, json.dumps(dict(layout.fallbacks), ensure_ascii=False))
            settings.endArray()
        finally:
            settings.endGroup()

    @staticmethod
    def __read_layouts(settings: QSettings) -> dict[str, tuple[str, ...]]:
        """The layouts of a stored layout, written as JSON text: each type's list of templates, or one template as a
        plain string (#638).

        :param settings: the ``QSettings``, at the layout's array index.
        :returns: the layouts; empty, and logged, when they are not that.
        """
        text = str(settings.value(LAYOUTS_KEY, "{}"))
        try:
            return read_layouts(json.loads(text))
        except ValueError:  # a `JSONDecodeError` is one
            LOG.warning(
                "A default root layout's %s are not an object of templates, and were dropped: %s", LAYOUTS_KEY, text
            )
            return {}

    @staticmethod
    def __read_fallbacks(settings: QSettings) -> dict[str, str]:
        """The fallbacks of a stored layout, written as JSON text.

        :param settings: the ``QSettings``, at the layout's array index.
        :returns: the map; empty, and logged, when it is not an object of strings.
        """
        text = str(settings.value(FALLBACKS_KEY, "{}"))
        try:
            value: Any = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if not isinstance(value, dict) or not all(isinstance(item, str) for item in value.values()):
            LOG.warning(
                "A default root layout's %s are not an object of strings, and were dropped: %s", FALLBACKS_KEY, text
            )
            return {}
        return value


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
