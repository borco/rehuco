"""A `CDockWidget`-hosted, restore-on-start-capable dialog panel (#47)."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from borco_pyside.dialogs.dockable_dialog_frame import DockableDialogFrame
from borco_pyside.dialogs.dockable_dialog_settings import DockableDialogSettings


class DockableDialog:
    """Wraps ``content`` as a dock on ``dock_manager``, adding a "Restore on start" checkbox and
    visibility persistence -- the reusable half of #47's modeless dockable dialog framework.

    Composition, not a `CDockWidget` subclass -- keeps QtAds's own class the single source of truth
    for dock behavior instead of fighting Shiboken's binding of it. Floating/re-docking is QtAds's
    own native drag-out behavior (``DockWidgetFloatable``), not reimplemented here; the only thing
    this class adds on top of a plain dock is the restore-on-start checkbox and its persistence --
    deliberately not a per-dialog geometry blob, since the dock's position/size already rides on its
    ``CDockManager``'s own ``saveState()``, like every other dock in the app.

    Closing hides rather than destroys (no ``DockWidgetDeleteOnClose``/``CustomCloseHandling``), so
    the single long-lived instance built at startup and its :attr:`toggle_action` checked state stay
    in sync, matching every other toggleable dock in this app (`plugins#dock-shell`).

    The dock is constructed but not placed -- add :attr:`dock` to ``dock_manager`` via
    ``addDockWidget``/``setCentralWidget`` separately.

    :param dock_manager: the manager this dialog's dock is associated with.
    :param object_name: this dock's ``objectName`` -- its identity for `CDockManager` persistence and
        this dialog's own settings group.
    :param title: the dock's visible tab/title-bar label.
    :param content: the widget this dialog actually shows.
    """

    def __init__(self, dock_manager: QtAds.CDockManager, object_name: str, title: str, content: QWidget) -> None:
        self.__object_name: Final = object_name
        self.__frame: Final = DockableDialogFrame(content)

        self.__dock: Final = QtAds.CDockWidget(dock_manager, title)
        self.__dock.setObjectName(object_name)
        features = QtAds.CDockWidget.DockWidgetFeature
        self.__dock.setFeatures(
            features.DockWidgetClosable
            | features.DockWidgetMovable
            | features.DockWidgetFloatable
            | features.DockWidgetFocusable
        )
        self.__dock.setWidget(self.__frame)

    @property
    def object_name(self) -> str:
        """This dialog's dock ``objectName`` -- also its settings group key."""
        return self.__object_name

    @property
    def dock(self) -> QtAds.CDockWidget:
        """The hosting dock -- place it via ``addDockWidget``/``setCentralWidget``."""
        return self.__dock

    @property
    def content(self) -> QWidget:
        """The wrapped content widget, as passed to the constructor."""
        return self.__frame.content

    @property
    def toggle_action(self) -> QAction:
        """The checkable action that shows/hides this dialog -- add to an action-bar toolbar."""
        return self.__dock.toggleViewAction()

    def save_settings(self) -> DockableDialogSettings:
        """Capture this dialog's current visibility and restore-on-start checkbox state.

        :returns: the settings to persist, e.g. via :meth:`DockableDialogSettings.save`.
        """
        return DockableDialogSettings(
            visible=not self.__dock.isClosed(), restore_on_start=self.__frame.restore_on_start
        )

    def enforce_restore_on_start(self) -> None:
        """Close this dialog's dock now if "Restore on start" is unchecked.

        Call before the owning ``CDockManager``'s ``saveState()`` is captured for persistence (on
        app close) -- otherwise a floating-and-visible dock whose checkbox is unchecked gets saved
        that way anyway, and the next launch's ``restoreState()`` faithfully recreates it (showing
        its floating window) a moment before :meth:`restore_settings` notices the checkbox and
        hides it again -- a visible show-then-hide flash. Forcing the "shouldn't reopen" state into
        the saved layout itself, instead of only correcting it after restore, is what removes the
        flash rather than just reordering it.
        """
        if not self.__frame.restore_on_start:
            self.__dock.toggleView(False)

    def restore_settings(self, settings: DockableDialogSettings) -> None:
        """Apply previously-saved settings: the restore-on-start checkbox, and the dialog's
        visibility -- open only if it was both visible and restore-on-start was checked when last
        saved, closed otherwise. Unconditional either way (not just "open if"), since a dock QtAds
        just placed via ``addDockWidget`` defaults to open (confirmed empirically) -- this call is
        what makes the framework, not that default, authoritative over initial visibility.

        :param settings: the settings to restore, e.g. from :meth:`DockableDialogSettings.load`.
        """
        self.__frame.restore_on_start = settings.restore_on_start
        self.__dock.toggleView(settings.restore_on_start and settings.visible)
