"""Local stubs for `pyside6-qtads` (upstream ships none, so pyright otherwise sees a raw
`Shiboken.ObjectType` and rejects every use of a QtAds class as a type annotation).

Covers only the surface `rehuco-agent`'s dock shell uses as of issue #20 (commit 5); extend as
later slices adopt more of the API (e.g. the QML docks from
[[packaging-deployment#qml-regression]]).
"""

from typing import overload

from PySide6.QtCore import QByteArray, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMenu, QToolButton, QWidget

class DockWidgetArea:
    """A drop-location selector for `CDockManager.addDockWidget`/`setCentralWidget` (e.g.
    `CenterDockWidgetArea`, `RightDockWidgetArea`)."""

    def __or__(self, other: DockWidgetArea) -> DockWidgetArea:
        """Combine two areas into one selector, mirroring the C++ enum's `|` (Qt flag) operator."""

CenterDockWidgetArea: DockWidgetArea
"""Docks as a new tab in the target area's existing tab group (or as the sole tab, if none)."""

RightDockWidgetArea: DockWidgetArea
"""Docks in a new area split off to the right of the reference area."""

LeftDockWidgetArea: DockWidgetArea
"""Docks in a new area split off to the left of the reference area."""

BottomDockWidgetArea: DockWidgetArea
"""Docks in a new area split off below the reference area -- where the app-wide log dock goes (#200),
read across the width of the window under the thing it is about."""

class TitleBarButton:
    """Selector for `CDockAreaWidget.titleBarButton` (e.g. `TitleBarButtonTabsMenu`)."""

TitleBarButtonTabsMenu: TitleBarButton
"""The dropdown button (shown when `CDockManager.DockAreaHasTabsMenuButton` is set) listing every
tab in an area, for areas with more tabs than fit the available width -- but present regardless of
tab count, including a lone tab (verified empirically)."""

TitleBarButtonAutoHide: TitleBarButton
"""The pin button (shown when `CDockManager.DockAreaHasAutoHideButton` is set) collapsing the area's
current dock into one of the window's sidebars. Shown regardless of whether that dock carries
`DockWidgetPinnable` -- that feature gates the drag and the context-menu route instead -- which is why
suppressing the button for one manager takes `~borco_pyside.qtads.QtAdsAutoHideButtonSuppressor`
rather than a feature flag (#279)."""

class SideBarLocation:
    """Which of a `CDockManager`'s four borders a pinned (auto-hidden) dock collapses into."""

SideBarNone: SideBarLocation
"""No sidebar -- what `CDockWidget.autoHideLocation` reports for a dock that is not pinned."""

SideBarLeft: SideBarLocation
"""The window's left border -- this app's default pin side (#279)."""

SideBarRight: SideBarLocation
"""The window's right border."""

SideBarTop: SideBarLocation
"""The window's top border."""

SideBarBottom: SideBarLocation
"""The window's bottom border."""

class CAutoHideTab(QWidget):
    """The sidebar tab standing in for a pinned dock, showing the dock's icon and/or its title
    rotated along the border."""

class CAutoHideDockContainer(QWidget):
    """The panel a pinned dock slides out into over the layout. Hidden while collapsed to its sidebar
    tab -- so ``isVisible()`` is the collapsed/expanded reading -- and ``toggleView(True)`` on the dock
    expands it (verified, #279), which is what lets an open reach a collapsed Documents dock."""

    def collapseView(self, enable: bool) -> None:
        """Collapse this container back to its sidebar tab (`enable`), or slide it out."""

    def dockWidget(self) -> CDockWidget:
        """The pinned dock this container holds."""

    def sideBarLocation(self) -> SideBarLocation:
        """Which sidebar this container's tab sits in -- the side the dock was actually pinned to,
        which is *not* written back to its `preferredAutoHideSideBarLocation`
        ([[appendices.qt-ads#auto-hide-preferred-side]])."""

