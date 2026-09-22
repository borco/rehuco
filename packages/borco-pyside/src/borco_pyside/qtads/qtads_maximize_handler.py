"""A per-tab maximize toggle on every dock of one QtAds `CDockManager`."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QBoxLayout, QPushButton, QSplitter

from ..theming import Glyph
from .qtads_widgets import TAB_MAXIMIZE_BUTTON_NAME, tab_close_button


# the handler holds three cohesive pieces of state that happen to be counted separately: what it
# maximizes (manager, dock, hidden areas, splitter sizes), how it draws the button (two glyphs and
# a size) and the buttons themselves -- none is separable without splitting one concern, the same
# call the focus tracker makes
class QtAdsMaximizeHandler(QObject):  # pylint: disable=too-many-instance-attributes
    """Puts a checkable **maximize** button on every dock's tab of **one** `CDockManager`, between
    the title and the tab's close button, and does the maximizing.

    Toggled on, the dock is the only thing left on screen: it is brought to the front of its area,
    the area's other tabs are hidden, every *sibling* area of the same container is hidden
    (``CDockAreaWidget.setVisible(False)``), and QtAds' splitters hand the freed room to the one
    left. Toggled off, exactly the tabs and areas that were hidden are shown again, the areas at
    the sizes they had. The container is the scope, not the manager: a dock living in a floating
    window fills that window and leaves the main one alone. A dock already alone in its container
    has nothing to hide -- maximizing it is a no-op that still checks the button, so the toggle
    reads consistently. Hiding the neighbouring tabs is what keeps the state readable: left in the
    tab bar, one of them could be maximized with nothing visible happening, and its restore would
    then put back everything the first maximize hid.

    **Why hide/show and not QtAds itself.** QtAds has no maximize: ``closeOtherAreas()`` *closes*
    the siblings (their docks read closed, their toggle actions un-check), and the ``showMaximized``
    family is plain window state. Hiding the sibling *areas* was measured to do the right thing
    instead: it fires no signal at all -- no ``dockAreaViewToggled``, no dock ``viewToggled``, no
    ``dockAreasAdded``/``Removed`` -- so no dock reads closed, nothing else reacts, and
    ``openedDockAreas()`` (which filters on ``isHidden()``) simply stops listing the hidden ones
    ([[appendices.qt-ads#area-maximize]]).

    **Session-only, and a capture must undo it first.** Nothing here is persisted, and a
    ``saveState()`` taken while maximized would record the hidden areas' splitter panes at zero --
    restoring that blob later gives a sliver, not the layout the user had. :meth:`unmaximized` is
    the seam: it shows the hidden areas for the duration of a capture and hides them again after,
    with the button and the maximize itself left exactly as they were.

    **The splitter sizes are remembered, not trusted.** ``QSplitter`` keeps a hidden pane's size
    and hands it back on show (measured, two and three panes, nested), so a plain show would
    usually do -- but that is the splitter's own bookkeeping, not a promise, and a pane QtAds keeps
    for a *closed* dock is one it re-divides freely. So every splitter under the container is
    recorded as a dock is maximized, and re-applied after each show, in :meth:`restore` and inside
    :meth:`unmaximized` alike: what the user had is what comes back, whatever the splitter decided.

    **Any structural change exits maximize first.** An area added or removed (a dock dragged out or
    docked in), a dock added or removed, a dock or an area shown or hidden by a toggle
    (``viewToggled``, ``dockAreaViewToggled``) all call :meth:`restore` synchronously from the
    signal, so whatever the app does in reaction sees the un-maximized layout. A layout restore
    rebuilds every area from scratch, so the bookkeeping is dropped on ``stateRestored`` -- the
    tabs, and the buttons on them, survive a restore (the same objects, reparented). A dock toggled
    inside a hidden sibling can leave that area with no open docks; showing such an area back would
    put an empty box on screen, so :meth:`restore` skips it.

    **The button is the app's, drawn like the tab's own close button.** QtAds builds a tab's label
    and close button in the tab's own layout, and a Python-subclassed tab through the factory
    crashes ([[appendices.qt-ads#custom-tab-widget]]); an ordinary `QPushButton` -- the close
    button's own kind -- inserted into that layout right after the title works
    ([[appendices.qt-ads#tab-layout-insert]]). It shows an icon-font glyph as **text**, squared to
    the tab's height, exactly as `QtAdsFocusTracker` draws the close button, so the same QSS
    ``color:`` that keeps the close glyph legible on the current tab's highlight covers this one,
    and the tracker derives the button's rest, hover and pressed look from QtAds' own
    ``#tabCloseButton`` rules (:meth:`QtAdsFocusTracker.tab_maximize_button_stylesheet`). Two
    glyphs tell the states apart: ``glyph`` at rest, ``maximized_glyph`` while its dock fills the
    container.

    A ``QObject``, parented to ``dock_manager`` -- ``QtAdsMaximizeHandler(dock_manager, glyph)``
    alone is enough, with nothing to hold onto unless a caller wants :meth:`unmaximized`.

    :param dock_manager: the manager whose docks get the button.
    :param glyph: the :class:`~borco_pyside.theming.Glyph` (codepoint + font family) drawn as the
        button's text while its dock is not maximized; a family must be loaded before any dock is
        shown, and an empty one keeps the inherited UI font.
    :param maximized_glyph: the glyph drawn while its dock is maximized -- a "restore" mark.
        Defaults to ``glyph``.
    :param glyph_size: pixel size the glyphs are rendered at. Defaults to :data:`DEFAULT_GLYPH_SIZE`.
    """

    BUTTON_OBJECT_NAME: Final = TAB_MAXIMIZE_BUTTON_NAME
    """Object name of every button this handler inserts, for a stylesheet rule or a test to find --
    what `QtAdsFocusTracker`'s stylesheet recolours on the current tab, beside ``#tabCloseButton``,
    and what it re-polishes as current-ness moves so that rule takes on the button itself."""

    DEFAULT_GLYPH_SIZE: Final = 12
    """Default pixel size the glyph is rendered at, matching the tracker's close glyph."""

    MAXIMIZE_TOOLTIP: Final = "Maximize"
    RESTORE_TOOLTIP: Final = "Restore"
    """The button's tooltip while its dock is un-maximized, and while it is maximized."""

    maximized_changed: Signal = Signal(bool)
    """Emitted with ``True`` as a dock is maximized and ``False`` as it is restored."""

    def __init__(
        self,
        dock_manager: QtAds.CDockManager,
        glyph: Glyph,
        maximized_glyph: Glyph | None = None,
        glyph_size: int = DEFAULT_GLYPH_SIZE,
    ) -> None:
        super().__init__(dock_manager)
        self.__dock_manager: Final = dock_manager
        self.__glyph: Final = glyph
        self.__maximized_glyph: Final = maximized_glyph if maximized_glyph is not None else glyph
        self.__glyph_size: Final = glyph_size
        self.__maximized_dock: QtAds.CDockWidget | None = None
        self.__hidden_areas: list[QtAds.CDockAreaWidget] = []
        self.__hidden_tabs: list[QtAds.CDockWidget] = []
        self.__splitter_sizes: dict[QSplitter, list[int]] = {}
        self.__buttons: Final[dict[QtAds.CDockWidget, QPushButton]] = {}

        dock_manager.dockWidgetAdded.connect(self.__on_dock_widget_added)
        dock_manager.dockWidgetRemoved.connect(self.__on_dock_widget_removed)
        dock_manager.dockAreasAdded.connect(self.__on_structural_change)
        dock_manager.dockAreasRemoved.connect(self.__on_structural_change)
        dock_manager.dockAreaViewToggled.connect(self.__on_structural_change)
        dock_manager.stateRestored.connect(self.__on_state_restored)
        for dock in dock_manager.dockWidgetsMap().values():
            dock.viewToggled.connect(self.__on_structural_change)
        self.__schedule_walk()

    @property
    def maximized_dock(self) -> QtAds.CDockWidget | None:
        """The dock currently filling its container, or ``None`` while none is."""
        return self.__maximized_dock

    def button(self, dock: QtAds.CDockWidget) -> QPushButton | None:
        """The maximize button this handler put on ``dock``'s tab, or ``None`` if it has none yet
        (the walk is deferred).

        :param dock: the dock to look up.
        :returns: its button, or ``None``.
        """
        return self.__buttons.get(dock)

    def maximize(self, dock: QtAds.CDockWidget) -> None:
        """Bring ``dock`` to the front, hide the other tabs of its area, and grow the area over every
        other open area of its container -- so ``dock`` is the only thing left on screen.

        A no-op if ``dock`` is already the maximized one, or has no area; another dock maximized in
        this manager is restored first, so at most one stands at a time.

        :param dock: the dock to fill its container with.
        """
        if dock is self.__maximized_dock:
            return
        area = dock.dockAreaWidget()
        if area is None:
            self.__sync_button(dock)
            return
        self.restore()
        container = area.dockContainer()
        self.__maximized_dock = dock
        self.__hidden_areas = [sibling for sibling in container.openedDockAreas() if sibling is not area]
        self.__hidden_tabs = [sibling for sibling in area.openedDockWidgets() if sibling is not dock]
        self.__splitter_sizes = {splitter: splitter.sizes() for splitter in container.findChildren(QSplitter)}
        dock.setAsCurrentTab()
        for sibling in self.__hidden_areas:
            sibling.setVisible(False)
        self.__set_tabs_visible(self.__hidden_tabs, False)
        self.__sync_button(dock)
        self.maximized_changed.emit(True)

    def restore(self) -> None:
        """Show back the areas :meth:`maximize` hid, and un-check the button. A no-op while nothing
        is maximized, so every exit hook can call it unconditionally.

        An area whose every dock was toggled closed while it sat hidden is skipped: showing it would
        put an empty area on screen, and QtAds itself hides an area as its last dock closes.
        """
        if self.__maximized_dock is None:
            return
        dock, self.__maximized_dock = self.__maximized_dock, None
        hidden, self.__hidden_areas = self.__hidden_areas, []
        tabs, self.__hidden_tabs = self.__hidden_tabs, []
        sizes, self.__splitter_sizes = self.__splitter_sizes, {}
        self.__set_tabs_visible(tabs, True)
        self.__show_areas(hidden, sizes)
        self.__sync_button(dock)
        self.maximized_changed.emit(False)

    @contextmanager
    def unmaximized(self) -> Generator[None]:
        """Show the hidden areas back for the duration of the block, then hide them again.

        For a layout capture (``CDockManager.saveState()``) taken while a dock is maximized: the
        blob then records every area at its real size rather than the hidden ones at zero, and the
        user sees no change -- the maximize, and the checked button, are exactly as they were after
        the block. A plain pass-through while nothing is maximized.
        """
        if self.__maximized_dock is None:
            yield
            return
        hidden = list(self.__hidden_areas)
        tabs = list(self.__hidden_tabs)
        self.__set_tabs_visible(tabs, True)
        self.__show_areas(hidden, self.__splitter_sizes)
        try:
            yield
        finally:
            for area in hidden:
                try:
                    area.setVisible(False)
                except RuntimeError:
                    pass
            self.__set_tabs_visible(tabs, False)

    @staticmethod
    def __set_tabs_visible(docks: list[QtAds.CDockWidget], visible: bool) -> None:
        """Hide or show the tabs of ``docks`` -- the maximized dock's neighbours in its own area.

        The tab widgets only: the docks stay open, so nothing reads closed and no toggle action
        moves, and QtAds neither re-shows a hidden tab on a resize or a current change nor lists it
        in the area's tabs menu (measured). Defensive against a dock Shiboken has already flagged
        deleted, like :meth:`__show_areas`.

        :param docks: the docks whose tabs to hide or show.
        :param visible: whether to show them.
        """
        for dock in docks:
            try:
                dock.tabWidget().setVisible(visible)
            except RuntimeError:
                pass

    @staticmethod
    def __show_areas(areas: list[QtAds.CDockAreaWidget], splitter_sizes: dict[QSplitter, list[int]]) -> None:
        """Show each of ``areas`` that still has an open dock, then put every splitter back to the
        sizes recorded as they were hidden.

        The splitter only re-divides its room on a ``LayoutRequest``, which Qt posts rather than
        delivers, so the sizes are settled here synchronously by delivering the posted requests --
        no turn of the event loop, nothing else let through -- before the recorded ones go back on
        top. Otherwise a capture in the same call would still read the shown panes at zero
        (measured: ``[800, 0]``).

        Defensive against an area or splitter Shiboken has already flagged deleted
        (``RuntimeError``): an exit hook can run mid-teardown, the same way `QtAdsFocusTracker`
        guards its own late slots.

        :param areas: the areas a maximize hid.
        :param splitter_sizes: each splitter's sizes from before the hide.
        """
        for area in areas:
            try:
                if area.openDockWidgetsCount() > 0:
                    area.setVisible(True)
            except RuntimeError:
                pass
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        for splitter, sizes in splitter_sizes.items():
            try:
                splitter.setSizes(sizes)
            except RuntimeError:
                pass

    def __on_dock_widget_added(self, dock: QtAds.CDockWidget) -> None:
        """Exit a standing maximize for the structural change, then hook and dress the new dock.

        :param dock: the dock QtAds just added.
        """
        self.__on_structural_change()
        dock.viewToggled.connect(self.__on_structural_change)
        self.__schedule_walk()

    def __on_dock_widget_removed(self, dock: QtAds.CDockWidget) -> None:
        """Exit a standing maximize for the structural change, and forget the dock's button -- it
        goes with the dock's tab.

        :param dock: the dock QtAds just removed.
        """
        self.__on_structural_change()
        self.__buttons.pop(dock, None)

    def __on_structural_change(self) -> None:
        """Exit a standing maximize before the app reacts to the change.

        Takes no arguments although most of the signals connected to it carry one (the dock, the
        area and its new state): what changed does not matter, only that the area set or its
        visibility did. Skipped while the manager is restoring a layout -- ``restoreState`` fires
        ``dockAreaViewToggled`` for every area it rebuilds, and :meth:`__on_state_restored` settles
        that case once at the end instead.
        """
        if not self.__dock_manager.isRestoringState():
            self.restore()

    def __on_state_restored(self) -> None:
        """Drop the bookkeeping a layout restore just invalidated, and re-assert the buttons.

        ``restoreState`` rebuilds every affected area from scratch: the hidden ones are gone (or
        are about to be), and the restored layout is whatever the blob says, un-maximized by
        construction (see :meth:`unmaximized`) -- so there is nothing to show back, only state to
        forget. The tabs survive a restore (reparented, not recreated), so the buttons on them are
        put back to un-checked rather than rebuilt.
        """
        dock, self.__maximized_dock = self.__maximized_dock, None
        self.__hidden_areas = []
        self.__hidden_tabs = []
        self.__splitter_sizes = {}
        if dock is not None:
            self.__sync_button(dock)
        self.__schedule_walk()

    def __schedule_walk(self) -> None:
        """Queue :meth:`__insert_buttons` for the next turn of the event loop.

        Deferred, with ``self`` as the context object, for the reasons
        `QtAdsAutoHideButtonSuppressor` gives: QtAds finishes its own synchronous tab bookkeeping
        first, and a manager torn down within the same turn cancels the call rather than receiving
        it.
        """
        QTimer.singleShot(0, self, self.__insert_buttons)

    def __insert_buttons(self) -> None:
        """Put a button on every registered dock's tab that has none yet.

        Reads the dock registry fresh on every run rather than remembering docks as they are added,
        the same way the suppressor re-walks its areas.
        """
        for dock in self.__dock_manager.dockWidgetsMap().values():
            if dock not in self.__buttons:
                self.__insert_button(dock)

    def __insert_button(self, dock: QtAds.CDockWidget) -> None:
        """Build ``dock``'s button, drawn like its tab's close button, and insert it between the
        tab's title and its close button, with the title's own spacing repeated ahead of the close
        button -- the tab's layout is title, spacing, close button, trailing spacing, so the button
        goes in at index 2 and a spacing of the same width follows it, keeping the close button as
        far from the maximize button as the maximize button is from the title.

        :param dock: the dock to give a button.
        """
        tab = dock.tabWidget()
        layout = tab.layout()
        if not isinstance(layout, QBoxLayout):  # pragma: no cover  (verified empirically: QtAds always builds one)
            return
        button = QPushButton(tab)
        button.setObjectName(self.BUTTON_OBJECT_NAME)
        button.setCheckable(True)
        font = button.font()
        if self.__glyph.family:
            font.setFamily(self.__glyph.family)
        font.setPixelSize(self.__glyph_size)
        button.setFont(font)
        # squared to the tab's own height, the way the tracker squares the close button -- read off
        # the tab rather than the close button, whose own squaring is deferred and may not have run
        close_button = tab_close_button(dock)
        side = tab.height() if tab.height() > 0 else button.sizeHint().height()
        if close_button is not None:
            side = min(side, close_button.height()) if close_button.height() > 0 else side
            button.setFocusPolicy(close_button.focusPolicy())
        button.setFixedSize(side, side)
        spacing_item = layout.itemAt(1)
        spacing = spacing_item.sizeHint().width() if spacing_item is not None else layout.spacing()
        layout.insertWidget(2, button)
        layout.insertSpacing(3, spacing)
        self.__buttons[dock] = button  # pylint: disable=unsupported-assignment-operation
        self.__sync_button(dock)
        button.toggled.connect(lambda checked: self.maximize(dock) if checked else self.restore())

    def __sync_button(self, dock: QtAds.CDockWidget) -> None:
        """Reflect whether ``dock`` is the maximized one on its button, without firing its toggle.

        :param dock: the dock whose button to update; a no-op if it has none.
        """
        button = self.__buttons.get(dock)
        if button is None:
            return
        maximized = dock is self.__maximized_dock
        button.blockSignals(True)
        try:
            button.setChecked(maximized)
        finally:
            button.blockSignals(False)
        button.setText((self.__maximized_glyph if maximized else self.__glyph).codepoint)
        button.setToolTip(self.RESTORE_TOOLTIP if maximized else self.MAXIMIZE_TOOLTIP)
