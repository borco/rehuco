"""Tests for QtAdsLayout: a dock manager's layout saved as a structural tree and rebuilt one dock at a time."""

import base64
from collections.abc import Iterator
from typing import Any, Final

import PySide6QtAds as QtAds
import shiboken6
from borco_pyside.qtads import QtAdsLayout
from borco_pyside.qtads.qtads_layout import (
    LayoutArea,
    LayoutDock,
    LayoutSplit,
    common_splitter,
    normalized,
    placed_area,
    splitter_panes,
)
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QToolBar, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

CENTER: Final = QtAds.CenterDockWidgetArea
RIGHT: Final = QtAds.RightDockWidgetArea
BOTTOM: Final = QtAds.BottomDockWidgetArea


# region fixtures and helpers
@fixture(autouse=True)
def auto_hide_flags() -> Iterator[None]:
    """Turn QtAds' pinning on for one test, and put the process-wide flags back afterwards -- the reason
    ``test_qtads_auto_hide_button_suppressor.py`` gives."""
    previous = QtAds.CDockManager.autoHideConfigFlags()
    QtAds.CDockManager.setAutoHideConfigFlags(QtAds.CDockManager.eAutoHideFlag.DefaultAutoHideConfig)
    yield
    QtAds.CDockManager.setAutoHideConfigFlags(previous)


@fixture
def window(qtbot: QtBot) -> Iterator[QMainWindow]:
    """A shown window for a manager to lay out on.

    Shown because a splitter that has never been laid out has no sizes to read or set. A generator fixture so
    the window, which owns its manager, stays alive for the whole test.
    """
    main_window = QMainWindow()
    main_window.resize(1000, 800)
    qtbot.addWidget(main_window)
    main_window.show()
    qtbot.waitExposed(main_window)
    yield main_window


def make_manager(window: QMainWindow, names: str) -> tuple[QtAds.CDockManager, dict[str, QtAds.CDockWidget]]:
    """A manager on ``window`` with one dock per letter of ``names``, built the way every manager in the app
    builds its docks before a restore: all tabbed into one area.

    :param window: the window to build the manager on.
    :param names: one letter per dock, each its object name.
    :returns: the manager and its docks by name.
    """
    manager = QtAds.CDockManager(window)
    docks: dict[str, QtAds.CDockWidget] = {}
    area = None
    for name in names:
        dock = QtAds.CDockWidget(manager, name)
        dock.setObjectName(name)
        dock.setWidget(QLabel(name))
        area = manager.addDockWidget(CENTER, dock, area)
        docks[name] = dock
    return manager, docks


def area(*names: str, closed: str = "", current: str | None = None) -> dict[str, Any]:
    """A stored area node.

    :param names: its docks, in tab order.
    :param closed: the names of the closed ones.
    :param current: its current tab; the first dock when omitted.
    :returns: the node.
    """
    return {
        "area": [{"name": name, "closed": name in closed} for name in names],
        "current": current if current is not None else names[0],
    }


def split(orientation: str, *children: dict[str, Any], sizes: list[int] | None = None) -> dict[str, Any]:
    """A stored splitter node.

    :param orientation: ``"h"`` or ``"v"``.
    :param children: its child nodes.
    :param sizes: its sizes; even ones when omitted.
    :returns: the node.
    """
    return {"split": orientation, "sizes": sizes or [100] * len(children), "children": list(children)}


def tree(main: dict[str, Any], **parts: Any) -> dict[str, Any]:
    """A stored layout.

    :param main: the main container's node.
    :param parts: ``floating``, ``pinned``, ``unplaced``.
    :returns: the layout.
    """
    return {"format": 1, "main": main, **parts}


def shape(node: dict[str, Any]) -> Any:
    """A stored node's structure, sizes left out: what a restore into another window size must keep.

    :param node: a stored node.
    :returns: nested lists of dock names, with ``(closed)`` marks and the current tab first-class.
    """
    if "area" in node:
        docks = [entry["name"] + (" (closed)" if entry["closed"] else "") for entry in node["area"]]
        return {"tabs": docks, "current": node.get("current")}
    return {node["split"]: [shape(child) for child in node["children"]]}


def ratios(node: dict[str, Any]) -> Any:
    """A stored node's splitter sizes as shares of their splitter, rounded: what survives the splitter scaling
    the stored pixels to the room it has.

    :param node: a stored node.
    :returns: nested lists of shares, one list per splitter.
    """
    if "area" in node:
        return None
    total = sum(node["sizes"])
    return [[round(size / total, 2) for size in node["sizes"]], *[ratios(child) for child in node["children"]]]


