"""Tests for placing one late dock by a saved tree, and keeping docks a save lacked, in `QtAdsLayout` (#698)."""

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsLayout
from borco_pyside.qtads.qtads_layout import placed_area, with_kept
from PySide6.QtWidgets import QApplication, QMainWindow
from pytest import mark
from pytestqt.qtbot import QtBot

from .test_qtads_layout import area, auto_hide_flags, ignore, make_manager, shape, split, tree, window

__all__ = ["auto_hide_flags", "window"]


# region tab order and late placement
def tab_order(docks: dict[str, QtAds.CDockWidget]) -> str:
    """The names of the docks in the area of ``docks["A"]``, in tab order.

    :param docks: the manager's docks by name.
    :returns: the names, one letter each.
    """
    return "".join(dock.objectName() for dock in placed_area(docks["A"]).dockWidgets())


def drag_tab_onto(moved: QtAds.CDockWidget, target: QtAds.CDockWidget) -> None:
    """End a tab drag with ``moved``'s tab over ``target``'s -- what the user's drop reports.

    :param moved: the dock whose tab is dragged.
    :param target: the dock whose tab it is dropped on.
    """
    tab = target.tabWidget()
    moved.tabWidget().moved.emit(tab.mapToGlobal(tab.rect().center()))
    QApplication.processEvents()


def test_a_dragged_tab_order_is_what_is_saved_and_what_restores(window: QMainWindow, qtbot: QtBot) -> None:
    """A one-row order the reader dragged into place is saved in tab order and rebuilt by a manager that built its
    docks in another one (#698).

    **Test steps:**

    * build a row ``ABCD`` and drag ``A``'s tab onto ``D``'s, which gives ``BCDA``
    * verify the saved area lists ``BCDA``
    * restore that tree into a second manager whose row was built ``ABCD``
    * verify its tab order is ``BCDA`` and the current tab is the saved one
    """
    manager, docks = make_manager(window, "ABCD")
    qtbot.wait(10)
    drag_tab_onto(docks["A"], docks["D"])
    docks["C"].setAsCurrentTab()

    saved = QtAdsLayout(manager).save()

    assert [entry["name"] for entry in saved["main"]["area"]] == list("BCDA")
    assert saved["main"]["current"] == "C"
    other_window = QMainWindow()
    other_window.resize(800, 600)
    other_manager, other_docks = make_manager(other_window, "ABCD")
    assert QtAdsLayout(other_manager).restore(saved, place_unnamed=ignore)
    assert tab_order(other_docks) == "BCDA"
    assert placed_area(other_docks["A"]).currentDockWidget() is other_docks["C"]
    other_window.deleteLater()


@mark.parametrize(
    ("late", "present", "expected"),
    [("B", "ACD", "ABCD"), ("A", "BCD", "ABCD"), ("D", "ABC", "ABCD"), ("C", "ADB", "ADBC")],
)
def test_a_late_dock_goes_right_after_its_nearest_saved_neighbor_that_is_there(
    window: QMainWindow, late: str, present: str, expected: str
) -> None:
    """A dock that arrives after the rest joins its saved row at its saved index (#698).

    **Test steps:**

    * build a row of the ``present`` docks, then the ``late`` one tabbed in at the end
    * place the late dock by a tree saving ``ABCD``
    * verify the row reads as ``expected``: after the nearest saved neighbor before it that is there, else before the
      nearest one after it
    """
    manager, docks = make_manager(window, present + late)

    assert QtAdsLayout(manager).place(tree(area("A", "B", "C", "D")), docks[late])

    assert "".join(d.objectName() for d in placed_area(docks[late]).dockWidgets()) == expected


def test_a_late_dock_moves_back_over_a_neighbor_it_came_after(window: QMainWindow) -> None:
    """A dock already in the row at the wrong place is moved, forward or back (#698).

    **Test steps:**

    * build a row ``BCDA`` and place ``A`` by a tree saving ``ABCD``, then ``D`` by one saving ``DABC``
    * verify the rows read ``ABCD`` and then ``DABC``
    """
    manager, docks = make_manager(window, "BCDA")

    assert QtAdsLayout(manager).place(tree(area("A", "B", "C", "D")), docks["A"])
    assert tab_order(docks) == "ABCD"
    assert QtAdsLayout(manager).place(tree(area("D", "A", "B", "C")), docks["D"])
    assert tab_order(docks) == "DABC"


def test_a_dock_with_no_saved_neighbor_that_is_there_is_left_where_it_is(window: QMainWindow) -> None:
    """Placing changes nothing when the tree does not name the dock, names it alone, or is not a layout (#698).

    **Test steps:**

    * build a row ``AB``
    * place ``B`` by a tree naming only it, by one naming docks that are not there, by one without it, and by a
      non-layout
    * verify each returns ``False`` and the row is still ``AB``
    """
    manager, docks = make_manager(window, "AB")

    assert not QtAdsLayout(manager).place(tree(area("B")), docks["B"])
    assert not QtAdsLayout(manager).place(tree(area("X", "B", "Y")), docks["B"])
    assert not QtAdsLayout(manager).place(tree(area("A")), docks["B"])
    assert not QtAdsLayout(manager).place("nonsense", docks["B"])
    assert tab_order(docks) == "AB"


