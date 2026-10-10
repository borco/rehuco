"""A QtAds `CDockManager`'s layout as a structural tree: saved by walking it, restored through public
``addDockWidget`` calls one dock at a time, degrading per node ([[appendices.qt-ads#structural-layout]])."""

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, cast

import PySide6QtAds as QtAds
from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtWidgets import QApplication, QSplitter, QSplitterHandle, QWidget

from .qtads_pin_side_handler import PIN_SIDE_NAMES

LAYOUT_FORMAT: Final = 1
"""The tree's own format number, stored under ``"format"``. Anything else restores nothing."""

PIN_SIDES: Final = {name: side for side, name in PIN_SIDE_NAMES.items()}
"""Each stored sidebar word's `SideBarLocation`, the inverse of `PIN_SIDE_NAMES`."""


@dataclass
class LayoutDock:
    """One dock's entry: its name, whether it is closed, and its content's opaque state.

    :param name: the dock's ``objectName()``.
    :param closed: whether the dock is closed.
    :param state: the content's own state, from the caller's ``dock_state`` hook, if any.
    :param dock: the dock itself -- the one saved, or the one a restore resolved the name to.
    """

    name: str
    closed: bool
    state: bytes | None = None
    dock: QtAds.CDockWidget | None = None

    @property
    def widget(self) -> QtAds.CDockWidget:
        """The dock a restore resolved this entry to -- every entry in a resolved tree has one.

        :returns: the dock.
        """
        return cast(QtAds.CDockWidget, self.dock)


@dataclass
class LayoutArea:
    """A tabbed area: its docks in tab order, and which of them is the current tab.

    :param docks: the area's docks, in tab order.
    :param current: the current tab's dock name.
    """

    docks: list[LayoutDock]
    current: str | None = None


@dataclass
class LayoutSplit:
    """A splitter: its orientation, and its children with their sizes.

    :param horizontal: whether the children sit side by side (else stacked).
    :param children: the areas and nested splitters, in order.
    :param sizes: each child's size in pixels; empty when unknown.
    """

    horizontal: bool
    children: list[LayoutArea | LayoutSplit]
    sizes: list[int] = field(default_factory=list)


type LayoutNode = LayoutArea | LayoutSplit
"""One node of a container's tree."""


@dataclass
class ParsedLayout:
    """A stored tree, resolved to the manager's docks and pruned to the ones that resolve.

    :param main: the main container's tree, if any of it resolved.
    :param floating: each floating window's geometry (if valid) and tree.
    :param pinned: each sidebar's side, docks in tab order, and stored panel size.
    :param unplaced: the docks stored with no area.
    """

    main: LayoutNode | None
    floating: list[tuple[QRect | None, LayoutNode]]
    pinned: list[tuple[QtAds.SideBarLocation, list[LayoutDock], object]]
    unplaced: list[LayoutDock]