def ignore(dock: QtAds.CDockWidget) -> None:
    """A ``place_unnamed`` that leaves every dock where it is.

    :param dock: the unnamed dock.
    """
    del dock


# endregion


# region round trips
def test_a_nested_layout_round_trips_with_tabs_closed_docks_and_sizes(window: QMainWindow, qtbot: QtBot) -> None:
    """Splits in both directions, tabs, the current tab, a closed dock and the splitter sizes all come back --
    the sizes in proportion, the splitter scaling them to the room it has.

    **Test steps:**

    * restore a nested layout into an as-built manager, and save it back
    * verify the saved tree is the one restored, sizes in proportion, and the docks are open or closed as it says
    """
    manager, docks = make_manager(window, "ABCDE")
    layout = tree(
        split(
            "h",
            area("A"),
            split("v", area("B", "C", closed="C"), area("D"), sizes=[500, 200]),
            area("E"),
            sizes=[150, 500, 300],
        )
    )

    assert QtAdsLayout(manager).restore(layout, place_unnamed=ignore)
    qtbot.wait(10)

    saved = QtAdsLayout(manager).save()
    assert shape(saved["main"]) == shape(layout["main"])
    assert ratios(saved["main"]) == ratios(layout["main"])
    assert docks["C"].isClosed()
    assert not docks["B"].isClosed()


def test_a_layout_saved_by_one_manager_restores_into_another(window: QMainWindow) -> None:
    """What one manager saves, another with the same docks rebuilds: the round trip across a restart.

    **Test steps:**

    * lay docks out by hand in one manager -- a split, a tab, a floating window, a pinned dock -- and save
    * restore that into a fresh, as-built manager and save again
    * verify the two trees match
    """
    manager, docks = make_manager(window, "ABCDEF")
    first = docks["A"].dockAreaWidget()
    manager.addDockWidget(RIGHT, docks["B"], first)
    manager.addDockWidget(CENTER, docks["C"], docks["B"].dockAreaWidget())
    manager.addDockWidgetFloating(docks["D"])
    manager.addDockWidget(RIGHT, docks["E"], docks["D"].dockAreaWidget())
    docks["F"].setAutoHide(True, QtAds.SideBarRight)
    saved = QtAdsLayout(manager).save()

    other, _ = make_manager(window, "ABCDEF")
    assert QtAdsLayout(other).restore(saved, place_unnamed=ignore)

    again = QtAdsLayout(other).save()
    assert shape(again["main"]) == shape(saved["main"])
    assert [shape(item["root"]) for item in again["floating"]] == [shape(item["root"]) for item in saved["floating"]]
    assert [item["geometry"] for item in again["floating"]] == [item["geometry"] for item in saved["floating"]]
    assert again["pinned"] == saved["pinned"]


def test_a_floating_window_of_two_docks_round_trips(window: QMainWindow) -> None:
    """A floating window holding a split of two docks comes back as one window, at its geometry -- the browsers
    case #102 was filed for, which the QtAds blob emptied.

    **Test steps:**

    * restore a layout with a floating window holding two docks side by side
    * verify one floating container holds both, at the stored geometry, and saving gives the same tree
    """
    manager, docks = make_manager(window, "ABC")
    floating = {"geometry": [120, 80, 600, 400], "root": split("h", area("B"), area("C"), sizes=[300, 300])}
    layout = tree(area("A"), floating=[floating])

    assert QtAdsLayout(manager).restore(layout, place_unnamed=ignore)

    container = docks["B"].floatingDockContainer()
    assert container is not None
    assert docks["C"].floatingDockContainer() is container
    assert container.geometry() == QRect(120, 80, 600, 400)
    assert shape(QtAdsLayout(manager).save()["floating"][0]["root"]) == shape(floating["root"])