class CAutoHideSideBar(QWidget):
    """One of a `CDockManager`'s four sidebars, holding the `CAutoHideTab`s of the docks pinned to
    that border."""

    def count(self) -> int:
        """How many pinned docks this sidebar holds."""

    def tab(self, index: int) -> CAutoHideTab:
        """The tab at `index`, in sidebar order."""

class CTitleBarButton(QToolButton):
    """One button in a `CDockAreaWidget`'s title bar (e.g. the tabs-menu dropdown)."""

    def menu(self) -> QMenu:
        """This button's dropdown menu (only meaningful for `TitleBarButtonTabsMenu`)."""

class CDockAreaTitleBar(QWidget):
    """The title-bar strip above a `CDockAreaWidget`'s tabs (`objectName() == "dockAreaTitleBar"`)."""

class CDockAreaWidget(QWidget):
    """One tabbed area within a `CDockManager`, holding one or more `CDockWidget` tabs."""

    def setCurrentIndex(self, index: int) -> None:
        """Bring the tab at `index` to the front, hiding whichever tab was previously current."""

    def index(self, dock_widget: CDockWidget) -> int:
        """The tab index `dock_widget` occupies in this area, for use with `setCurrentIndex`."""

    def dockWidget(self, index: int) -> CDockWidget | None:
        """The dock widget occupying the tab at `index`, or `None` if `index` is out of range."""

    def currentIndex(self) -> int:
        """The index of this area's currently-selected (front) tab."""

    def titleBar(self) -> CDockAreaTitleBar:
        """This area's title bar (the strip above its tabs), e.g. to re-polish it after a
        stylesheet-affecting property change."""

    def titleBarButton(self, which: TitleBarButton) -> CTitleBarButton:
        """This area's title-bar button matching `which` (e.g. its tabs-menu dropdown)."""

    currentChanged: Signal
    """Emitted with the new tab index whenever this area's current (selected) tab changes -- e.g.
    the user clicks a different tab."""

class CElidingLabel(QLabel):
    """A `QLabel` that elides overflowing text instead of overflowing its bounds. Also the default
    content of a `CDockWidgetTab`'s clickable label (`objectName() == "dockWidgetTabLabel"`,
    findable via `CDockWidgetTab.findChild`)."""

    clicked: Signal
    """Emitted when the label is clicked (a single click, unlike `doubleClicked`)."""

    doubleClicked: Signal
    """Emitted when the label is double-clicked."""

class CDockWidgetTab(QWidget):
    """The clickable tab representing a `CDockWidget` within its `CDockAreaWidget`'s tab bar.
    `toolTip()` (inherited from `QWidget`) reflects `CDockWidget.setTabToolTip`."""

class CFloatingDockContainer(QWidget):
    """The top-level window hosting one or more docks torn out of a `CDockManager` (drag-out, or
    `CDockManager.addDockWidgetFloating`). A plain `QWidget` for typing purposes -- callers only
    ever need `isVisible()`/`show()`/etc., inherited from it."""