def test_a_late_dock_joins_the_floating_area_its_neighbor_sits_in(window: QMainWindow) -> None:
    """The area a dock is placed in is the neighbor's own, wherever it sits (#698).

    **Test steps:**

    * restore a tree with ``A``, ``C`` and ``D`` in the main area and ``B`` floating
    * place ``D`` by a tree that saves ``B`` and ``D`` together
    * verify it joined ``B``'s area, right after it
    """
    manager, docks = make_manager(window, "ABCD")
    assert QtAdsLayout(manager).restore(
        tree(area("A", "C", "D"), floating=[{"geometry": [10, 10, 300, 200], "root": area("B")}]), place_unnamed=ignore
    )

    assert QtAdsLayout(manager).place(tree(area("A", "C"), floating=[{"root": area("B", "D")}]), docks["D"])

    assert placed_area(docks["D"]) is placed_area(docks["B"])
    assert [d.objectName() for d in placed_area(docks["B"]).dockWidgets()] == ["B", "D"]


def test_kept_docks_go_back_beside_their_saved_neighbors() -> None:
    """A save made without some docks puts them back in their saved places, closed marks included (#698).

    **Test steps:**

    * save ``ADE`` while ``B`` and ``C`` (closed) were saved between ``A`` and ``D``
    * keep ``B`` and ``C``
    * verify the row is ``ABCDE``, ``C`` still closed and ``current`` unchanged, and the argument untouched
    """
    new = tree(area("A", "D", "E", current="D"))
    old = tree(area("A", "B", "C", "D", "E", closed="C"))

    kept = with_kept(new, old, {"B", "C"})

    assert shape(kept["main"]) == {"tabs": ["A", "B", "C (closed)", "D", "E"], "current": "D"}
    assert shape(new["main"]) == {"tabs": ["A", "D", "E"], "current": "D"}


def test_a_kept_dock_with_no_saved_neighbor_present_is_left_out() -> None:
    """Only a dock with a saved neighbor in the new tree can be put back, and one the new tree has stays as it is
    (#698).

    **Test steps:**

    * keep ``X`` (alone in an old area), ``B`` (already in the new tree) and not ``Z``
    * verify nothing is added
    * verify a non-layout old tree adds nothing either
    """
    new = tree(area("A", "B"))
    old = tree(split("h", area("A", "B", "Z"), area("X")))

    assert shape(with_kept(new, old, {"X", "B"})["main"]) == shape(new["main"])
    assert shape(with_kept(new, "nonsense", {"X"})["main"]) == shape(new["main"])


def test_a_kept_dock_follows_its_neighbor_into_a_floating_area() -> None:
    """The kept dock goes where its neighbor is now, in whichever area (#698).

    **Test steps:**

    * save a tree with ``B`` floating alone and ``A`` in the main area, where ``A``, ``B`` and ``C`` shared an area
    * keep ``C``
    * verify it joined the floating area after ``B``
    """
    new = tree(area("A"), floating=[{"geometry": [0, 0, 10, 10], "root": area("B")}])
    old = tree(area("A", "B", "C"))

    kept = with_kept(new, old, {"C"})

    assert shape(kept["floating"][0]["root"]) == {"tabs": ["B", "C"], "current": "B"}


def test_a_late_dock_is_placed_by_a_tree_with_splits(window: QMainWindow) -> None:
    """The saved area is found wherever the tree has it, splits included (#698).

    **Test steps:**

    * build a row ``ACB`` and place ``B`` by a tree with ``A, B`` beside ``C``
    * verify the row reads ``ABC``
    """
    manager, docks = make_manager(window, "ACB")

    assert QtAdsLayout(manager).place(tree(split("h", area("A", "B"), area("C"))), docks["B"])

    assert tab_order(docks) == "ABC"


def test_kept_docks_ignore_what_a_stored_tree_has_no_area_in() -> None:
    """A malformed stored node holds no area, so nothing is put back beside it, and a good one is still used (#698).

    **Test steps:**

    * keep ``B`` into an old tree whose split holds a non-node, a node with neither an area nor children, and an area
    * verify ``B`` is put back from that area
    * verify an old tree of one empty node adds nothing
    """
    new = tree(area("A"))
    junk = {"split": "h", "children": ["x", {"nothing": 1}, area("A", "B")]}

    assert shape(with_kept(new, tree(junk), {"B"})["main"]) == {"tabs": ["A", "B"], "current": "A"}
    assert shape(with_kept(new, tree({"nothing": 1}), {"B"})["main"]) == shape(new["main"])


def test_a_kept_dock_goes_beside_the_nearest_neighbor_the_new_tree_has() -> None:
    """A neighbor the new tree lacks is passed over for the next nearest, before it first and then after it (#698).

    **Test steps:**

    * save ``A`` only, where ``A, B, C, D`` was saved, and keep ``C``; verify ``C`` follows ``A``
    * save ``D`` only and keep ``B``; verify ``B`` goes before ``D``
    """
    old = tree(area("A", "B", "C", "D"))

    assert shape(with_kept(tree(area("A")), old, {"C"})["main"])["tabs"] == ["A", "C"]
    assert shape(with_kept(tree(area("D")), old, {"B"})["main"])["tabs"] == ["B", "D"]


# endregion