def test_pinned_docks_round_trip_in_tab_order_with_their_size_and_closed_state(window: QMainWindow) -> None:
    """Each sidebar's docks come back pinned there, in order, closed or not, with the panel's size.

    **Test steps:**

    * restore a layout pinning two docks to the right sidebar, one closed, with a panel size
    * verify both are pinned right in that order, the closed one closed, the panel sized, and it saves the same
    """
    manager, docks = make_manager(window, "ABC")
    pinned = {
        "side": "right",
        "docks": [{"name": "B", "closed": False}, {"name": "C", "closed": True}],
        "size": 240,
    }

    assert QtAdsLayout(manager).restore(tree(area("A"), pinned=[pinned]), place_unnamed=ignore)

    assert docks["B"].isAutoHide()
    assert docks["B"].autoHideLocation() == QtAds.SideBarRight
    assert docks["C"].isClosed()
    container = docks["B"].autoHideDockContainer()
    assert container is not None
    assert container.width() == 240
    assert QtAdsLayout(manager).save()["pinned"] == [pinned]


# endregion


# region degrading per node
def test_a_dock_the_layout_names_but_the_manager_lacks_is_skipped(window: QMainWindow) -> None:
    """An unknown dock drops out of its area and the rest of the layout restores around it.

    **Test steps:**

    * restore a layout whose areas also name a dock the manager does not have
    * verify the known docks are laid out as stored, and the unknown one is nowhere in the saved tree
    """
    manager, _ = make_manager(window, "AB")
    layout = tree(split("h", area("A", "gone"), area("B")))

    assert QtAdsLayout(manager).restore(layout, place_unnamed=ignore)

    assert shape(QtAdsLayout(manager).save()["main"]) == shape(split("h", area("A"), area("B")))


def test_an_area_left_empty_by_unknown_docks_is_dropped_and_its_splitter_collapses(window: QMainWindow) -> None:
    """When every dock of an area is unknown the area goes, and a splitter left with one child is that child.

    **Test steps:**

    * restore a layout splitting a known area from one holding only unknown docks
    * verify the known docks are laid out with no split
    """
    manager, _ = make_manager(window, "AB")
    layout = tree(split("h", area("A", "B"), area("gone", "lost")))

    assert QtAdsLayout(manager).restore(layout, place_unnamed=ignore)

    assert shape(QtAdsLayout(manager).save()["main"]) == shape(area("A", "B"))


def test_a_dock_the_layout_does_not_name_is_handed_to_place_unnamed(window: QMainWindow) -> None:
    """A dock built after the layout was saved is the caller's to place; the rest restores as stored.

    **Test steps:**

    * restore a layout naming two of three docks
    * verify the third, and only it, reaches ``place_unnamed``
    """
    manager, docks = make_manager(window, "ABZ")
    placed: list[QtAds.CDockWidget] = []

    assert QtAdsLayout(manager).restore(tree(split("h", area("A"), area("B"))), place_unnamed=placed.append)

    assert placed == [docks["Z"]]


def test_anything_but_a_layout_restores_nothing(window: QMainWindow) -> None:
    """Not a dict, or a dict of another format -- an old QtAds blob among them -- leaves the layout alone.

    **Test steps:**

    * offer the restore bytes, a dict with no format and one of another format
    * verify each is refused, and no dock was handed to ``place_unnamed``
    """
    manager, _ = make_manager(window, "AB")
    placed: list[QtAds.CDockWidget] = []

    for layout in (b"\x00\x00\x00\xffblob", {"main": area("A")}, {"format": 2, "main": area("A")}):
        assert not QtAdsLayout(manager).restore(layout, place_unnamed=placed.append)

    assert not placed


def test_malformed_nodes_are_dropped_and_the_rest_restores(window: QMainWindow) -> None:
    """Every malformed part of a stored tree drops on its own: a non-dict node or dock entry, an area that is not
    a list, a splitter with no orientation or no children list, a dock name that is not a string, a repeated name,
    a state that is not base64, sizes that do not match the children, a floating window with no valid geometry,
    a sidebar that is not one.

    **Test steps:**

    * restore a layout carrying one of each next to well-formed nodes
    * verify the well-formed ones are laid out, the docks only malformed parts named are the caller's to place,
      and the bad state reaches nobody
    """
    manager, docks = make_manager(window, "ABCDE")
    states: list[tuple[str, bytes]] = []
    placed: list[str] = []
    layout = tree(
        {
            "split": "h",
            "sizes": [1, 2],  # not one per child: ignored
            "children": [
                "not a node",
                {"area": "not a list"},
                {"split": "x", "children": []},
                {"split": "v", "children": "not a list"},
                {"area": [42, {"name": 7}, {"name": "A", "closed": False, "state": "%%%"}, {"name": "A"}]},
                area("B"),
            ],
        },
        floating=["not a window", {"geometry": "nowhere", "root": area("C")}, {"geometry": [0, 0, 0, 10]}],
        pinned=[{"side": "middle", "docks": [{"name": "D"}]}, {"side": "left", "docks": []}],
    )

    assert QtAdsLayout(manager).restore(
        layout,
        place_unnamed=lambda dock: placed.append(dock.objectName()),
        restore_dock_state=lambda dock, state: states.append((dock.objectName(), state)),
    )

    assert sorted(placed) == ["D", "E"]
    assert docks["A"].dockAreaWidget() is not docks["B"].dockAreaWidget()
    assert docks["C"].floatingDockContainer() is not None
    assert not docks["D"].isAutoHide()
    assert not states