class QtAdsLayout:
    """Saves and restores one `CDockManager`'s layout as a JSON-able tree instead of QtAds' opaque
    ``saveState()`` blob.

    **Why.** The blob is all-or-nothing: ``restoreState`` leaves a dock the blob does not name in no area
    at all, and ``saveState`` writes only docks that sit in an area, so one bad save loses a dock for
    good (#102). Here every node degrades on its own: a dock the tree names but the manager lacks is
    dropped, a dock the manager has but the tree does not name goes to the caller's default place, and
    the rest of the layout survives either way.

    **Save** starts from the docks, not from the manager's lists of containers: each dock's area names
    its container, so a floating window the manager lost track of is still saved (#488).

    **Restore** moves the manager's existing docks into place -- every manager builds its docks before
    it restores. The tree is pruned to the docks that exist before anything moves, so every area it
    builds has a real dock to seed it: no placeholder docks. Splitter sizes are applied once the whole
    tree exists, since every insertion resets its splitter's sizes.

    **A manager that never pins** (``pins=False``, a nested one) restores a ``pinned`` entry into its main
    container instead: pinning there would grow the manager a sidebar of its own, and such an entry is only
    ever written by a dock QtAds pinned against the manager's will (#491).

    :param dock_manager: the manager whose layout to save or restore.
    :param pins: whether the manager pins docks into its sidebars.
    """

    def __init__(self, dock_manager: QtAds.CDockManager, *, pins: bool = True) -> None:
        self.__dock_manager: Final = dock_manager
        self.__pins: Final = pins

    def save(self, dock_state: Callable[[QtAds.CDockWidget], bytes | None] | None = None) -> dict[str, Any]:
        """Walk the manager's layout into a tree.

        Capture with any maximize undone (`QtAdsMaximizeHandler.unmaximized`): a maximized area's
        neighbours are hidden, and their sizes would be saved as zero.

        :param dock_state: returns a dock's content state to store in its entry, or ``None``.
        :returns: the JSON-able tree, restorable by :meth:`restore`.
        """
        # of two docks sharing a name (#364), the one registered first keeps it: a later one was renamed onto it
        entries: dict[str, QtAds.CDockWidget] = {}
        for dock in self.__dock_manager.dockWidgetsMap().values():
            entries.setdefault(dock.objectName(), dock)
        containers, pinned, unplaced = self.__sort_docks(entries, dock_state)
        layout: dict[str, Any] = {"format": LAYOUT_FORMAT}
        floating: list[dict[str, Any]] = []
        for container in containers:
            # never None: the container holds the dock it was found by
            node = cast(LayoutNode, self.__walk(container.rootSplitter(), entries, dock_state))
            # the manager's own container is told apart by identity: QtAds' floatingWidget() is the nearest
            # floating window *above* the container, so a nested manager inside a floated outer dock reports the
            # outer window as its own
            window = container.floatingWidget()
            if container is self.__dock_manager or window is None:
                layout["main"] = self.__node_to_json(node)
            else:
                geometry = window.geometry()
                floating.append(
                    {
                        "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                        "root": self.__node_to_json(node),
                    }
                )
        if floating:
            layout["floating"] = floating
        if pinned:
            layout["pinned"] = [
                {
                    "side": side,
                    "docks": [self.__dock_to_json(entry) for _, entry, _ in sorted(rows, key=lambda row: row[0])],
                    "size": max(size for _, _, size in rows),
                }
                for side, rows in pinned.items()
            ]
        if unplaced:
            layout["unplaced"] = [self.__dock_to_json(entry) for entry in unplaced]
        return layout

    def __sort_docks(
        self,
        entries: dict[str, QtAds.CDockWidget],
        dock_state: Callable[[QtAds.CDockWidget], bytes | None] | None,
    ) -> tuple[list[QtAds.CDockContainerWidget], dict[str, list[tuple[int, LayoutDock, int]]], list[LayoutDock]]:
        """Sort the manager's docks into the containers they sit in, the sidebars they are pinned to, and the
        ones with no area -- starting from the docks, so a container the manager lost track of is still found
        (#488).

        :param entries: the manager's docks by name.
        :param dock_state: the caller's content-state hook.
        :returns: the containers in the order first met; each side's ``(tab index, entry, panel size)`` rows;
            and the area-less docks' entries.
        """
        containers: list[QtAds.CDockContainerWidget] = []
        pinned: dict[str, list[tuple[int, LayoutDock, int]]] = {}
        unplaced: list[LayoutDock] = []
        for dock in entries.values():
            auto_hide = dock.autoHideDockContainer()
            side = PIN_SIDE_NAMES.get(auto_hide.sideBarLocation()) if auto_hide is not None else None
            area = dock.dockAreaWidget()
            if auto_hide is not None and side is not None:
                size = auto_hide.width() if side in ("left", "right") else auto_hide.height()
                pinned.setdefault(side, []).append((auto_hide.tabIndex(), self.__entry(dock, dock_state), size))
            elif area is None:
                unplaced.append(self.__entry(dock, dock_state))
            elif not any(known is area.dockContainer() for known in containers):
                containers.append(area.dockContainer())
        return containers, pinned, unplaced

    def restore(
        self,
        layout: object,
        *,
        place_unnamed: Callable[[QtAds.CDockWidget], None],
        create_dock: Callable[[str, bytes | None], QtAds.CDockWidget | None] | None = None,
        restore_dock_state: Callable[[QtAds.CDockWidget, bytes], None] | None = None,
    ) -> bool:
        """Rebuild a tree :meth:`save` wrote, moving the manager's docks into place.

        :param layout: the tree. Anything but a dict of this :data:`LAYOUT_FORMAT` restores nothing; a
            malformed node inside one is dropped and the rest restores.
        :param place_unnamed: puts back a dock the tree does not name, or names only as unplaced. The dock
            may still sit wherever it was before the restore.
        :param create_dock: builds, and adds to the manager, a dock for a name the manager lacks, from the
            entry's state -- for a manager whose docks the layout defines (the browsers). ``None``, or a
            ``None`` answer, drops the entry.
        :param restore_dock_state: hands a dock the content state its entry carries, once it is placed.
        :returns: whether ``layout`` was a tree to restore; ``False`` leaves the layout untouched.
        """
        if not isinstance(layout, dict) or layout.get("format") != LAYOUT_FORMAT:
            return False
        resolver = LayoutResolver(self.__dock_manager, create_dock)
        parsed = resolver.layout(layout)
        self.__build(parsed)
        delete_emptied_areas()
        for dock in [*resolver.unnamed(), *(entry.widget for entry in parsed.unplaced)]:
            place_unnamed(dock)
        if restore_dock_state is not None:
            for entry in resolver.resolved:
                if entry.state is not None:
                    restore_dock_state(entry.widget, entry.state)
        self.__dock_manager.stateRestored.emit()
        return True

    def __build(self, parsed: ParsedLayout) -> None:
        """Lay a resolved tree out: the main container, the floating windows and the sidebars, then each dock open
        or closed, each area's current tab, and the splitter sizes once every splitter exists.

        :param parsed: the resolved tree.
        """
        builds: list[LayoutNode] = []
        if parsed.main is not None:
            self.__build_main(parsed.main)
            builds.append(parsed.main)
        for geometry, node in parsed.floating:
            self.__build_floating(node, geometry)
            builds.append(node)
        for side, docks, size in parsed.pinned:
            self.__build_pinned(side, docks, size)

        for node in builds:
            self.__apply_open_and_current(node)
        for _, docks, _ in parsed.pinned:
            for entry in docks:
                if entry.widget.isClosed() != entry.closed:
                    entry.widget.toggleView(not entry.closed)
        for node in builds:
            self.__apply_sizes(node)

    def __walk(
        self,
        widget: QWidget,
        entries: dict[str, QtAds.CDockWidget],
        dock_state: Callable[[QtAds.CDockWidget], bytes | None] | None,
    ) -> LayoutNode | None:
        """Read one live splitter or area into a node, normalized.

        A dock is read only under the name the manager knows it by, so of two docks sharing a name (#364) only
        the registered one is saved.

        :param widget: a `CDockSplitter` or a `CDockAreaWidget` -- all a container's tree holds.
        :param entries: the manager's docks by name.
        :param dock_state: the caller's content-state hook.
        :returns: the node, or ``None`` for an empty splitter or area.
        """
        if isinstance(widget, QtAds.CDockAreaWidget):
            docks = [
                self.__entry(dock, dock_state)
                for dock in widget.dockWidgets()
                if entries.get(dock.objectName()) is dock
            ]
            if not docks:
                return None
            current = widget.currentDockWidget()
            return LayoutArea(docks, current.objectName() if current is not None else None)
        splitter = cast(QSplitter, widget)
        sizes = splitter.sizes()
        children: list[LayoutNode] = []
        kept: list[int] = []
        for index, pane in enumerate(splitter_panes(splitter)):
            child = self.__walk(pane, entries, dock_state)
            if child is not None:
                children.append(child)
                kept.append(sizes[index])
        return normalized(LayoutSplit(splitter.orientation() == Qt.Orientation.Horizontal, children, kept))

    @staticmethod
    def __entry(dock: QtAds.CDockWidget, dock_state: Callable[[QtAds.CDockWidget], bytes | None] | None) -> LayoutDock:
        """A live dock's entry.

        :param dock: the dock.
        :param dock_state: the caller's content-state hook.
        :returns: the entry.
        """
        return LayoutDock(dock.objectName(), dock.isClosed(), dock_state(dock) if dock_state else None)

    def __build_main(self, node: LayoutNode) -> None:
        """Lay ``node`` out in the manager's main container.

        The first dock stays where it is when it already sits in the main container, so the tree grows
        out of that area; otherwise it joins the main container's first area, or starts it.

        :param node: the pruned tree.
        """
        seed = first_dock(node)
        self.__prepare_move(seed)
        area = seed.dockAreaWidget()
        if area is None or area.dockContainer() is not self.__dock_manager:
            target = next(iter(self.__main_areas()), None)
            area = self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, seed, target)
        self.__expand(node, area)

    def __build_floating(self, node: LayoutNode, geometry: QRect | None) -> None:
        """Lay ``node`` out in a new floating window.

        :param node: the pruned tree.
        :param geometry: the window's geometry, if the tree had a valid one.
        """
        seed = first_dock(node)
        self.__prepare_move(seed)
        self.__dock_manager.addDockWidgetFloating(seed)
        self.__expand(node, placed_area(seed))
        if geometry is not None:
            cast(QtAds.CFloatingDockContainer, seed.floatingDockContainer()).setGeometry(geometry)

    def __build_pinned(self, side: QtAds.SideBarLocation, docks: list[LayoutDock], size: object) -> None:
        """Pin ``docks`` to ``side``, in order -- or, for a manager that never pins, dock them in its main
        container.

        A dock outside the main container is docked there first: pinning a floating dock leaves its old
        window behind ([[appendices.qt-ads#auto-hide-abandoned-float]]). A dock already pinned to ``side`` is
        left alone only when the sidebar is this manager's: one QtAds pinned into another manager's sidebar
        (#491) is brought home like any other.

        :param side: the sidebar.
        :param docks: the docks, in tab order.
        :param size: the slid-out panel's extent, if the tree had a valid one.
        """
        for entry in docks:
            dock = entry.widget
            if self.__pins and self.__is_pinned_here(dock, side):
                continue
            self.__prepare_move(dock)
            area = dock.dockAreaWidget()
            if area is None or area.dockContainer() is not self.__dock_manager:
                self.__dock_manager.addDockWidget(
                    QtAds.CenterDockWidgetArea, dock, next(iter(self.__main_areas()), None)
                )
            if not self.__pins:
                continue
            dock.setAutoHide(True, side)
            container = dock.autoHideDockContainer()
            if container is not None and isinstance(size, int) and size > 0:
                container.setSize(size)

    def __expand(self, node: LayoutNode, area: QtAds.CDockAreaWidget) -> None:
        """Grow ``node`` out of ``area``, which already holds the node's first dock.

        A splitter first places one seed area per child -- each child's first dock, beside the previous
        seed -- and only then expands each child from its seed, so every insertion targets a lone area:
        inserting beside an area whose splitter runs the other way wraps the two in a new splitter, and
        beside one whose splitter runs the same way joins it.

        :param node: the node to lay out.
        :param area: the area holding ``first_dock(node)``.
        """
        if isinstance(node, LayoutArea):
            for entry in node.docks[1:]:
                self.__prepare_move(entry.widget)
                self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, entry.widget, area)
            return
        direction = QtAds.RightDockWidgetArea if node.horizontal else QtAds.BottomDockWidgetArea
        seeds = [area]
        for child in node.children[1:]:
            seed = first_dock(child)
            self.__prepare_move(seed)
            seeds.append(self.__dock_manager.addDockWidget(direction, seed, seeds[-1]))
        for child, seed_area in zip(node.children, seeds, strict=True):
            self.__expand(child, seed_area)

    def __is_pinned_here(self, dock: QtAds.CDockWidget, side: QtAds.SideBarLocation) -> bool:
        """Whether ``dock`` is already pinned to ``side`` in this manager's own sidebar.

        :param dock: the dock.
        :param side: the sidebar.
        :returns: ``False`` for a dock pinned to the same side of another manager's sidebar.
        """
        container = dock.autoHideDockContainer()
        return (
            container is not None
            and container.sideBarLocation() == side
            and container.dockContainer() is self.__dock_manager
        )

    def __prepare_move(self, dock: QtAds.CDockWidget) -> None:
        """Ready ``dock`` to be moved: out of its sidebar if it is pinned, and open if it is closed.

        Opened because QtAds moves a closed dock as an open one with its tab still hidden: the dock reports
        itself open, so no later ``toggleView(True)`` shows the tab (measured). The tree's closed docks are
        closed again once everything is placed.

        :param dock: the dock about to be moved.
        """
        if dock.isAutoHide():
            dock.setAutoHide(False)
        if dock.isClosed():
            dock.toggleView(True)

    def __apply_open_and_current(self, node: LayoutNode) -> None:
        """Open or close each dock as the tree says, then bring each area's current tab to the front.

        :param node: a built tree.
        """
        if isinstance(node, LayoutSplit):
            for child in node.children:
                self.__apply_open_and_current(child)
            return
        current: QtAds.CDockWidget | None = None
        for entry in node.docks:
            if entry.widget.isClosed() != entry.closed:
                entry.widget.toggleView(not entry.closed)
            if entry.name == node.current and not entry.closed:
                current = entry.widget
        if current is not None:
            current.setAsCurrentTab()

    def __apply_sizes(self, node: LayoutNode) -> None:
        """Give each built splitter its saved sizes, where the live splitter has the tree's shape.

        A splitter is found as the innermost one holding the first docks of its first two children -- the
        build put every child in it, in order; one that holds other panes too (an area the restore left for a
        dock the tree does not name) keeps QtAds' sizes.

        :param node: a built tree.
        """
        if isinstance(node, LayoutArea):
            return
        for child in node.children:
            self.__apply_sizes(child)
        if len(node.sizes) != len(node.children) or sum(node.sizes) <= 0:
            return
        firsts = [placed_area(first_dock(child)) for child in node.children]
        splitter = common_splitter(firsts[0], firsts[1])
        if splitter is not None and splitter.count() == len(firsts):
            splitter.setSizes(node.sizes)

    def __main_areas(self) -> list[QtAds.CDockAreaWidget]:
        """The main container's areas, open or not.

        :returns: the areas, in no guaranteed order.
        """
        return [
            area
            for area in self.__dock_manager.findChildren(QtAds.CDockAreaWidget)
            if area.dockContainer() is self.__dock_manager and area.objectName() != "autoHideDockArea"
        ]

    def __node_to_json(self, node: LayoutNode) -> dict[str, Any]:
        """A node as stored.

        :param node: the node.
        :returns: its JSON-able form.
        """
        if isinstance(node, LayoutArea):
            return {"area": [self.__dock_to_json(entry) for entry in node.docks], "current": node.current}
        return {
            "split": "h" if node.horizontal else "v",
            "sizes": node.sizes,
            "children": [self.__node_to_json(child) for child in node.children],
        }

    @staticmethod
    def __dock_to_json(entry: LayoutDock) -> dict[str, Any]:
        """A dock entry as stored.

        :param entry: the entry.
        :returns: its JSON-able form, the state base64-encoded.
        """
        dock: dict[str, Any] = {"name": entry.name, "closed": entry.closed}
        if entry.state is not None:
            dock["state"] = base64.b64encode(entry.state).decode("ascii")
        return dock


