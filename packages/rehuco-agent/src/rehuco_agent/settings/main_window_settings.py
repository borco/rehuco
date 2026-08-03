"""MainWindow's own geometry and outer dock layout, persisted across restarts
(#21, #47)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

GROUP: Final = "main_window"
GEOMETRY_KEY: Final = "geometry"
OUTER_DOCKS_STATE_KEY: Final = "outer_docks_state"
OUTER_DOCKS_STATE_VERSION_KEY: Final = "outer_docks_state_version"
TOOLBARS_STATE_KEY: Final = "toolbars_state"
LOG_WIDGET_STATE_KEY: Final = "log_widget_state"

OUTER_DOCKS_STATE_VERSION: Final = 2
"""Schema version of :attr:`MainWindowSettings.outer_docks_state`. The outer dock set (the central
documents dock plus any sibling dockable dialogs, e.g. #47's settings dock) is keyed by dock object
name, so any change to that set makes an older blob incompatible: ``CDockManager.restoreState``
would accept it and silently hide docks not present in the saved layout. Bump this whenever the
outer dock set changes; :meth:`MainWindowSettings.load` discards a blob whose version differs,
keeping the default (all-visible) layout instead.

Bumped to 2 when the app-wide log dock was added (#200): a v1 blob knows nothing of it, so restoring
one would leave that dock in whatever state QtAds invents for a dock the layout never mentions, rather
than the deliberately-hidden-by-default one the window builds."""

TOOLBARS_STATE_VERSION: Final = 2
"""Version passed to Qt's own ``QMainWindow.saveState``/``restoreState`` (the toolbar-area/floating
layout for ``action_bar`` -- distinct from :data:`OUTER_DOCKS_STATE_VERSION`,
which is QtAds' own, separate state). Qt rejects a mismatched version itself (``restoreState``
returns ``False`` and leaves the default layout), so this is passed straight through rather than
checked here. Bump whenever the toolbar set changes."""


# Mirrors UnsavedChangesDialogSettings's shape exactly (same geometry-blob load/save, different
# GROUP) -- kept as a separate class rather than a shared base since the two may diverge as each
# widget's settings grow (e.g. #38's dialog vs. this window).
# pylint: disable=duplicate-code
@dataclass
class MainWindowSettings:
    """The main window's saved geometry (size/position), outer dock layout, and toolbar layout."""

    geometry: bytes = field(default=b"")
    """The window's ``saveGeometry()`` blob, or empty before any session has been saved."""

    outer_docks_state: bytes = field(default=b"")
    """The outer ``CDockManager``'s ``saveState()`` blob (central documents dock + sibling dockable
    dialogs, #47), or empty before any session has been saved or after an incompatible
    :data:`OUTER_DOCKS_STATE_VERSION`."""

    toolbars_state: bytes = field(default=b"")
    """Qt's own ``QMainWindow.saveState()`` blob -- the ``action_bar`` toolbar's area/floating
    layout, distinct from :attr:`outer_docks_state` (QtAds' own docks). Empty before any session
    has been saved."""

    log_widget_state: bytes = field(default=b"")
    """The app-wide log surface's own blob (#200): which level bands are shown, whether the tail is
    followed, and what is searched for.

    Kept outside :data:`OUTER_DOCKS_STATE_VERSION`'s guard on purpose, the same way
    ``DocumentWidget``'s image-strip key is: that version guards the *dock set*, while this is one
    widget's filters, read key by key and defaulting individually
    (:meth:`~borco_pyside.logging.LogWidget.restore_state`). A blob written before a filter existed is
    still a perfectly good answer about the others."""

    def load(self, settings: QSettings) -> None:
        """Replace the current geometry, outer dock state, and toolbar state with what's in
        persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        state = cast(QByteArray, settings.value(GEOMETRY_KEY, QByteArray(), type=QByteArray))
        self.geometry = bytes(state.data())

        version = cast(int, settings.value(OUTER_DOCKS_STATE_VERSION_KEY, 0, type=int))
        if version == OUTER_DOCKS_STATE_VERSION:
            docks_state = cast(QByteArray, settings.value(OUTER_DOCKS_STATE_KEY, QByteArray(), type=QByteArray))
            self.outer_docks_state = bytes(docks_state.data())
        else:
            self.outer_docks_state = b""

        toolbars_state = cast(QByteArray, settings.value(TOOLBARS_STATE_KEY, QByteArray(), type=QByteArray))
        self.toolbars_state = bytes(toolbars_state.data())

        log_widget_state = cast(QByteArray, settings.value(LOG_WIDGET_STATE_KEY, QByteArray(), type=QByteArray))
        self.log_widget_state = bytes(log_widget_state.data())
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the geometry, outer dock state, and toolbar state to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(GEOMETRY_KEY, QByteArray(self.geometry))
        settings.setValue(OUTER_DOCKS_STATE_KEY, QByteArray(self.outer_docks_state))
        settings.setValue(OUTER_DOCKS_STATE_VERSION_KEY, OUTER_DOCKS_STATE_VERSION)
        settings.setValue(TOOLBARS_STATE_KEY, QByteArray(self.toolbars_state))
        settings.setValue(LOG_WIDGET_STATE_KEY, QByteArray(self.log_widget_state))
        settings.endGroup()


# pylint: enable=duplicate-code