def test_create_dock_builds_a_dock_the_manager_lacks_from_its_state(window: QMainWindow) -> None:
    """For a manager whose layout defines its docks, a name it lacks is offered to ``create_dock`` with the
    entry's state; a ``None`` answer drops the entry.

    **Test steps:**

    * restore a layout naming two docks the manager lacks, one of which ``create_dock`` builds
    * verify the built dock is laid out where the layout says and was handed its state, and the other is gone
    """
    manager, _ = make_manager(window, "A")
    asked: list[tuple[str, bytes | None]] = []

    def create(name: str, state: bytes | None) -> QtAds.CDockWidget | None:
        asked.append((name, state))
        if name != "N":
            return None
        dock = QtAds.CDockWidget(manager, name)
        dock.setObjectName(name)
        dock.setWidget(QLabel(name))
        manager.addDockWidget(CENTER, dock)
        return dock

    new = {"name": "N", "closed": False, "state": base64.b64encode(b"new").decode("ascii")}
    layout = tree(split("h", area("A"), {"area": [new, {"name": "M", "closed": False}], "current": "N"}))

    assert QtAdsLayout(manager).restore(layout, place_unnamed=ignore, create_dock=create)

    assert asked == [("N", b"new"), ("M", None)]
    assert shape(QtAdsLayout(manager).save()["main"]) == shape(split("h", area("A"), area("N")))


# endregion


# region content state
def test_each_entry_carries_its_docks_content_state_and_hands_it_back(window: QMainWindow) -> None:
    """What ``dock_state`` gives for a dock rides in its entry, and the restore hands it back, once placed.

    **Test steps:**

    * save with a hook giving bytes for one dock and nothing for another
    * verify the bytes are stored base64 in that dock's entry only, and the restore hands them back to it
    """
    manager, docks = make_manager(window, "AB")
    saved = QtAdsLayout(manager).save(lambda dock: b"\x00state" if dock is docks["A"] else None)

    entries = {entry["name"]: entry for entry in saved["main"]["area"]}
    assert base64.b64decode(entries["A"]["state"]) == b"\x00state"
    assert "state" not in entries["B"]

    handed: list[tuple[QtAds.CDockWidget, bytes]] = []
    QtAdsLayout(manager).restore(
        saved, place_unnamed=ignore, restore_dock_state=lambda dock, state: handed.append((dock, state))
    )
    assert handed == [(docks["A"], b"\x00state")]


def test_a_dock_with_no_area_is_saved_unplaced_and_placed_by_the_caller_on_restore(
    window: QMainWindow, mocker: MockerFixture
) -> None:
    """A dock that sits in no area when the layout is saved keeps its entry -- its state survives -- and the
    restore hands it to ``place_unnamed`` with its state.

    **Test steps:**

    * make one dock report no area, and save with a state for it
    * verify it is stored as unplaced, and a restore places it through the caller and hands back its state
    """
    manager, docks = make_manager(window, "AB")
    mocker.patch.object(docks["B"], "dockAreaWidget", return_value=None)

    saved = QtAdsLayout(manager).save(lambda dock: b"kept" if dock is docks["B"] else None)

    assert [entry["name"] for entry in saved["unplaced"]] == ["B"]
    mocker.stopall()
    placed: list[QtAds.CDockWidget] = []
    handed: list[bytes] = []
    QtAdsLayout(manager).restore(
        tree(area("A"), unplaced=saved["unplaced"]),
        place_unnamed=placed.append,
        restore_dock_state=lambda dock, state: handed.append(state),
    )
    assert placed == [docks["B"]]
    assert handed == [b"kept"]


