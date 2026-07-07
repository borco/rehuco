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

class TitleBarButton:
    """Selector for `CDockAreaWidget.titleBarButton` (e.g. `TitleBarButtonTabsMenu`)."""

TitleBarButtonTabsMenu: TitleBarButton
"""The dropdown button (shown when `CDockManager.DockAreaHasTabsMenuButton` is set) listing every
tab in an area, for areas with more tabs than fit the available width -- but present regardless of
tab count, including a lone tab (verified empirically)."""

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

    def setFeatures(self, features: DockWidgetFeature) -> None:
        """Replace this dock's entire `DockWidgetFeature` bitmask."""

    def setFeature(self, feature: DockWidgetFeature, on: bool) -> None:
        """Turn a single `DockWidgetFeature` on or off, leaving the others untouched."""

    def setWidget(self, widget: QWidget) -> None:
        """Set the content widget this dock displays."""

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

    def __init__(self, parent: QWidget | None = None) -> None:
        """Construct an empty dock manager with no docks yet."""

    @staticmethod
    def setConfigFlags(flags: eConfigFlag) -> None:
        """Turn on every `eConfigFlag` OR'd into `flags` (all others off) for every `CDockManager`
        in the process. Must be called before the first `CDockManager` is constructed to take
        effect."""

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
