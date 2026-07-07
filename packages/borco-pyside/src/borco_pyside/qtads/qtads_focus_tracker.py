"""Tracks the currently-selected dock within a QtAds `CDockManager`."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from borco_pyside.qtads.qtads_utils import tab_label


class QtAdsFocusTracker(QObject):
    """Tracks which dock in one `CDockManager` counts as "current" (selected/focused).

    Combines every signal actually needed to catch a tab switch, confirmed empirically (see
    [[appendices.qt-ads]]) not to be covered by any single QtAds signal alone:

    * ``CDockAreaWidget.currentChanged`` -- ordinary tab-bar switching within a shared area.
    * an area's own tabs-menu ``QMenu.triggered`` -- picking an already-current lone tab from the
      dropdown never actually changes ``currentChanged``'s index.
    * a dock's own tab-label ``clicked`` -- a dock alone in its own area is always index 0, so
      clicking it never changes ``currentChanged``'s index either.
    * ``QApplication.focusChanged`` -- real keyboard focus moving into a different,
      already-visible split area, which changes no area's current-tab index at all.

    Every dock QtAds adds to (or removes from) ``dock_manager`` is tracked automatically via
    ``dockWidgetAdded``/``dockWidgetRemoved``; a layout restore's ``stateRestored`` re-tracks every
    still-registered dock's (possibly rebuilt) area, since ``CDockManager.restoreState()`` rebuilds
    every affected ``CDockAreaWidget`` from scratch, orphaning connections made before the call.

    Deliberately avoids QtAds's own ``FocusHighlighting``/``setDockWidgetFocused()`` machinery --
    it stores the focused dock on a *shared* native ``QWindow`` property, so multiple nested
    ``CDockManager``s sharing one real top-level window cross-contaminate each other's focus state
    (see [[appendices.qt-ads#focus-highlighting]]). Each :class:`QtAdsFocusTracker` instance only
    ever reads/writes its own bookkeeping, so nesting several (one per manager) is safe.

    A ``QObject``, parented to ``dock_manager`` by default -- ``QtAdsFocusTracker(dock_manager)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``dock_manager``.

    :param dock_manager: the dock manager whose docks to track.
    :param current_dock_marker: prefix added to the current dock's tab title, stripped from
        whichever dock stops being current; empty (the default) skips marking titles at all.
    :param parent: optional Qt parent; defaults to ``dock_manager`` itself.
    """

    current_dock_changed: Signal = Signal(object)
    """Emitted with the newly-current dock (a ``QtAds.CDockWidget``), or ``None`` when none is
    current, whenever :attr:`current_dock` changes."""

    def __init__(
        self,
        dock_manager: QtAds.CDockManager,
        current_dock_marker: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else dock_manager)
        self.__marker: Final = current_dock_marker
        self.__current_dock: QtAds.CDockWidget | None = None
        self.__tracked_docks: Final[set[QtAds.CDockWidget]] = set()
        self.__areas_tracking_current_tab: Final[set[QtAds.CDockAreaWidget]] = set()

        dock_manager.dockWidgetAdded.connect(self.__on_dock_widget_added)
        dock_manager.dockWidgetRemoved.connect(self.__on_dock_widget_removed)
        dock_manager.stateRestored.connect(self.__on_state_restored)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self.__on_application_focus_changed)

    @property
    def current_dock(self) -> QtAds.CDockWidget | None:
        """The dock currently tracked as current, or ``None`` if none is."""
        return self.__current_dock

    def set_current_dock(self, dock: QtAds.CDockWidget | None) -> None:
        """Make ``dock`` the current one: bring its tab to the front of its area, and track it.

        The explicit counterpart to the automatic tracking (tab switches, tab-label clicks,
        tabs-menu picks, keyboard focus) -- for driving current-ness from code rather than user
        interaction. Reveals a dock stacked behind others by raising it (``setAsCurrentTab``), so
        this is how you focus/show a specific dock: pick a particular document tab, or restore a
        remembered focus after a reload. Also marks a dock that's alone at index 0 of its area,
        which the automatic tracking can't (no ``currentChanged`` fires there).

        :param dock: the dock to make current, or ``None`` to mark that none is.
        """
        if dock is not None:
            dock.setAsCurrentTab()
        self.__set_current_dock(dock)

    def __on_dock_widget_added(self, dock: QtAds.CDockWidget) -> None:
        """Start tracking a dock QtAds just added: its tab-label click and its area's tab switches.

        Also adopts ``dock`` as current in the two cases the area's own ``currentChanged`` can't
        cover on its own:

        * it joins an **existing** area (tabbed in) -- it becomes that area's current tab, but
          QtAds fires the area's ``currentChanged`` *before* emitting ``dockWidgetAdded``, so at
          that point ``dock`` isn't tracked yet and :meth:`__on_area_current_changed` drops it.
        * nothing is current yet -- the first dock overall, sitting at index 0 of a fresh area,
          which fires no ``currentChanged`` at all (no prior index to change *from*).

        A dock that opens a **new** area while something is already current (a deliberate split,
        e.g. a second surface built after the first) is left as-is; focus it with
        :meth:`set_current_dock` if it should steal current-ness.

        :param dock: the dock QtAds just added to the tracked manager.
        """
        self.__tracked_docks.add(dock)
        tab_label(dock).clicked.connect(lambda: self.__set_current_dock(dock))
        area = dock.dockAreaWidget()
        joins_existing_area = area is not None and area in self.__areas_tracking_current_tab
        if area is not None:
            self.__track_area(area)
        if joins_existing_area or self.__current_dock is None:
            self.__set_current_dock(dock)

    def __on_dock_widget_removed(self, dock: QtAds.CDockWidget) -> None:
        """Stop tracking a dock QtAds just removed, clearing it as current if it was.

        :param dock: the dock QtAds just removed from the tracked manager.
        """
        self.__tracked_docks.discard(dock)
        if self.__current_dock is dock:
            self.__set_current_dock(None)

    def __on_state_restored(self) -> None:
        """Re-track every still-registered dock's (possibly rebuilt) area after a layout restore."""
        for dock in self.__tracked_docks:
            if area := dock.dockAreaWidget():
                self.__track_area(area)

    def __track_area(self, area: QtAds.CDockAreaWidget) -> None:
        """Connect ``area.currentChanged`` and its tabs-menu to track tab switches, once per area.

        :param area: the dock area to track; a no-op if already tracked (e.g. a new dock joining
            an already-open area, which shares that area's existing connection).
        """
        if area not in self.__areas_tracking_current_tab:
            self.__areas_tracking_current_tab.add(area)
            area.currentChanged.connect(lambda index: self.__on_area_current_changed(area, index))
            menu = area.titleBarButton(QtAds.TitleBarButtonTabsMenu).menu()
            menu.triggered.connect(lambda action: self.__on_area_current_changed(area, action.data()))

    def __on_area_current_changed(self, area: QtAds.CDockAreaWidget, index: int) -> None:
        """Track the current dock whenever the user switches tabs within ``area``.

        A stale connection from an area a restore has since replaced can still fire while
        ``CDockManager.restoreState()`` tears the old one down -- Shiboken flags the old area's
        wrapper "already deleted" partway through that teardown, before Qt's own
        auto-disconnect-on-destroy takes effect. Harmless to just ignore.

        :param area: the dock area whose current tab changed.
        :param index: the newly-current tab's index within ``area``.
        """
        try:
            dock = area.dockWidget(index)
        except RuntimeError:
            return
        if dock in self.__tracked_docks:
            self.__set_current_dock(dock)

    def __on_application_focus_changed(self, _old: QWidget | None, now: QWidget | None) -> None:
        """Track the current dock whenever real Qt keyboard focus moves into a tracked one.

        Catches focus moving into a *different, already-visible split area* (e.g. clicking a
        field in another dock's content), which changes no area's current-tab index at all.

        :param _old: the widget that just lost focus; unused.
        :param now: the widget that gained focus, or ``None`` if focus left the application.
        """
        widget: QWidget | None = now
        while widget is not None:
            if isinstance(widget, QtAds.CDockWidget) and widget in self.__tracked_docks:
                self.__set_current_dock(widget)
                return
            widget = widget.parentWidget()

    def __set_current_dock(self, dock: QtAds.CDockWidget | None) -> None:
        if dock is self.__current_dock:
            return
        previous = self.__current_dock
        self.__current_dock = dock
        if self.__marker:
            if previous is not None:
                self.__mark(previous, False)
            if dock is not None:
                self.__mark(dock, True)
        self.current_dock_changed.emit(dock)

    def __mark(self, dock: QtAds.CDockWidget, current: bool) -> None:
        """Prefix or strip :attr:`__marker` from ``dock``'s tab title, in place.

        :param dock: the dock whose title to mark or unmark.
        :param current: whether ``dock`` is now the current one.
        """
        title = dock.windowTitle().removeprefix(self.__marker)
        dock.setWindowTitle(f"{self.__marker}{title}" if current else title)
