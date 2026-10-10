"""Hides the tab of a dock with title-bar actions while it is alone in a floating window."""

from typing import cast, override

import PySide6QtAds as QtAds
from PySide6.QtCore import QEvent, QObject, QTimer


class QtAdsLoneTabHider(QObject):
    """Hides the tab of any dock of **one** `CDockManager` that has title-bar actions, while that dock is alone in
    a floating window, and shows it again once it is not.

    QtAds hides the whole title bar -- and with it the tab -- of a dock alone in a floating window, the window's
    own title saying what it is, **unless the dock has title-bar actions**, which it keeps reachable by keeping
    the bar. So a dock with actions floated alone kept a lone tab no other dock shows. Hiding just that tab keeps
    the bar and its buttons and drops the tab that names the window a second time. The tab comes back as another
    dock joins the window or the dock docks again -- only a tab this hid, so the neighbours' tabs a maximize hides
    on purpose stay hidden.

    Every dock the manager has, and every one it adds, is watched; which of them need it is decided as each
    decision is made, from the actions the dock has then, so actions given after the dock was added count too.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsLoneTabHider(dock_manager)`` alone is enough, with
    nothing to hold onto: Qt destroys it along with ``dock_manager``, and each dock's own watcher with the dock.

    :param dock_manager: the manager whose docks should hide their lone tab.
    """

    def __init__(self, dock_manager: QtAds.CDockManager) -> None:
        super().__init__(dock_manager)
        dock_manager.dockWidgetAdded.connect(self.__watch)
        for dock in dock_manager.dockWidgetsMap().values():
            self.__watch(dock)

    @staticmethod
    def __watch(dock: QtAds.CDockWidget) -> None:
        """Give ``dock`` a watcher, unless it has one from an earlier add.

        A dock taken out of the manager keeps its watcher (it is the dock's child), so one added back is not
        given a second.

        :param dock: a dock of the manager this hider is built for.
        """
        if dock.findChild(LoneTabWatcher) is None:
            LoneTabWatcher(dock)


class LoneTabWatcher(QObject):
    """The per-dock half of `QtAdsLoneTabHider`: hides one dock's tab while it floats alone with actions.

    **When to re-decide.** ``CDockWidget.isFloating()`` is true exactly while the dock is alone in a floating
    window. No one signal marks every change of it (measured): ``topLevelChanged`` covers a dock joining or
    leaving the window, but not the dock re-docking or floating out again, which reparent it instead. So both
    are watched, and the decision runs a turn of the event loop later, once QtAds has finished the move.

    A ``QObject`` parented to ``dock``. It reads the dock from its Qt parent on each use rather than keeping
    it: a kept wrapper closes a cycle with the child wrapper the dock's own holds, and Python's collector then
    clears this object's attributes while its C++ side still filters the dock's events (measured, in a test's
    teardown).

    :param dock: the dock whose tab to manage.
    """

    def __init__(self, dock: QtAds.CDockWidget) -> None:
        super().__init__(dock)
        self.__tab_hidden: bool = False
        dock.topLevelChanged.connect(self.__schedule)
        dock.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Re-decide when the dock is reparented, which is how a re-dock or a fresh float reaches it.

        :param watched: the dock.
        :param event: the event.
        :returns: ``False``, always: the event goes on.
        """
        if event.type() == QEvent.Type.ParentChange and watched is self.parent():
            self.__schedule()
        return False

    def __schedule(self, *_args: object) -> None:
        """Queue :meth:`__apply` for the next turn of the event loop.

        Bound to this object, so a dock deleted meanwhile takes the call with it.
        """
        QTimer.singleShot(0, self, self.__apply)

    def __apply(self) -> None:
        """Hide the tab while the dock floats alone with actions; show it again, if this hid it, once it does not.

        Claims a tab only if it was shown: one already hidden by another party stays that party's to show.
        """
        dock = cast(QtAds.CDockWidget, self.parent())
        tab = dock.tabWidget()
        if dock.isFloating() and dock.titleBarActions():
            if not tab.isHidden():
                tab.setVisible(False)
                self.__tab_hidden = True
        elif self.__tab_hidden:
            self.__tab_hidden = False
            if not dock.isClosed():
                tab.setVisible(True)