def test_two_docks_sharing_a_name_save_only_the_registered_one(window: QMainWindow) -> None:
    """A dock renamed to another's name (#364) is not saved under it: entries are read through the registry.

    **Test steps:**

    * split one dock off and float another, then give both the first dock's object name
    * verify the saved tree names that dock once, and neither the area nor the window left with only a renamed
      dock is saved
    """
    manager, docks = make_manager(window, "ABC")
    manager.addDockWidget(RIGHT, docks["B"], docks["A"].dockAreaWidget())
    manager.addDockWidgetFloating(docks["C"])
    docks["B"].setObjectName("A")
    docks["C"].setObjectName("A")

    saved = QtAdsLayout(manager).save()

    assert shape(saved["main"]) == shape(area("A"))
    assert "floating" not in saved


# endregion


# region moving docks into place
def test_a_closed_dock_moved_into_its_own_area_shows_its_tab(window: QMainWindow, qtbot: QtBot) -> None:
    """A dock that is closed when the restore moves it comes out open *with its tab shown*.

    QtAds moves a closed dock as an open one with its tab still hidden, so nothing later shows the tab: a
    restored document's own areas came back with no tab strip and a Content Images dock that never loaded (#102).

    **Test steps:**

    * close three of four docks, then restore a layout putting each in an area of its own, open
    * verify every dock is open and its tab is on screen
    """
    manager, docks = make_manager(window, "ABCD")
    for name in "BCD":
        docks[name].toggleView(False)

    QtAdsLayout(manager).restore(
        tree(split("v", split("h", area("A"), area("B")), split("h", area("C"), area("D")))), place_unnamed=ignore
    )
    qtbot.wait(10)

    for dock in docks.values():
        assert not dock.isClosed()
        assert not dock.tabWidget().isHidden()


def test_a_main_tree_whose_first_dock_floats_is_built_in_the_main_container(window: QMainWindow) -> None:
    """The main tree grows from its first dock only where that dock already sits in the main container; a dock
    floating at the time is moved there first, and with nothing in the main container it starts it.

    **Test steps:**

    * float every dock, then restore a layout putting them all in the main container
    * verify none is floating any more
    """
    manager, docks = make_manager(window, "AB")
    for dock in docks.values():
        manager.addDockWidgetFloating(dock)

    QtAdsLayout(manager).restore(tree(split("h", area("A"), area("B"))), place_unnamed=ignore)

    assert all(dock.floatingDockContainer() is None for dock in docks.values())
    assert shape(QtAdsLayout(manager).save()["main"]) == shape(split("h", area("A"), area("B")))


def test_a_pinned_dock_is_unpinned_to_be_docked_and_repinned_to_its_new_side(window: QMainWindow) -> None:
    """A pinned dock the layout docks is taken out of its sidebar; one pinned elsewhere moves sidebar; one
    already pinned where the layout wants it stays.

    **Test steps:**

    * pin three docks to the left
    * restore a layout docking one, pinning one right and leaving one left
    * verify each ends where the layout says
    """
    manager, docks = make_manager(window, "ABCD")
    for name in "BCD":
        docks[name].setAutoHide(True, QtAds.SideBarLeft)
    pinned = [
        {"side": "right", "docks": [{"name": "C", "closed": False}]},
        {"side": "left", "docks": [{"name": "D", "closed": False}]},
    ]

    QtAdsLayout(manager).restore(tree(split("h", area("A"), area("B")), pinned=pinned), place_unnamed=ignore)

    assert not docks["B"].isAutoHide()
    assert docks["C"].autoHideLocation() == QtAds.SideBarRight
    assert docks["D"].autoHideLocation() == QtAds.SideBarLeft


def test_a_floating_dock_is_docked_before_it_is_pinned_and_leaves_no_window(window: QMainWindow) -> None:
    """Pinning a floating dock straight from its window leaves the window behind
    ([[appendices.qt-ads#auto-hide-abandoned-float]]), so a floating dock is docked first.

    **Test steps:**

    * float a dock, then restore a layout pinning it
    * verify it is pinned and no floating container is left
    """
    manager, docks = make_manager(window, "AB")
    manager.addDockWidgetFloating(docks["B"])

    QtAdsLayout(manager).restore(
        tree(area("A"), pinned=[{"side": "bottom", "docks": [{"name": "B", "closed": False}], "size": "tall"}]),
        place_unnamed=ignore,
    )

    assert docks["B"].autoHideLocation() == QtAds.SideBarBottom
    assert all(not container.isVisible() for container in window.findChildren(QtAds.CFloatingDockContainer))


