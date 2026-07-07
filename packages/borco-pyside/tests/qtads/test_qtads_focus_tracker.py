"""Tests for QtAdsFocusTracker: tracking (and marking) the current dock within a CDockManager."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from borco_pyside.qtads.qtads_focus_tracker import QtAdsFocusTracker
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

MARKER = "* "


@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real `CDockManager` kept alive for the whole test.

    A generator fixture, not a plain ``return``: `CDockManager()` has no Qt parent, so a ``return``
    would let it be garbage-collected (``qtbot.addWidget`` keeps only a weakref) -- see
    ``test_qtads_utils`` for the full reasoning. Pausing at ``yield`` keeps it alive here.
    """
    manager = QtAds.CDockManager()
    qtbot.addWidget(manager)
    yield manager


def add_dock(
    manager: QtAds.CDockManager,
    name: str,
    area: QtAds.DockWidgetArea = QtAds.CenterDockWidgetArea,
    target: QtAds.CDockAreaWidget | None = None,
) -> QtAds.CDockWidget:
    """Build a real dock named ``name`` and add it to ``manager`` at ``area`` (relative to ``target``).

    :param manager: the dock manager to add to.
    :param name: the dock's object name and initial title.
    :param area: where to place it (defaults to a center tab).
    :param target: the area to place it relative to, or ``None`` for the whole manager.
    :returns: the new dock.
    """
    dock = QtAds.CDockWidget(manager, name)
    dock.setObjectName(name)
    dock.setWidget(QWidget())
    manager.addDockWidget(area, dock, target)
    return dock