class LayoutResolver:
    """Reads stored nodes into pruned ones, resolving each dock name to one of the manager's docks.

    A name the manager lacks is offered to ``create_dock``, and dropped if that gives nothing; a name seen
    twice keeps its first entry. Whatever the tree never named is :meth:`unnamed`.

    :param dock_manager: the manager restoring.
    :param create_dock: the caller's dock factory, if any.
    """

    def __init__(
        self,
        dock_manager: QtAds.CDockManager,
        create_dock: Callable[[str, bytes | None], QtAds.CDockWidget | None] | None,
    ) -> None:
        self.__create_dock: Final = create_dock
        self.__docks: Final = {dock.objectName(): dock for dock in dock_manager.dockWidgetsMap().values()}
        self.__seen: Final[set[str]] = set()
        self.resolved: Final[list[LayoutDock]] = []
        """Every entry resolved so far, in tree order."""

    def layout(self, values: dict[str, Any]) -> ParsedLayout:
        """A stored tree, resolved.

        :param values: the stored tree, of :data:`LAYOUT_FORMAT`.
        :returns: its resolved parts.
        """
        return ParsedLayout(
            main=self.node(values.get("main")),
            floating=[
                (self.__geometry(item.get("geometry")), node)
                for item in self.__dicts(values.get("floating"))
                if (node := self.node(item.get("root"))) is not None
            ],
            pinned=[
                (PIN_SIDES[item["side"]], docks, item.get("size"))
                for item in self.__dicts(values.get("pinned"))
                if item.get("side") in PIN_SIDES and (docks := self.docks(item.get("docks")))
            ],
            unplaced=self.docks(values.get("unplaced")),
        )

    def node(self, value: object) -> LayoutNode | None:
        """A stored node, pruned to the docks that resolve, and normalized.

        :param value: the stored node.
        :returns: the node, or ``None`` if nothing in it resolves.
        """
        if not isinstance(value, dict):
            return None
        if "area" in value:
            docks = self.docks(value["area"])
            if not docks:
                return None
            current = value.get("current")
            return LayoutArea(docks, current if isinstance(current, str) else None)
        children_value = value.get("children")
        if value.get("split") not in ("h", "v") or not isinstance(children_value, list):
            return None
        sizes_value = value.get("sizes")
        sizes = (
            [size for size in sizes_value if isinstance(size, int) and size >= 0]
            if isinstance(sizes_value, list)
            else []
        )
        aligned = len(sizes) == len(children_value)
        children: list[LayoutNode] = []
        kept: list[int] = []
        for index, child_value in enumerate(children_value):
            child = self.node(child_value)
            if child is not None:
                children.append(child)
                if aligned:
                    kept.append(sizes[index])
        return normalized(LayoutSplit(value["split"] == "h", children, kept))

    def docks(self, value: object) -> list[LayoutDock]:
        """A stored list of dock entries, keeping those that resolve.

        :param value: the stored list.
        :returns: the resolved entries.
        """
        if not isinstance(value, list):
            return []
        docks: list[LayoutDock] = []
        for item in value:
            entry = self.__dock(item)
            if entry is not None:
                docks.append(entry)
        return docks

    def unnamed(self) -> list[QtAds.CDockWidget]:
        """The manager's docks no resolved entry named.

        :returns: the docks.
        """
        return [dock for name, dock in self.__docks.items() if name not in self.__seen]

    def __dock(self, value: object) -> LayoutDock | None:
        """One stored dock entry, resolved.

        :param value: the stored entry.
        :returns: the entry with its dock, or ``None`` if it is malformed, a repeat, or names no dock.
        """
        if not isinstance(value, dict):
            return None
        name = value.get("name")
        if not isinstance(name, str) or name in self.__seen:
            return None
        state = self.__state(value.get("state"))
        dock = self.__docks.get(name)
        if dock is None and self.__create_dock is not None:
            dock = self.__create_dock(name, state)
            if dock is not None:
                self.__docks[name] = dock  # pylint: disable=unsupported-assignment-operation
        if dock is None:
            return None
        self.__seen.add(name)
        entry = LayoutDock(name, value.get("closed") is True, state, dock)
        self.resolved.append(entry)
        return entry

    @staticmethod
    def __dicts(value: object) -> list[dict[str, Any]]:
        """The dict items of a stored list.

        :param value: a stored value that should be a list of dicts.
        :returns: its dict items; nothing if it is not a list.
        """
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def __geometry(value: object) -> QRect | None:
        """A stored ``[x, y, width, height]`` as a rectangle.

        :param value: the stored value.
        :returns: the rectangle, or ``None`` if the value is not four integers with a positive size.
        """
        if not isinstance(value, list) or len(value) != 4 or not all(isinstance(v, int) for v in value):
            return None
        rect = QRect(*value)
        return rect if rect.width() > 0 and rect.height() > 0 else None

    @staticmethod
    def __state(value: object) -> bytes | None:
        """A stored base64 state, decoded.

        :param value: the stored value.
        :returns: the bytes, or ``None`` if there is none or it is not valid base64.
        """
        if not isinstance(value, str):
            return None
        try:
            return base64.b64decode(value, validate=True)
        except binascii.Error:
            return None