def test_a_manager_that_never_pins_docks_a_pinned_entry_in_its_main_container(window: QMainWindow) -> None:
    """With ``pins=False`` a ``pinned`` entry is laid into the main container instead: pinning would grow a nested
    manager a sidebar of its own, and only a dock QtAds stole ever wrote such an entry (#491).

    **Test steps:**

    * pin a dock, then restore with ``pins=False`` a layout naming it pinned
    * verify it is unpinned, in the main container, and saved as no pin
    """
    manager, docks = make_manager(window, "AB")
    docks["B"].setAutoHide(True, QtAds.SideBarLeft)
    pinned = [{"side": "left", "docks": [{"name": "B", "closed": False}], "size": 300}]

    QtAdsLayout(manager, pins=False).restore(tree(area("A"), pinned=pinned), place_unnamed=ignore)

    assert not docks["B"].isAutoHide()
    assert placed_area(docks["B"]).dockContainer() is manager
    assert "pinned" not in QtAdsLayout(manager).save()


def test_a_dock_pinned_to_its_side_in_another_managers_sidebar_is_brought_home(
    window: QMainWindow, qtbot: QtBot
) -> None:
    """A dock pinned to the stored side is left alone only when the sidebar is this manager's own: QtAds pins a
    nested manager's dock into an outer sidebar ([[appendices.qt-ads#recursive-sidebar-drop]]), and the restore
    pins it back here instead.

    **Test steps:**

    * nest a manager in a dock of an outer one, and pin its dock into the outer left sidebar
    * restore the nested manager's layout naming the dock pinned left
    * verify the dock is pinned left in the nested manager's sidebar, and owned by it
    """
    outer, outer_docks = make_manager(window, "H")
    inner = QtAds.CDockManager(outer_docks["H"])
    outer_docks["H"].setWidget(inner)
    dock = QtAds.CDockWidget(inner, "S")
    dock.setObjectName("S")
    dock.setWidget(QLabel("S"))
    inner.addDockWidget(CENTER, dock)
    qtbot.wait(10)
    outer.createAndSetupAutoHideContainer(QtAds.SideBarLeft, dock, -1)

    QtAdsLayout(inner).restore(
        {"format": 1, "pinned": [{"side": "left", "docks": [{"name": "S", "closed": False}]}]}, place_unnamed=ignore
    )

    container = dock.autoHideDockContainer()
    assert container is not None
    assert container.sideBarLocation() == QtAds.SideBarLeft
    assert container.dockContainer() is inner
    assert dock.dockManager() is inner


def test_the_restore_announces_itself_as_a_restored_state(window: QMainWindow, qtbot: QtBot) -> None:
    """The restore ends with ``stateRestored``, which the manager's helpers re-track their areas on.

    **Test steps:**

    * restore a layout while waiting on the manager's signal
    * verify it fired
    """
    manager, _ = make_manager(window, "A")

    with qtbot.waitSignal(manager.stateRestored, timeout=1000):
        QtAdsLayout(manager).restore(tree(area("A")), place_unnamed=ignore)


# endregion


# region sizes
def test_a_splitter_shared_with_an_area_the_layout_does_not_name_keeps_its_sizes(
    window: QMainWindow, mocker: MockerFixture
) -> None:
    """Sizes are given only to a splitter of the tree's own shape: one that also holds the area of a dock the
    layout does not name keeps QtAds' sizes, rather than being sized pane for pane against the wrong panes.

    **Test steps:**

    * build a dock the layout will not name in an area of its own, beside the one the tree grows from
    * restore a split the same way round, spying on ``setSizes``
    * verify no splitter was sized
    """
    manager, docks = make_manager(window, "ABZ")
    manager.addDockWidget(RIGHT, docks["Z"], docks["A"].dockAreaWidget())
    set_sizes = mocker.spy(QSplitter, "setSizes")

    QtAdsLayout(manager).restore(tree(split("h", area("A"), area("B"), sizes=[600, 300])), place_unnamed=ignore)

    set_sizes.assert_not_called()


def test_a_layout_with_no_main_tree_builds_only_its_other_parts(window: QMainWindow) -> None:
    """A layout whose docks are all floating or pinned has no main tree, and none is built.

    **Test steps:**

    * restore a layout with one floating window and no main tree
    * verify its dock floats, and the dock it does not name is the caller's to place
    """
    manager, docks = make_manager(window, "AB")
    placed: list[QtAds.CDockWidget] = []
    layout = {"format": 1, "floating": [{"geometry": [10, 10, 300, 200], "root": area("B")}]}

    assert QtAdsLayout(manager).restore(layout, place_unnamed=placed.append)

    assert docks["B"].floatingDockContainer() is not None
    assert placed == [docks["A"]]