class CDockWidget(QWidget):
    """One dockable pane: a titled, taggable container around a single content `QWidget`
    (`setWidget`), placed into a `CDockManager` via `addDockWidget`/`setCentralWidget`."""

    class DockWidgetFeature:
        """Bitmask of optional `CDockWidget` behaviors, passed to `setFeatures`/`setFeature`."""

        DockWidgetClosable: CDockWidget.DockWidgetFeature
        """Shows a close (x) button on the dock's tab/title bar."""

        DockWidgetMovable: CDockWidget.DockWidgetFeature
        """Lets the user drag this dock to another area or float it."""

        DockWidgetFloatable: CDockWidget.DockWidgetFeature
        """Lets this dock be torn out into its own floating top-level window."""

        DockWidgetFocusable: CDockWidget.DockWidgetFeature
        """Lets this dock (and its content) receive keyboard focus and appear in
        `focusedDockWidgetChanged`."""

        DockWidgetForceCloseWithArea: CDockWidget.DockWidgetFeature
        """Closes this dock along with its containing area, instead of the area surviving with
        one fewer tab."""

        DockWidgetDeleteOnClose: CDockWidget.DockWidgetFeature
        """Deletes the dock widget (via `deleteLater`) when it closes, instead of just hiding it."""

        CustomCloseHandling: CDockWidget.DockWidgetFeature
        """Routes the close (x) button through `closeRequested` instead of ADS's own
        hide-or-delete default, so the application decides what "close" means."""

        NoTab: CDockWidget.DockWidgetFeature
        """Hides this dock's own tab, e.g. for a lone central-widget dock with nothing to tab
        against."""

        DockWidgetPinnable: CDockWidget.DockWidgetFeature
        """Lets this dock be pinned (auto-hidden) into one of the window's sidebars -- by a drag, or by
        the area title bar's "Pin Group" context-menu action, both of which upstream gates on it. It
        gates **neither the area's pin button nor `setAutoHide`**: both work on a dock without it
        (verified, #279), which is why keeping the button off one manager takes
        `~borco_pyside.qtads.QtAdsAutoHideButtonSuppressor`, while keeping the drag and the menu off
        takes nothing more than not setting this ([[appendices.qt-ads#pinnable-is-not-a-lever]])."""

        def __or__(self, other: CDockWidget.DockWidgetFeature) -> CDockWidget.DockWidgetFeature:
            """Combine two features into one selector, mirroring the C++ enum's `|` operator."""

    # the flag enum's members are also promoted onto CDockWidget itself (verified at runtime):
    # both `QtAds.CDockWidget.DockWidgetFeature.NoTab` and `QtAds.CDockWidget.NoTab` resolve.
    DockWidgetClosable: DockWidgetFeature
    DockWidgetMovable: DockWidgetFeature
    DockWidgetFloatable: DockWidgetFeature
    DockWidgetFocusable: DockWidgetFeature
    DockWidgetForceCloseWithArea: DockWidgetFeature
    DockWidgetDeleteOnClose: DockWidgetFeature
    CustomCloseHandling: DockWidgetFeature
    NoTab: DockWidgetFeature
    DockWidgetPinnable: DockWidgetFeature

    @overload
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Construct a standalone dock widget, to be added to a manager later via
        `CDockManager.addDockWidget`/`setCentralWidget`."""
    @overload
    def __init__(self, manager: CDockManager, title: str, parent: QWidget | None = None) -> None:
        """Construct a dock widget already associated with `manager` (still needs
        `addDockWidget`/`setCentralWidget` to actually place it)."""

    closeRequested: Signal
    """Emitted when the user clicks the close (x) button on a dock with `CustomCloseHandling`
    and/or `DockWidgetDeleteOnClose` set. With `CustomCloseHandling`, ADS then stops and leaves
    the actual close (hide/remove/delete) entirely to the application -- `DocumentsDock`'s docks
    use this. A dock with neither feature (just `DockWidgetClosable`, e.g. `DocumentWidget`'s
    viewer/editor docks) never emits this -- its close button routes through `toggleView` /
    `viewToggled` instead."""

    viewToggled: Signal
    """Emitted with the new visibility whenever this dock's open/closed state actually changes --
    via the checkable `toggleViewAction()`, or via the close (x) button on a dock that has
    neither `CustomCloseHandling` nor `DockWidgetDeleteOnClose` set (closing there falls through
    to the same `toggleView` path). Not emitted by switching tabs within a shared area (that
    doesn't change open/closed state), nor by a `CustomCloseHandling` close-button click (that
    emits `closeRequested` instead, and does not toggle the view itself)."""

    visibilityChanged: Signal
    """Emitted with the new visibility when this dock's content actually appears on or leaves the
    screen -- unlike `viewToggled` (logical open/closed) this tracks *real* widget visibility, tab
    selection included. Confirmed empirically (offscreen): while the top-level window is still
    hidden, adding docks and switching their tabs emits **nothing**; showing the window emits
    ``True`` once for each area's current tab only; switching tabs in a shown window emits
    ``False`` for the covered dock and ``True`` for the revealed one. That silence-while-hidden
    plus fires-on-first-show is what `DocumentsDock` keys its deferred session-restore document
    loads on (#66)."""

    def setFeatures(self, features: DockWidgetFeature) -> None:
        """Replace this dock's entire `DockWidgetFeature` bitmask."""

    def setFeature(self, feature: DockWidgetFeature, on: bool) -> None:
        """Turn a single `DockWidgetFeature` on or off, leaving the others untouched."""

    class eInsertMode:
        """How `setWidget` inserts the content widget -- directly, or wrapped in a `QScrollArea`."""

        AutoScrollArea: CDockWidget.eInsertMode
        """Wraps the widget in a `QScrollArea` unless it is already a `QAbstractScrollArea` (e.g. a
        bare `QTableView`), which is inserted directly. The default."""

        ForceScrollArea: CDockWidget.eInsertMode
        """Documented upstream as always wrapping in a `QScrollArea`, even a `QAbstractScrollArea`
        content widget -- not reproduced against this binding (a `QTableView` still came in unwrapped,
        same as `AutoScrollArea`); verify before relying on the distinction."""

        ForceNoScrollArea: CDockWidget.eInsertMode
        """Never wraps the widget -- inserted directly, so a composite that already manages its own
        scrolling end-to-end (e.g. a table with a pinned header and a pinned summary label below it)
        doesn't get an outer scrollbar that drags the whole thing, header and summary included."""

    # the enum's members are also promoted onto CDockWidget itself, mirroring DockWidgetFeature above
    # (verified at runtime): both `QtAds.CDockWidget.eInsertMode.ForceNoScrollArea` and
    # `QtAds.CDockWidget.ForceNoScrollArea` resolve.
    AutoScrollArea: eInsertMode
    ForceScrollArea: eInsertMode
    ForceNoScrollArea: eInsertMode

    def setWidget(self, widget: QWidget, insert_mode: eInsertMode = ...) -> None:
        """Set the content widget this dock displays, per `insert_mode` (default `AutoScrollArea`)."""

    def dockManager(self) -> CDockManager:
        """The manager this dock is associated with -- the two-argument constructor's, or the one that
        adopted it. `None` only for a dock built standalone and never added, which is why callers that
        require a manager read it unguarded."""

    def setAutoHide(self, enable: bool, location: SideBarLocation = ...) -> None:
        """Pin this dock into a sidebar (`enable`), or dock it back into the layout.

        Without `location`, pins to `preferredAutoHideSideBarLocation`. A pinned dock is **not**
        closed -- `isClosed()` stays false and `toggleViewAction()` stays checked, so a View menu
        reading either one reads a pinned dock as open (verified, #279)."""

    def autoHideDockContainer(self) -> CAutoHideDockContainer | None:
        """The slide-out container holding this dock while it is pinned, or `None` while it is not."""

    def isAutoHide(self) -> bool:
        """Whether this dock is currently pinned into a sidebar rather than docked in the layout."""

    def autoHideLocation(self) -> SideBarLocation:
        """Which sidebar this dock is pinned into, or `SideBarNone` while it is not pinned."""

    def setPreferredAutoHideSideBarLocation(self, location: SideBarLocation) -> None:
        """Which sidebar this dock's *next* pin lands in -- consulted by the area's pin button in
        place of the dock's geometry. Re-setting it leaves an already-pinned dock where it is."""

    def preferredAutoHideSideBarLocation(self) -> SideBarLocation:
        """The sidebar this dock's next pin will land in."""

    def takeWidget(self) -> QWidget:
        """Remove and return this dock's content widget **without deleting it**, so a caller replacing
        the content (e.g. re-resolving a document's form on a type switch) owns the old widget's disposal."""

    def setTabToolTip(self, tool_tip: str) -> None:
        """Set the tooltip shown when hovering this dock's tab (independent of `setWindowTitle`,
        which sets the tab's visible label)."""

    def tabWidget(self) -> CDockWidgetTab:
        """This dock's tab widget, e.g. to read back `toolTip()` after `setTabToolTip`."""

    def widget(self) -> QWidget:
        """The content widget previously set with `setWidget`."""

    def toggleViewAction(self) -> QAction:
        """A checkable `QAction` that shows/hides this dock -- checking/unchecking it (e.g. from
        a toolbar button or menu item) is what fires `viewToggled`."""

    def dockAreaWidget(self) -> CDockAreaWidget | None:
        """The tabbed area currently containing this dock, or `None` if it isn't placed in one
        (e.g. before it's been added to a manager)."""

    def isClosed(self) -> bool:
        """Whether this dock is currently closed/hidden (its `toggleViewAction` unchecked)."""

    def isFloating(self) -> bool:
        """Whether this dock currently lives in its own floating container, rather than docked
        into a `CDockAreaWidget` split within its manager's normal layout."""

    def floatingDockContainer(self) -> CFloatingDockContainer | None:
        """This dock's floating container, or `None` if it isn't currently floating
        (`isFloating()` is `False`)."""

    def toggleView(self, open: bool = ...) -> None:
        """Show (`open=True`) or hide (`open=False`) this dock, as its `toggleViewAction` does --
        firing `viewToggled` with the new visibility."""

    def requestCloseDockWidget(self) -> None:
        """Ask ADS to close this dock as if its close button were clicked, honoring
        `CustomCloseHandling`/`DockWidgetDeleteOnClose` the same way a real click would."""

    def setAsCurrentTab(self) -> None:
        """Bring this dock's tab to the front of its area (the visible one), without giving it Qt
        keyboard focus. A no-op if it's already the area's current tab, or has no area yet. Fires
        `CDockAreaWidget.currentChanged` when the current tab actually changes."""

class CDockManager(QWidget):
    """The top-level docking surface: owns every `CDockAreaWidget`/`CDockWidget` placed into it
    via `addDockWidget`/`setCentralWidget`. Nestable -- a `CDockWidget`'s content can itself embed
    another `CDockManager` (`rehuco_agent`'s dock-in-dock shell, [[nodes#single-instance]])."""

    class eConfigFlag:
        """One global docking-behavior toggle, OR'd together and passed to `setConfigFlags`. Only
        the flags `rehuco-agent` actually needs are declared here (see this stub's module
        docstring)."""

        AllTabsHaveCloseButton: CDockManager.eConfigFlag
        """Shows the `[x]` close button on every tab in a dock area, not only the active one."""

        DockAreaHasTabsMenuButton: CDockManager.eConfigFlag
        """Adds a drop-down button to each dock area listing all its tabs, for areas with more
        tabs than fit the available width."""

        MiddleMouseButtonClosesTab: CDockManager.eConfigFlag
        """Middle-clicking a tab closes it, the same as clicking its `[x]` button."""

        def __or__(self, other: CDockManager.eConfigFlag) -> CDockManager.eConfigFlag:
            """Combine two flags into one selector, mirroring the C++ enum's `|` (Qt flag)
            operator."""

    # promoted onto CDockManager itself too, like CDockWidget.DockWidgetFeature's members:
    AllTabsHaveCloseButton: eConfigFlag
    DockAreaHasTabsMenuButton: eConfigFlag
    MiddleMouseButtonClosesTab: eConfigFlag

    class eAutoHideFlag:
        """One global auto-hide (pinning) toggle, OR'd together and passed to
        `setAutoHideConfigFlags`. Only the flags `rehuco-agent` actually needs are declared here (see
        this stub's module docstring)."""

        DefaultAutoHideConfig: CDockManager.eAutoHideFlag
        """QtAds' own recommended set, and the base this app builds on: pinning enabled, a pin button
        on each dock area, a minimize button on a slid-out dock, and collapse on a click outside it
        (verified against the installed binding -- see [[appendices.qt-ads#auto-hide-flags]])."""

        AutoHideShowOnMouseOver: CDockManager.eAutoHideFlag
        """Slides a pinned dock out on hovering its sidebar tab, not only on clicking it."""

        AutoHideSideBarsIconOnly: CDockManager.eAutoHideFlag
        """Shows only each sidebar tab's icon, dropping its title -- which needs every pinnable dock
        to carry a `setIcon`, or the tab says nothing at all
        ([[appendices.qt-ads#auto-hide-icon-only]]). Not set by this app."""

        def __or__(self, other: CDockManager.eAutoHideFlag) -> CDockManager.eAutoHideFlag:
            """Combine two flags into one selector, mirroring the C++ enum's `|` (Qt flag)
            operator."""

    # promoted onto CDockManager itself too, like eConfigFlag's members:
    DefaultAutoHideConfig: eAutoHideFlag
    AutoHideShowOnMouseOver: eAutoHideFlag
    AutoHideSideBarsIconOnly: eAutoHideFlag

    class ColorSchemeMode:
        """Which of QtAds' four bundled stylesheets a manager applies to itself (ADS 5.0)."""

        Light: CDockManager.ColorSchemeMode
        """Always the light sheet."""

        Dark: CDockManager.ColorSchemeMode
        """Always the dark sheet."""

        FollowPalette: CDockManager.ColorSchemeMode
        """The default: pick by the application palette's dark-ness, **and re-pick at runtime** --
        which re-runs QtAds' own `loadStylesheet()` on an `ApplicationPaletteChange`, *replacing*
        the manager's whole stylesheet ([[appendices.qt-ads#stylesheet-reload]])."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Construct an empty dock manager with no docks yet."""

    def setColorSchemeMode(self, mode: CDockManager.ColorSchemeMode) -> None:
        """Pick which bundled stylesheet this manager applies, and reload it right now.

        Reloading *replaces* the manager's stylesheet, dropping anything appended to it -- so any
        appended rules have to go back on afterwards. Pinning `Light`/`Dark` (rather than leaving
        `FollowPalette`) also stops the runtime reload on palette changes, which is what makes that
        re-append survivable: the timing becomes the caller's
        ([[appendices.qt-ads#stylesheet-reload]])."""

    @staticmethod
    def isApplicationPaletteDark() -> bool:
        """Whether QtAds reads the current application palette as a dark one -- the same test its
        own `FollowPalette` mode uses to choose between the light and dark sheets."""

    @staticmethod
    def setConfigFlags(flags: eConfigFlag) -> None:
        """Turn on every `eConfigFlag` OR'd into `flags` (all others off) for every `CDockManager`
        in the process. Must be called before the first `CDockManager` is constructed to take
        effect."""

    @staticmethod
    def setAutoHideConfigFlags(flags: eAutoHideFlag) -> None:
        """Turn on every `eAutoHideFlag` OR'd into `flags` (all others off) for every `CDockManager`
        in the process. Like `setConfigFlags`, must be called before the first `CDockManager` is
        constructed to take effect -- and, being process-wide, reaches nested managers too
        ([[appendices.qt-ads#auto-hide-flags]])."""

    @staticmethod
    def autoHideConfigFlags() -> eAutoHideFlag:
        """The process-wide auto-hide flags currently in force -- for a test that turns pinning on
        for its own duration and has to put back whatever it found."""

    def openedDockAreas(self) -> list[CDockAreaWidget]:
        """Every currently-open (visible) dock area of this manager, in no guaranteed order."""

    def addAutoHideDockWidget(self, location: SideBarLocation, dock_widget: CDockWidget) -> CAutoHideTab:
        """Pin `dock_widget` into the sidebar at `location`, whatever its
        `preferredAutoHideSideBarLocation` says -- the entry point a drag dropped on one of the
        window's borders goes through, and the reason a named side beats the preference (#279).

        :returns: the sidebar tab now standing in for it.
        """

    def autoHideSideBar(self, location: SideBarLocation) -> CAutoHideSideBar:
        """This manager's sidebar at `location` -- the strip of tabs standing in for the docks pinned
        to that border."""

    autoHideWidgetCreated: Signal
    """Emitted with the `CAutoHideDockContainer` QtAds has just built for a dock being pinned. Fires on
    every route into a sidebar -- a drop on a border, the area's pin button, `CDockWidget.setAutoHide`,
    a drag of an already-pinned dock between sidebars, and a `restoreState` bringing a pinned dock back
    (all verified) -- which is what makes it the one hook a remembered pin side needs."""

    dockAreaViewToggled: Signal
    """Emitted ``(area, open)`` whenever one of this manager's areas is shown or hidden -- including a
    dock revealed by ``CDockWidget.toggleView``, which moves a container's visible-area count and so
    re-shows its title-bar buttons ([[appendices.qt-ads#tabs-menu-per-manager]])."""

    dockAreaCreated: Signal
    """Emitted with a `CDockAreaWidget` just after this manager creates it. Per-instance: an outer
    manager's connection never fires for a nested manager's areas, which is what makes per-manager
    title-bar-button suppression possible at all ([[appendices.qt-ads#tabs-menu-per-manager]])."""

    def addDockWidget(
        self,
        area: DockWidgetArea,
        dock_widget: CDockWidget,
        dock_area_widget: CDockAreaWidget | None = None,
    ) -> CDockAreaWidget:
        """Place `dock_widget` at `area` relative to `dock_area_widget` (or relative to the whole
        manager, if omitted), creating a new tabbed area or joining an existing one as `area`
        dictates.

        :returns: the tabbed area `dock_widget` ended up in.
        """

    def setCentralWidget(self, dock_widget: CDockWidget) -> CDockAreaWidget:
        """Place `dock_widget` as this manager's permanent central area, which stays visible even
        when every other area is empty.

        :returns: the tabbed area `dock_widget` ended up in.
        """

    def addDockWidgetFloating(self, dock_widget: CDockWidget) -> CFloatingDockContainer:
        """Place `dock_widget` in its own new floating top-level window, not docked into any area.

        Confirmed empirically to follow ordinary Qt parent/child show semantics -- the floating
        container stays hidden until its own top-level ancestor is shown, unlike `restoreState`
        recreating a previously-floating dock (which shows its container immediately regardless).

        :returns: the new floating container.
        """

    def splitterSizes(self, dock_area_widget: CDockAreaWidget) -> list[int]:
        """The pixel sizes of `dock_area_widget`'s containing splitter's panes, in splitter order."""

    def setSplitterSizes(self, dock_area_widget: CDockAreaWidget, sizes: list[int]) -> None:
        """Re-apply previously-read `splitterSizes` to `dock_area_widget`'s containing splitter
        (`len(sizes)` must match the splitter's current pane count)."""

    def saveState(self) -> QByteArray:
        """Serialize this manager's current layout (areas, splitters, visibility) for later
        `restoreState`. Used for per-document dock-layout persistence (#21)."""

    def restoreState(self, state: QByteArray) -> bool:
        """Re-apply a layout previously captured by `saveState`.

        :returns: whether `state` was recognized and applied."""

    dockWidgetAdded: Signal
    """Emitted with a dock widget just after it's been added to this manager (e.g. via
    `addDockWidget`), already placed into its `CDockAreaWidget`."""

    dockWidgetRemoved: Signal
    """Emitted with a dock widget just after it's been removed from this manager via
    `removeDockWidget`."""

    stateRestored: Signal
    """Emitted after `restoreState` finishes applying a previously-saved layout."""

    def removeDockWidget(self, dock_widget: CDockWidget) -> None:
        """Remove `dock_widget` from this manager's layout (its containing area is removed too, if
        it was the area's last dock). Does not delete `dock_widget` itself -- callers that own it
        (e.g. via `DockWidgetDeleteOnClose`) are responsible for that separately."""

    def findDockWidget(self, object_name: str) -> CDockWidget | None:
        """Return the registered dock whose `objectName()` is `object_name`, or `None` if none matches."""

    def dockWidgetsMap(self) -> dict[str, CDockWidget]:
        """Every registered dock, keyed by `objectName()` -- the authoritative registry. Unlike
        `QObject.findChildren`, it includes a dock currently hidden behind another tab in its area
        (whose content QtAds detaches from the widget tree), so persistence must enumerate docks
        through this, not `findChildren`."""

    def isRestoringState(self) -> bool:
        """Whether a `restoreState` is currently in progress -- true only during that call, e.g. while
        the `viewToggled`/`currentChanged` signals it fires for reconstructed docks are dispatching."""
