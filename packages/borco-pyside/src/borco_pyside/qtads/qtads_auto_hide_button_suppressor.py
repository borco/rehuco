"""Keeps one QtAds `CDockManager`'s areas free of the auto-hide (pin) button."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, QTimer


class QtAdsAutoHideButtonSuppressor(QObject):
    """Hides the auto-hide ("pin") button on every dock area of **one** `CDockManager`.

    For an app that nests managers and wants pinning to stay an outer-window affordance: the sidebars
    a pinned dock collapses into belong to the window, and a dock pinned inside a dock inside another
    dock puts a third sidebar behind two the reader already has to keep track of.

    **A feature flag is not a lever here.** ``DockWidgetPinnable`` gates neither the button nor the
    drop: a dock built without it still shows the button, and ``setAutoHide(True)`` on it still pins
    (verified against the installed binding). What shows the button is
    ``CDockManager.DockAreaHasAutoHideButton``, an ``eAutoHideFlag`` -- and the auto-hide flags are
    ``CDockManager`` **statics**, shared process-wide across every manager, so clearing the flag turns
    pinning off everywhere or nowhere. ``dockAreaCreated`` is the per-instance seam: it fires only for
    areas created under the manager it was connected on, which is what makes this suppressible for one
    manager while the rest keep the flag's default.

    **The hide has to be deferred, and re-applied.** QtAds forces its title-bar buttons back to visible
    from ``DockContainerWidgetPrivate::onVisibleDockAreaCountChanged()`` whenever a container's visible
    area count transitions to or from exactly one, regardless of any flag. So a hide made synchronously
    from ``dockAreaCreated`` reverts itself for the first area, and every later thing that moves that
    count reverts it again. Each hide therefore runs through a zero-delay ``QTimer`` so QtAds' own
    synchronous bookkeeping finishes first -- the same shape, and the same reason, as the tabs-menu
    button's per-manager suppression ([[appendices.qt-ads#tabs-menu-per-manager]]).

    **Every way the count moves is hooked**, not only the two that section names: a dock added or
    removed, an area created, a hidden dock *revealed* (``dockAreaViewToggled`` -- the one a shell whose
    sub-docks start hidden actually lives or dies by, and the one a narrower signal set was measured to
    miss), and a layout restore rebuilding the areas outright.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsAutoHideButtonSuppressor(dock_manager)`` alone
    is enough, with nothing to hold onto: Qt destroys it along with ``dock_manager``.

    :param dock_manager: the manager whose areas should carry no pin button.
    """

    def __init__(self, dock_manager: QtAds.CDockManager) -> None:
        super().__init__(dock_manager)
        self.__dock_manager: Final = dock_manager
        dock_manager.dockAreaCreated.connect(self.__schedule_hide)
        dock_manager.dockWidgetAdded.connect(self.__schedule_hide)
        dock_manager.dockWidgetRemoved.connect(self.__schedule_hide)
        dock_manager.dockAreaViewToggled.connect(self.__schedule_hide)
        dock_manager.stateRestored.connect(self.__schedule_hide)
        self.__schedule_hide()

    def __schedule_hide(self) -> None:
        """Queue :meth:`__hide_buttons` for the next turn of the event loop.

        Takes no arguments although most of the signals connected to it carry one (the new area, the
        added or removed dock): every hide re-walks the manager's whole area set anyway, since one
        area's change can flip a *different* area's count through one.

        Scheduled **with a context object** (``self``) rather than as a bare callable: a plain
        ``singleShot(0, bound_method)`` outlives its receiver, so a manager torn down within the same
        turn of the event loop -- a window closed right after a layout change, which is most of what a
        test does -- fires this into a deleted ``CDockManager`` and raises. Qt drops a context-bound
        one when the context dies, and this object is parented to the very manager it reads.
        """
        QTimer.singleShot(0, self, self.__hide_buttons)

    def __hide_buttons(self) -> None:
        """Hide the auto-hide button on each of the manager's currently open areas.

        Reads the area set fresh on every run rather than remembering areas as they are created:
        ``CDockManager.restoreState`` rebuilds every affected `CDockAreaWidget` from scratch, so a
        remembered one can already be gone by the time this runs.

        The button is taken unguarded: QtAds builds all four title-bar buttons in the title bar's own
        layout, so an area that exists has one -- a ``None`` check here would only be a branch nothing
        can take.
        """
        for area in self.__dock_manager.openedDockAreas():
            area.titleBarButton(QtAds.TitleBarButtonAutoHide).setVisible(False)