@mark.parametrize("sizes", [[0, 0], [100]], ids=["all zero", "not one per child"])
def test_sizes_that_say_nothing_are_not_applied(window: QMainWindow, mocker: MockerFixture, sizes: list[int]) -> None:
    """A splitter saved before it was ever laid out reads all zeroes; neither those nor a mismatched list are
    applied.

    **Test steps:**

    * restore a split with such sizes, spying on ``setSizes``
    * verify no splitter was sized
    """
    manager, _ = make_manager(window, "AB")
    set_sizes = mocker.spy(QSplitter, "setSizes")

    QtAdsLayout(manager).restore(tree(split("h", area("A"), area("B"), sizes=sizes)), place_unnamed=ignore)

    set_sizes.assert_not_called()


# endregion


# region the tree's own shape
def test_a_splitter_inside_one_running_the_same_way_is_spliced_into_it() -> None:
    """QtAds can nest a splitter in one of the same orientation; the tree keeps one canonical shape, the inner
    children taking the outer pane's size in their own proportion, or evenly without sizes of their own.

    **Test steps:**

    * normalize a splitter holding a same-way splitter, with and without inner sizes
    * verify the inner children are spliced in with their share of the size
    """
    a, b, c = (LayoutArea([LayoutDock(name, closed=False)]) for name in "abc")

    sized = normalized(LayoutSplit(True, [a, LayoutSplit(True, [b, c], [1, 3])], [100, 400]))
    even = normalized(LayoutSplit(True, [a, LayoutSplit(True, [b, c])], [100, 400]))
    unsized = normalized(LayoutSplit(True, [a, LayoutSplit(True, [b, c], [1, 3])]))

    assert sized == LayoutSplit(True, [a, b, c], [100, 100, 300])
    assert even == LayoutSplit(True, [a, b, c], [100, 200, 200])
    assert unsized == LayoutSplit(True, [a, b, c], [])


def test_an_empty_splitter_is_no_node_and_a_single_child_is_that_child() -> None:
    """QtAds roots every container in a splitter that often holds one child; the tree has neither shape.

    **Test steps:**

    * normalize an empty splitter and a single-child one
    * verify the first is nothing and the second is its child
    """
    only = LayoutArea([LayoutDock("only", closed=False)])

    assert normalized(LayoutSplit(False, [])) is None
    assert normalized(LayoutSplit(False, [only], [5])) is only


def test_widgets_in_no_shared_splitter_have_no_common_splitter(qtbot: QtBot) -> None:
    """``common_splitter`` answers ``None`` for widgets no splitter holds both of.

    **Test steps:**

    * ask for the common splitter of two unrelated widgets
    * verify there is none
    """
    first, second = QWidget(), QWidget()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    child = QWidget(first)

    assert common_splitter(child, second) is None


def test_reading_a_splitters_panes_leaves_qt_made_objects_below_them_valid(window: QMainWindow) -> None:
    """Reading a temporary splitter wrapper's panes registers nothing on it: ``QSplitter.widget(i)`` would, and
    freeing that wrapper then invalidates every Qt-made object below the pane -- a document toolbar's actions --
    while they live on (#102).

    **Test steps:**

    * give a dock a toolbar with a Qt-made action, split it from another
    * read its splitter's panes through a temporary wrapper, then let the wrapper go
    * verify the panes are the splitter's, in order, and the action is still valid
    """
    manager, docks = make_manager(window, "AB")
    inner = QMainWindow()
    toolbar = QToolBar()
    inner.addToolBar(toolbar)
    action = toolbar.addWidget(QWidget())
    docks["B"].setWidget(inner)
    manager.addDockWidget(RIGHT, docks["B"], docks["A"].dockAreaWidget())

    def panes_of_a_temporary_wrapper() -> list[bool]:
        area_b = docks["B"].dockAreaWidget()
        assert area_b is not None
        splitter = area_b.parentSplitter()
        assert splitter is not None
        return [pane is area_b for pane in splitter_panes(splitter)]

    assert panes_of_a_temporary_wrapper() == [False, True]
    assert shiboken6.isValid(action)


# endregion