def normalized(split: LayoutSplit) -> LayoutNode | None:
    """``split`` in its one canonical shape: no empty or single-child splitter, and no child splitter
    running the same way as its parent -- QtAds builds both, and a restore could not rebuild them.

    :param split: a splitter whose children are already normalized.
    :returns: the normalized node, or ``None`` if it has no children.
    """
    if not split.children:
        return None
    if len(split.children) == 1:
        return split.children[0]
    sized = len(split.sizes) == len(split.children)
    children: list[LayoutNode] = []
    sizes: list[int] = []
    for index, child in enumerate(split.children):
        if isinstance(child, LayoutSplit) and child.horizontal == split.horizontal:
            children.extend(child.children)
            if sized:
                sizes.extend(spread(split.sizes[index], child.sizes, len(child.children)))
        else:
            children.append(child)
            if sized:
                sizes.append(split.sizes[index])
    return LayoutSplit(split.horizontal, children, sizes)


def spread(total: int, sizes: list[int], count: int) -> list[int]:
    """Share ``total`` among ``count`` children in proportion to ``sizes``, or evenly without them.

    :param total: the parent's size for the spliced splitter.
    :param sizes: the spliced splitter's own sizes; may be empty.
    :param count: how many children it had.
    :returns: one size per child.
    """
    weight = sum(sizes)
    if len(sizes) != count or weight <= 0:
        return [total // count] * count
    return [total * size // weight for size in sizes]


def first_dock(node: LayoutNode) -> QtAds.CDockWidget:
    """The dock of a node's first leaf's first entry -- the dock a node is grown from.

    :param node: a resolved node.
    :returns: the dock.
    """
    while isinstance(node, LayoutSplit):
        node = node.children[0]
    first, *_ = node.docks
    return first.widget


def delete_emptied_areas() -> None:
    """Delete, now, every dock area QtAds has emptied and let go of.

    QtAds takes an area whose last dock moved out off its parent and only *schedules* its deletion. Left to the
    event loop, a window torn down before the loop next runs -- a document closed in the handler that laid it out,
    a test's teardown -- leaves the parentless area to be deleted after its manager, and the process dies of an
    access violation (#102, measured in the suite). A live area always has a parent (a splitter, or a pinned dock's
    panel), so a parentless one is exactly such an area -- found among the application's widgets, since one the
    build made and emptied again was never the manager's child to list. Only these areas are delivered their
    pending deletion: a blanket flush would also free a dock someone else just scheduled, ahead of the events its
    removal posted ([[appendices.qt-ads#dock-registry-keys]]).
    """
    for widget in QApplication.allWidgets():
        if isinstance(widget, QtAds.CDockAreaWidget) and widget.parentWidget() is None:
            QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)


def placed_area(dock: QtAds.CDockWidget) -> QtAds.CDockAreaWidget:
    """The area a dock the restore has just placed sits in.

    :param dock: a placed dock.
    :returns: its area.
    """
    return cast(QtAds.CDockAreaWidget, dock.dockAreaWidget())


def common_splitter(first: QWidget, second: QWidget) -> QSplitter | None:
    """The innermost splitter holding both widgets.

    :param first: one widget.
    :param second: another widget.
    :returns: the splitter, or ``None`` if they share none.
    """
    ancestors: list[QWidget] = []
    widget = first.parentWidget()
    while widget is not None:
        ancestors.append(widget)
        widget = widget.parentWidget()
    widget = second.parentWidget()
    while widget is not None:
        if isinstance(widget, QSplitter) and any(widget is ancestor for ancestor in ancestors):
            return widget
        widget = widget.parentWidget()
    return None


def splitter_panes(splitter: QSplitter) -> list[QWidget]:
    """A splitter's panes in order, read without ``QSplitter.widget(i)``.

    PySide registers what ``widget(i)`` returns as a child of the splitter's Python wrapper, and freeing
    that wrapper -- a temporary one, from ``parentSplitter()`` or ``parentWidget()`` -- invalidates the
    wrapper of every Qt-made object below each pane while the objects live on: a document toolbar's
    actions, a floating window's container ("already deleted", #102; measured). ``children()`` and
    ``indexOf()`` register nothing; ``indexOf()`` answers for a handle too, so handles are left out.

    :param splitter: the splitter.
    :returns: its panes, in splitter order.
    """
    panes = [
        child
        for child in splitter.children()
        if isinstance(child, QWidget) and not isinstance(child, QSplitterHandle) and splitter.indexOf(child) >= 0
    ]
    return sorted(panes, key=splitter.indexOf)
