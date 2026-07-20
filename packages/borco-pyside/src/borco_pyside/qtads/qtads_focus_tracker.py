"""Tracks the currently-selected dock within a QtAds `CDockManager`."""

from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, QSize, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from .qtads_widgets import tab_close_button, tab_label


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

    Styles the current dock via the :data:`TRACKED_FOCUS_PROPERTY` dynamic property it sets (and
    re-polishes) on the current dock's tab and the dock itself as current-ness moves, matched by a
    stylesheet applied to ``dock_manager`` at construction (:meth:`tracked_focus_dock_stylesheet`).
    This is the ``FocusHighlighting``-free equivalent of QtAds' own ``focused`` property styling.
    Also renders every tab's close button as :data:`CLOSE_BUTTON_TEXT` text (not an icon) so the
    same stylesheet can recolour it to stay legible against the current tab's highlight.
    Note the stylesheet's ``palette(...)`` colours are frozen to the theme active when it was
    applied; to follow a theme switch, rebuild it and re-apply on ``QApplication.paletteChanged``.

    A ``QObject``, parented to ``dock_manager`` by default -- ``QtAdsFocusTracker(dock_manager)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``dock_manager``.

    :param dock_manager: the dock manager whose docks to track.
    :param highlight: current dock's tab fill/border colour (see :meth:`tracked_focus_dock_stylesheet`).
    :param label: current dock's tab label colour (see :meth:`tracked_focus_dock_stylesheet`).
    :param title_bar: current dock's area title-bar accent colour (see
        :meth:`tracked_focus_dock_stylesheet`).
    :param parent: optional Qt parent; defaults to ``dock_manager`` itself.
    """

    TRACKED_FOCUS_PROPERTY: Final = "tracked_focus"
    """Dynamic boolean property this tracker sets on the current dock's tab (a ``CDockWidgetTab``)
    and the dock itself (a ``CDockWidget``) -- and re-polishes -- for
    :meth:`tracked_focus_dock_stylesheet`'s selectors to match on."""

    CLOSE_BUTTON_TEXT: Final = "\ue4f6"
    """Glyph shown as each tab close button's text instead of its icon. Text (not an icon) so its
    colour follows QSS ``color:`` -- normally the tab's own foreground, and :meth:`label`'s colour on
    the current tab -- letting it stay legible against the current tab's highlighted background. A
    QtAds close button's icon is a fixed ``url()`` SVG that ``color:`` cannot tint, and the style's
    fallback icon only recolors under some styles (not the native Windows one); text works
    everywhere. The default is the Phosphor ``x`` glyph, which only renders once the
    :data:`CLOSE_BUTTON_FONT` font is loaded (via ``QFontDatabase.addApplicationFont``); without it
    the button shows tofu."""

    CLOSE_BUTTON_FONT: Final = "Phosphor-Bold"
    """Font family the close button is rendered in, so :data:`CLOSE_BUTTON_TEXT`'s glyph resolves.
    The application must load this font (``QFontDatabase.addApplicationFont``) before any tracked
    dock is shown; the family is em-centered, so no per-glyph padding tuning is needed."""

    CLOSE_BUTTON_GLYPH_SIZE: Final = 12
    """Pixel size the close button glyph is rendered at -- set in code (not QSS, which QtAds ignores
    for this button's font), and re-applied on every restyle since QtAds rebuilds the button."""

    current_dock_changed: Signal = Signal(object)
    """Emitted with the newly-current dock (a ``QtAds.CDockWidget``), or ``None`` when none is
    current, whenever :attr:`current_dock` changes."""

    def __init__(
        self,
        dock_manager: QtAds.CDockManager,
        highlight: str = "palette(highlight)",
        label: str = "palette(highlighted-text)",
        title_bar: str = "palette(highlight)",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else dock_manager)
        self.__dock_manager: Final = dock_manager
        self.__current_dock: QtAds.CDockWidget | None = None
        self.__tracked_docks: Final[set[QtAds.CDockWidget]] = set()
        self.__areas_tracking_current_tab: Final[set[QtAds.CDockAreaWidget]] = set()

        dock_manager.setStyleSheet(self.tracked_focus_dock_stylesheet(highlight, label, title_bar))
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
        remembered focus after a reload. Also tracks a dock that's alone at index 0 of its area,
        which the automatic tracking can't (no ``currentChanged`` fires there).

        :param dock: the dock to make current, or ``None`` to record that none is.
        """
        if dock is not None:
            dock.setAsCurrentTab()
        self.__set_current_dock(dock)

    def save_state(self) -> bytes:
        """Serialize which dock is current, to survive a dock-manager ``restoreState`` round-trip.

        ``CDockManager.saveState`` records only the current *tab within each area*, not which area
        holds focus -- so docks split across separate areas lose their current-ness on restore
        (a fresh restore defaults to whichever dock was adopted first). Persisting this alongside
        the manager's own state, and replaying it via :meth:`restore_state`, closes that gap.

        :returns: the current dock's ``objectName`` as UTF-8 bytes, or empty when none is current.
        """
        return self.__current_dock.objectName().encode() if self.__current_dock is not None else b""

    def restore_state(self, state: bytes) -> None:
        """Re-select the dock :meth:`save_state` recorded as current, found by its ``objectName``.

        Call *after* ``CDockManager.restoreState`` has repositioned (and so re-registered by name)
        every dock. A no-op when ``state`` is empty or names a dock no longer present.

        :param state: the bytes from a prior :meth:`save_state`.
        """
        name = bytes(state).decode()
        if not name:
            return
        dock = self.__dock_manager.findDockWidget(name)
        if dock is not None:
            self.set_current_dock(dock)

    def tracked_focus_dock_stylesheet(
        self,
        highlight: str = "palette(highlight)",
        label: str = "palette(highlighted-text)",
        title_bar: str = "palette(highlight)",
    ) -> str:
        """Build the QSS styling whichever dock currently carries :data:`TRACKED_FOCUS_PROPERTY`.

        Mirrors QtAds' own ``FocusHighlighting`` reference styling, but off this tracker's custom
        property rather than QtAds' ``focused`` one. Each colour is a QSS colour expression -- a
        ``palette(role)`` reference (theme-aware on each re-apply) or a literal ``#rrggbb``/``rgb(...)``.

        Also carries a plain ``#tabCloseButton`` rule zeroing every tab close button's icon size, so
        the :data:`CLOSE_BUTTON_TEXT` text :meth:`__style_close_button` sets shows alone. Done in QSS
        (not just Python) because QtAds re-polishes the button on every tab activation, which would
        otherwise re-apply its 16px icon size -- the rule re-applies 0 on each such repolish instead.

        :param highlight: fill/border colour of the current dock's tab. Default ``palette(highlight)``.
        :param label: text colour of the current dock's tab label *and* its close button (drawn as
            :data:`CLOSE_BUTTON_TEXT`, not an icon, so this recolors it). Default
            ``palette(highlighted-text)`` -- the role guaranteed to contrast ``highlight`` in both
            light and dark themes.
        :param title_bar: colour of the accent line just below the title bar (drawn as the current
            dock's top border). Default ``palette(highlight)``.
        :returns: a QSS string, ready for ``setStyleSheet`` (or appended to an existing one).
        """
        prop = self.TRACKED_FOCUS_PROPERTY
        return f"""\
#tabCloseButton {{
    qproperty-iconSize: 0px;
    padding: 0px;
}}
ads--CDockWidgetTab[{prop}="true"] {{
    background: {highlight};
    border-color: {highlight};
    padding-bottom: 1px;
}}
ads--CDockWidgetTab[{prop}="true"] QLabel {{
    color: {label};
}}
ads--CDockWidgetTab[{prop}="true"] #tabCloseButton {{
    color: {label};
}}
ads--CDockWidget[{prop}="true"] {{
    border-top: 1px solid {title_bar};
}}
"""

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
        dock.viewToggled.connect(lambda visible: self.__on_view_toggled(dock, visible))
        self.__defer_close_button_style(dock)
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

    def __on_view_toggled(self, dock: QtAds.CDockWidget, visible: bool) -> None:
        """Follow a dock hidden/shown by its ``toggleViewAction``: make current-ness track visibility.

        Showing a dock makes it current (focus moves to the surface you just revealed); hiding the
        current dock moves current to another still-visible one (or nothing, if none remain), so the
        remaining surface takes focus rather than the hidden one keeping it. Skipped while the
        manager is restoring state -- ``restoreState`` fires ``viewToggled`` for every reconstructed
        dock, and :meth:`restore_state` re-selects the saved current dock explicitly afterwards.

        :param dock: the dock whose visibility just changed.
        :param visible: the dock's new visibility.
        """
        if self.__dock_manager.isRestoringState():
            return
        if visible:
            self.set_current_dock(dock)
        elif dock is self.__current_dock:
            # Reached only when hiding the current dock did *not* move Qt focus into another tracked
            # dock -- if it had, ``focusChanged`` would already have re-selected that real neighbour
            # (Qt moves focus synchronously, before this fires). So nothing tracked is focused now;
            # clear rather than fabricate a current dock no real focus points at.
            self.__set_current_dock(None)

    def __tracked_dock_ancestor(self, widget: QWidget | None) -> QtAds.CDockWidget | None:
        """The tracked dock that is ``widget`` or encloses it, or ``None`` if none does.

        :param widget: the widget to walk up from (e.g. the global focus widget).
        :returns: the enclosing tracked dock, or ``None``.
        """
        while widget is not None:
            if isinstance(widget, QtAds.CDockWidget) and widget in self.__tracked_docks:
                return widget
            widget = widget.parentWidget()
        return None

    def __on_state_restored(self) -> None:
        """Re-track areas after a layout restore, and resync the current dock to the restored tab.

        ``restoreState`` sets each area's current tab from the saved layout and fires that area's
        ``currentChanged`` -- but *during* the restore, before this method reconnects the areas, so
        it's missed and :attr:`current_dock` would otherwise stay on whatever was current before
        (e.g. a dock the restore has since stacked *behind* another). Reading the current tab of the
        stale current dock's area back here corrects it, without needing the user to click first.

        Also re-runs :meth:`__style_close_button` on every tracked dock: ``restoreState`` rebuilds
        the tabs, so each dock's close button is a fresh one back to showing QtAds' default icon.
        """
        for dock in self.__tracked_docks:
            self.__defer_close_button_style(dock)
            if area := dock.dockAreaWidget():
                self.__track_area(area)
        if self.__current_dock is not None:
            area = self.__current_dock.dockAreaWidget()
            if area is not None:
                restored_current = area.dockWidget(area.currentIndex())
                if restored_current in self.__tracked_docks:
                    self.__set_current_dock(restored_current)

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
        dock = self.__tracked_dock_ancestor(now)
        if dock is not None:
            self.__set_current_dock(dock)

    def __set_current_dock(self, dock: QtAds.CDockWidget | None) -> None:
        if dock is self.__current_dock:
            return
        previous = self.__current_dock
        self.__current_dock = dock
        if previous is not None:
            self.__style_dock(previous, False)
        if dock is not None:
            self.__style_dock(dock, True)
        self.current_dock_changed.emit(dock)

    def __style_dock(self, dock: QtAds.CDockWidget, current: bool) -> None:
        """Reflect ``dock``'s current-ness by toggling (and re-polishing) the tracked-focus property.

        Sets ``tracked_focus`` on ``dock`` (styled with the accent line -- its top border, just below
        the title bar) and on its ``tab`` (the highlight fill), then re-polishes them plus the tab's
        label. A descendant rule (e.g. ``...CDockWidgetTab[tracked_focus] QLabel``) re-evaluates only
        when the descendant itself is re-polished, never merely because its ancestor was; QSS does not
        cascade ``color`` across child widgets the way CSS does.

        Defensive against a ``dock`` mid-teardown (e.g. the one just removed): Shiboken can flag its
        tab "already deleted" transiently, surfacing as ``RuntimeError`` -- harmless to skip.

        :param dock: the dock whose styling to update.
        :param current: whether ``dock`` is now the current one.
        """
        try:
            tab = dock.tabWidget()
            dock.setProperty(self.TRACKED_FOCUS_PROPERTY, current)
            tab.setProperty(self.TRACKED_FOCUS_PROPERTY, current)
            widgets: list[QWidget] = [dock, tab, tab_label(dock)]
            if (button := tab_close_button(dock)) is not None:
                widgets.append(button)
            self.__repolish(*widgets)
        except RuntimeError:
            pass

    def __defer_close_button_style(self, dock: QtAds.CDockWidget) -> None:
        """Schedule :meth:`__style_close_button` for ``dock`` on the next event-loop tick.

        Deferred, not immediate, because QtAds re-applies the close button's own icon and 16px icon
        size *after* it emits ``dockWidgetAdded`` (and after a restore) for the tab it then makes
        active -- overwriting an eager restyle (confirmed empirically: the first/active tab kept
        QtAds' icon while a tabbed-in one styled correctly). A zero-delay timer runs once that
        synchronous QtAds setup has finished.

        :param dock: the dock whose close button to restyle once QtAds has finished with it.
        """
        QTimer.singleShot(0, lambda: self.__style_close_button(dock))

    def __style_close_button(self, dock: QtAds.CDockWidget) -> None:
        """Render ``dock``'s tab close button as :data:`CLOSE_BUTTON_TEXT` text rather than an icon.

        Shows :data:`CLOSE_BUTTON_TEXT` as text and hides QtAds' own close icon by zeroing the
        button's icon size (rather than clearing the icon, which QtAds re-sets) -- so QSS ``color:``
        recolours it, see :data:`CLOSE_BUTTON_TEXT`. Called (deferred) whenever the button is
        (re)created: on ``dockWidgetAdded`` and after a layout restore rebuilds the tabs. A no-op if
        this tab shows no close button (no close-button config flag).

        Defensive against a ``dock`` mid-teardown, like :meth:`__style_dock`: ``RuntimeError`` from a
        tab Shiboken has already flagged deleted is harmless to skip -- and expected, since the
        deferred timer can fire after ``dock`` has since been closed.

        :param dock: the dock whose close button to restyle.
        """
        try:
            button = tab_close_button(dock)
        except RuntimeError:
            return
        if button is not None:
            button.setIconSize(QSize(0, 0))
            button.setText(self.CLOSE_BUTTON_TEXT)
            font = button.font()
            font.setFamily(self.CLOSE_BUTTON_FONT)
            font.setPixelSize(self.CLOSE_BUTTON_GLYPH_SIZE)
            button.setFont(font)
            side = button.height()
            button.setFixedSize(side, side)

    @staticmethod
    def __repolish(*widgets: QWidget) -> None:
        """Force ``widgets`` to re-evaluate the stylesheet (e.g. after a property change).

        :param widgets: the widgets to unpolish/re-polish, in order.
        """
        for widget in widgets:
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
