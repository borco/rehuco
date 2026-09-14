"""Which of the window's borders a pinned main dock collapses into (#279)."""

from enum import StrEnum
from functools import lru_cache
from typing import Final, cast

import PySide6QtAds as QtAds
from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "docks"
PIN_SIDE_KEY: Final = "pin_side"


class DockPinSide(StrEnum):
    """Which border of the main window a pinned dock's sidebar tab lands on.

    A ``StrEnum``, and QtAds' own ``SideBarLocation`` is deliberately not persisted directly: the
    stored value stays a readable word in the ``.ini``, and the setting is not tied to the numbering
    of a third-party enum that a future QtAds could renumber under a blob already on disk.
    """

    LEFT = "left"
    """The window's left border -- the default."""

    RIGHT = "right"
    """The window's right border."""

    TOP = "top"
    """The window's top border."""

    BOTTOM = "bottom"
    """The window's bottom border."""


SIDE_BAR_LOCATIONS: Final[dict[DockPinSide, QtAds.SideBarLocation]] = {
    DockPinSide.LEFT: QtAds.SideBarLeft,
    DockPinSide.RIGHT: QtAds.SideBarRight,
    DockPinSide.TOP: QtAds.SideBarTop,
    DockPinSide.BOTTOM: QtAds.SideBarBottom,
}
"""Each side's QtAds counterpart, for `CDockWidget.setPreferredAutoHideSideBarLocation`. The one
place the two vocabularies meet, so a reader looking for "what does 'left' actually do" has one
answer rather than a branch per call site."""

SIDE_LABELS: Final[dict[DockPinSide, str]] = {
    DockPinSide.LEFT: "Left",
    DockPinSide.RIGHT: "Right",
    DockPinSide.TOP: "Top",
    DockPinSide.BOTTOM: "Bottom",
}
"""What each side is called on the Docks settings page -- kept beside the sides themselves rather
than typed into the ``.ui``, so the combo box cannot come to offer a side this module does not know
how to apply."""

DEFAULT_PIN_SIDE: Final = DockPinSide.LEFT
"""Where a fresh install pins to. Left because that is the side the window's own action bar is on:
a pinned dock's tabs then read down the same edge the toggles that open those docks already do."""


class DocksSettings(QObject):
    """Where the main window's docks pin to ([[appendices.settings-pages#category-groups]], #279).

    A reactive ``QObject`` (``SimpleProperty``), following
    :class:`~rehuco_agent.settings.image_viewer_settings.ImageViewerSettings` rather than the plain
    dataclass most of this app's settings sections use: applying the page has to show its effect on
    the docks **already open**, by re-setting the preferred location on each of them -- which is the
    whole point of having an Apply button to watch. :func:`shared_docks_settings` is the single,
    process-wide instance the window reads and subscribes to.

    :param parent: optional Qt parent.
    """

    pin_side = SimpleProperty[DockPinSide](DEFAULT_PIN_SIDE)
    """Which border a main dock's pin button collapses it into."""

    def load(self, settings: QSettings) -> None:
        """Replace the current side with what's in persistent storage.

        A missing side -- or one this build doesn't recognize, e.g. an ``.ini`` written by a newer
        version offering a fifth -- falls back to :data:`DEFAULT_PIN_SIDE` rather than raising, the
        same way `ImageViewerSettings.load` treats its mode: an unreadable preference must not stop
        the window from building its docks at all.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        stored = cast(str, settings.value(PIN_SIDE_KEY, DEFAULT_PIN_SIDE.value, type=str))
        settings.endGroup()
        try:
            self.pin_side = DockPinSide(stored)
        except ValueError:
            self.pin_side = DEFAULT_PIN_SIDE

    def save(self, settings: QSettings) -> None:
        """Save the current side to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(PIN_SIDE_KEY, self.pin_side.value)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_docks_settings() -> DocksSettings:
    """The single, process-wide `DocksSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.image_viewer_settings.shared_image_viewer_settings`: the settings
    page's Save must be what the open docks re-read, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = DocksSettings()
    settings.load(persistent_settings())
    return settings