def test_construction_without_a_qapplication_skips_focus_tracking(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """Construction succeeds (just without the ``focusChanged`` hook) when no ``QApplication`` runs.

    **Test steps:**

    * mock ``QApplication.instance()`` to return ``None``
    * construct a tracker
    * verify it built with no current dock and did not raise
    """
    mocker.patch("borco_pyside.qtads.qtads_focus_tracker.QApplication.instance", return_value=None)

    tracker = QtAdsFocusTracker(manager)

    assert tracker.current_dock is None


def test_first_dock_added_becomes_current(manager: QtAds.CDockManager) -> None:
    """The first dock added to the manager is adopted as current automatically.

    **Test steps:**

    * build a tracker, then add one dock
    * verify that dock is now the current one
    """
    tracker = QtAdsFocusTracker(manager)

    dock = add_dock(manager, "one")

    assert tracker.current_dock is dock


def test_tabbing_a_dock_into_an_existing_area_makes_it_current(manager: QtAds.CDockManager) -> None:
    """A dock tabbed into an existing area becomes current, despite QtAds' signal ordering.

    **Test steps:**

    * add a first dock (current), then a second tabbed into the same area
    * verify the second dock is now current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")

    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())

    assert tracker.current_dock is second


def test_splitting_a_dock_into_a_new_area_leaves_the_first_current(manager: QtAds.CDockManager) -> None:
    """A dock split into its own new area does not steal current-ness from the first.

    **Test steps:**

    * add a first dock (current), then split a second into its own area
    * verify the first dock is still current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")

    add_dock(manager, "two", QtAds.RightDockWidgetArea, first.dockAreaWidget())

    assert tracker.current_dock is first


def test_switching_the_current_tab_updates_the_current_dock(manager: QtAds.CDockManager) -> None:
    """Selecting a different tab in a shared area makes that tab's dock current.

    **Test steps:**

    * add two docks tabbed together (the second is current)
    * bring the first's tab to the front
    * verify the first dock is now current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())

    area = first.dockAreaWidget()
    assert area is not None
    area.setCurrentIndex(area.index(first))

    assert tracker.current_dock is first


def test_current_dock_marker_marks_only_the_current_dock(manager: QtAds.CDockManager) -> None:
    """The marker prefixes only the current dock's title, moving as current-ness moves.

    **Test steps:**

    * build a marking tracker, add two tabbed docks (second current)
    * verify only the second's title carries the marker
    * switch to the first
    * verify the marker moved to the first and off the second
    """
    tracker = QtAdsFocusTracker(manager, current_dock_marker=MARKER)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    assert not first.windowTitle().startswith(MARKER)
    assert second.windowTitle().startswith(MARKER)

    area = first.dockAreaWidget()
    assert area is not None
    area.setCurrentIndex(area.index(first))

    assert tracker.current_dock is first
    assert first.windowTitle().startswith(MARKER)
    assert not second.windowTitle().startswith(MARKER)


def test_empty_marker_leaves_titles_untouched(manager: QtAds.CDockManager) -> None:
    """With the default empty marker, titles are never rewritten.

    **Test steps:**

    * build a tracker with no marker, add a dock
    * verify its title is unchanged (its plain name)
    """
    tracker = QtAdsFocusTracker(manager)

    dock = add_dock(manager, "one")

    assert tracker.current_dock is dock
    assert dock.windowTitle() == "one"


def test_set_current_dock_reveals_a_stacked_dock(manager: QtAds.CDockManager) -> None:
    """``set_current_dock`` raises a tabbed-behind dock to the front and makes it current.

    **Test steps:**

    * add two docks tabbed together (the second is current/shown)
    * ``set_current_dock`` the first
    * verify the first is both shown (its area's current tab) and tracked as current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    area = first.dockAreaWidget()
    assert area is not None and area.dockWidget(area.currentIndex()) is second

    tracker.set_current_dock(first)

    assert area.dockWidget(area.currentIndex()) is first
    assert tracker.current_dock is first


def test_set_current_dock_none_clears_the_current_dock_and_its_marker(manager: QtAds.CDockManager) -> None:
    """``set_current_dock(None)`` clears current-ness and strips the marker from the old current.

    **Test steps:**

    * build a marking tracker, add a dock (current, marked)
    * ``set_current_dock(None)``
    * verify nothing is current and the old dock's marker is gone
    """
    tracker = QtAdsFocusTracker(manager, current_dock_marker=MARKER)
    dock = add_dock(manager, "one")
    assert dock.windowTitle().startswith(MARKER)

    tracker.set_current_dock(None)

    assert tracker.current_dock is None
    assert dock.windowTitle() == "one"


def test_setting_the_already_current_dock_is_a_noop(manager: QtAds.CDockManager) -> None:
    """Re-setting the current dock to itself neither re-emits nor rewrites its title.

    **Test steps:**

    * add a dock (current), spy on ``current_dock_changed``
    * ``set_current_dock`` that same dock
    * verify no change signal fired
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")
    emitted: list[object] = []
    tracker.current_dock_changed.connect(emitted.append)

    tracker.set_current_dock(dock)

    assert not emitted


def test_removing_the_current_dock_clears_it(manager: QtAds.CDockManager) -> None:
    """Removing the current dock resets the current dock to ``None``.

    **Test steps:**

    * add a dock (current), then remove it from the manager
    * verify nothing is current
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")

    manager.removeDockWidget(dock)

    assert tracker.current_dock is None


def test_removing_a_non_current_dock_leaves_the_current_dock(manager: QtAds.CDockManager) -> None:
    """Removing a dock that isn't current doesn't disturb the current one.

    **Test steps:**

    * add two tabbed docks (the second is current), remove the first
    * verify the second is still current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())

    manager.removeDockWidget(first)

    assert tracker.current_dock is second


def test_state_restore_retracks_areas_so_tab_switches_still_work(manager: QtAds.CDockManager) -> None:
    """After a layout restore rebuilds areas, tab switches keep updating the current dock.

    ``restoreState`` discards and recreates every ``CDockAreaWidget``, orphaning connections made
    before it; the tracker re-tracks on ``stateRestored``.

    **Test steps:**

    * add two tabbed docks and save the layout
    * restore it (rebuilding the area)
    * switch to the first dock's tab on the (rebuilt) area
    * verify the current dock followed the switch
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    state = bytes(manager.saveState().data())

    assert manager.restoreState(QByteArray(state))

    area = first.dockAreaWidget()
    assert area is not None
    area.setCurrentIndex(area.index(first))

    assert tracker.current_dock is first


def test_state_restore_skips_a_tracked_dock_with_no_area(manager: QtAds.CDockManager, mocker: MockerFixture) -> None:
    """The re-track loop skips a tracked dock that currently has no containing area.

    A stand-in dock (reporting no area) is registered directly, since a real dock always has an
    area after a successful restore -- this null case can't be reached through the public API alone.

    **Test steps:**

    * register a stand-in dock reporting no area, directly in the tracker's set
    * emit ``stateRestored``
    * verify the stand-in's area was queried (loop reached it) but nothing raised
    """
    tracker = QtAdsFocusTracker(manager)
    fake_dock = mocker.MagicMock()
    fake_dock.dockAreaWidget.return_value = None
    tracker._QtAdsFocusTracker__tracked_docks.add(fake_dock)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    manager.stateRestored.emit()

    fake_dock.dockAreaWidget.assert_called_once()


def test_dock_added_without_an_area_is_still_tracked(manager: QtAds.CDockManager, mocker: MockerFixture) -> None:
    """A dock reporting no area on add is still tracked and adopted, just without area hookup.

    Registers a stand-in dock (reporting no area) via the add handler, since a real added dock
    always has an area -- this null case can't be reached through the public API alone.

    **Test steps:**

    * feed a stand-in dock (reporting no area) to the add handler
    * verify it became the current dock (nothing was current before)
    """
    tracker = QtAdsFocusTracker(manager)
    fake_dock = mocker.MagicMock()
    fake_dock.dockAreaWidget.return_value = None

    tracker._QtAdsFocusTracker__on_dock_widget_added(fake_dock)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is fake_dock


def test_area_current_changed_ignores_a_deleted_area(manager: QtAds.CDockManager, mocker: MockerFixture) -> None:
    """A ``currentChanged`` from an area already torn down (Shiboken-deleted) is ignored.

    A stand-in area whose ``dockWidget`` raises ``RuntimeError`` stands in for the mid-teardown
    "already deleted" case QtAds can transiently fire -- unreachable through the public API.

    **Test steps:**

    * add a real dock (current)
    * fire the area handler with a stand-in area that raises ``RuntimeError``
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")
    dead_area = mocker.MagicMock()
    dead_area.dockWidget.side_effect = RuntimeError("already deleted")

    tracker._QtAdsFocusTracker__on_area_current_changed(dead_area, 0)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is dock


def test_area_current_changed_ignores_an_untracked_dock(manager: QtAds.CDockManager, mocker: MockerFixture) -> None:
    """A ``currentChanged`` resolving to a dock this tracker doesn't own is ignored.

    **Test steps:**

    * add a real dock (current)
    * fire the area handler with a stand-in area returning an untracked dock
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")
    area = mocker.MagicMock()
    area.dockWidget.return_value = mocker.MagicMock()

    tracker._QtAdsFocusTracker__on_area_current_changed(area, 0)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is dock


def test_focus_moving_into_a_tracked_dock_makes_it_current(manager: QtAds.CDockManager, qtbot: QtBot) -> None:
    """Keyboard focus entering a widget nested inside a tracked dock makes that dock current.

    **Test steps:**

    * add two split docks (the first is current)
    * report focus moving to a child widget nested under the second dock
    * verify the second dock is now current
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.RightDockWidgetArea, first.dockAreaWidget())
    assert tracker.current_dock is first
    nested = QWidget(second)
    qtbot.addWidget(nested)

    tracker._QtAdsFocusTracker__on_application_focus_changed(None, nested)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is second


def test_focus_moving_outside_every_tracked_dock_is_ignored(manager: QtAds.CDockManager, qtbot: QtBot) -> None:
    """Focus moving to a widget with no tracked-dock ancestor leaves the current dock alone.

    **Test steps:**

    * add a dock (current)
    * report focus moving to an unrelated, parentless widget
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")
    unrelated = QWidget()
    qtbot.addWidget(unrelated)

    tracker._QtAdsFocusTracker__on_application_focus_changed(None, unrelated)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is dock


def test_explicit_style_sheet_overrides_the_built_default(manager: QtAds.CDockManager) -> None:
    """A ``style_sheet`` argument is applied verbatim instead of the built default.

    **Test steps:**

    * construct a tracker with an explicit ``style_sheet``
    * verify the manager carries exactly that stylesheet
    """
    tracker = QtAdsFocusTracker(manager, style_sheet="QWidget { color: red; }")

    assert tracker.current_dock is None
    assert manager.styleSheet() == "QWidget { color: red; }"


def test_state_restore_resyncs_current_dock_to_the_restored_current_tab(manager: QtAds.CDockManager) -> None:
    """After a restore, the current dock follows the tab the restore made current -- no click needed.

    **Test steps:**

    * tab two docks together and make the second current, then save the layout
    * make the first current (the mismatch a restore would otherwise leave stale)
    * restore the saved layout (which makes the second current again)
    * verify the current dock resynced to the second without any manual switch
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    tracker.set_current_dock(second)
    state = bytes(manager.saveState().data())
    tracker.set_current_dock(first)
    assert tracker.current_dock is first

    assert manager.restoreState(QByteArray(state))

    assert tracker.current_dock is second


def test_state_restore_with_a_current_dock_that_has_no_area_is_a_noop(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """The resync skips a current dock that (improbably) has no containing area after a restore.

    **Test steps:**

    * register a stand-in current dock reporting no area, directly in the tracker
    * emit ``stateRestored``
    * verify nothing raised and the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    fake_current = mocker.MagicMock()
    fake_current.dockAreaWidget.return_value = None
    tracker._QtAdsFocusTracker__current_dock = fake_current  # type: ignore[attr-defined]  # pylint: disable=protected-access

    manager.stateRestored.emit()

    assert tracker.current_dock is fake_current


def test_state_restore_ignores_a_restored_tab_that_is_not_tracked(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """The resync ignores a restored current tab this tracker doesn't own.

    **Test steps:**

    * register a stand-in current dock whose area's current tab is an untracked dock
    * emit ``stateRestored``
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    fake_area = mocker.MagicMock()
    fake_area.dockWidget.return_value = mocker.MagicMock()
    fake_current = mocker.MagicMock()
    fake_current.dockAreaWidget.return_value = fake_area
    tracker._QtAdsFocusTracker__current_dock = fake_current  # type: ignore[attr-defined]  # pylint: disable=protected-access

    manager.stateRestored.emit()

    assert tracker.current_dock is fake_current


def test_styling_a_dock_mid_teardown_is_swallowed(manager: QtAds.CDockManager, mocker: MockerFixture) -> None:
    """A ``RuntimeError`` while styling a dock (Shiboken "already deleted") is caught, not propagated.

    **Test steps:**

    * make a stand-in dock whose ``tabWidget()`` raises ``RuntimeError`` current
    * verify it still became the current dock (the styling failure was swallowed)
    """
    tracker = QtAdsFocusTracker(manager)
    fake = mocker.MagicMock()
    fake.tabWidget.side_effect = RuntimeError("already deleted")

    tracker._QtAdsFocusTracker__set_current_dock(fake)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert tracker.current_dock is fake
