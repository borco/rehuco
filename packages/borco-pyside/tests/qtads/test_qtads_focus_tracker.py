"""Tests for QtAdsFocusTracker: tracking (and marking) the current dock within a CDockManager."""

from collections.abc import Iterator

import PySide6QtAds as QtAds
from borco_pyside.qtads.qtads_focus_tracker import QtAdsFocusTracker
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real `CDockManager` kept alive for the whole test.

    A generator fixture, not a plain ``return``: `CDockManager()` has no Qt parent, so a ``return``
    would let it be garbage-collected (``qtbot.addWidget`` keeps only a weakref) -- see
    ``test_qtads_widgets`` for the full reasoning. Pausing at ``yield`` keeps it alive here.
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


def test_the_tracker_leaves_tab_titles_untouched(manager: QtAds.CDockManager) -> None:
    """The tracker never rewrites a dock's tab title -- current-ness is shown by styling alone.

    **Test steps:**

    * build a tracker, add two tabbed docks (the second becomes current)
    * switch current between them
    * verify each dock keeps exactly the title it was given, current or not
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    assert tracker.current_dock is second

    area = first.dockAreaWidget()
    assert area is not None
    area.setCurrentIndex(area.index(first))

    assert tracker.current_dock is first
    assert first.windowTitle() == "one"
    assert second.windowTitle() == "two"


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


def test_set_current_dock_none_clears_the_current_dock(manager: QtAds.CDockManager) -> None:
    """``set_current_dock(None)`` clears current-ness.

    **Test steps:**

    * add a dock (it becomes current)
    * ``set_current_dock(None)``
    * verify nothing is current
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")
    assert tracker.current_dock is dock

    tracker.set_current_dock(None)

    assert tracker.current_dock is None


def test_save_state_records_the_current_docks_object_name(manager: QtAds.CDockManager) -> None:
    """``save_state`` returns the current dock's object name as bytes.

    **Test steps:**

    * add a dock (it becomes current)
    * verify ``save_state`` returns its object name as UTF-8 bytes
    """
    tracker = QtAdsFocusTracker(manager)
    add_dock(manager, "one")

    assert tracker.save_state() == b"one"


def test_save_state_is_empty_without_a_current_dock(manager: QtAds.CDockManager) -> None:
    """``save_state`` returns empty bytes when nothing is current.

    **Test steps:**

    * build a tracker over an empty manager (nothing current)
    * verify ``save_state`` returns empty bytes
    """
    tracker = QtAdsFocusTracker(manager)

    assert tracker.save_state() == b""


def test_restore_state_reselects_the_saved_dock(manager: QtAds.CDockManager) -> None:
    """``restore_state`` re-selects the dock ``save_state`` recorded, even after current moved away.

    **Test steps:**

    * add two tabbed docks (the second is current) and save
    * make the first current (moving current away from the saved one)
    * restore the saved state and verify the second is current again
    """
    tracker = QtAdsFocusTracker(manager)
    first = add_dock(manager, "one")
    second = add_dock(manager, "two", QtAds.CenterDockWidgetArea, first.dockAreaWidget())
    state = tracker.save_state()
    tracker.set_current_dock(first)
    assert tracker.current_dock is first

    tracker.restore_state(state)

    assert tracker.current_dock is second


def test_restore_state_with_empty_bytes_is_a_noop(manager: QtAds.CDockManager) -> None:
    """``restore_state`` with empty bytes leaves the current dock unchanged.

    **Test steps:**

    * add a dock (current), then ``restore_state`` empty bytes
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")

    tracker.restore_state(b"")

    assert tracker.current_dock is dock


def test_restore_state_ignores_an_unknown_dock_name(manager: QtAds.CDockManager) -> None:
    """``restore_state`` naming a dock that isn't present leaves the current dock unchanged.

    **Test steps:**

    * add a dock (current), then ``restore_state`` a name no dock has
    * verify the current dock is unchanged
    """
    tracker = QtAdsFocusTracker(manager)
    dock = add_dock(manager, "one")

    tracker.restore_state(b"ghost")

    assert tracker.current_dock is dock


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


def test_tracked_focus_dock_stylesheet_builds_qss_from_its_colours(manager: QtAds.CDockManager) -> None:
    """The stylesheet builder emits the tracked-focus selectors with the given colours.

    **Test steps:**

    * build a stylesheet with explicit colours
    * verify it selects on the tracked-focus property and carries each colour
    """
    tracker = QtAdsFocusTracker(manager)

    qss = tracker.tracked_focus_dock_stylesheet(highlight="#111", label="#222", title_bar="#333")

    assert '[tracked_focus="true"]' in qss
    assert "#111" in qss
    assert "#222" in qss
    assert "#333" in qss


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


def test_styling_a_current_dock_with_no_close_button_re_polishes_without_it(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """A current dock whose tab shows no close button is styled without one (nothing to re-polish).

    The default config gives every tab a close button, so this branch (no button) is forced by
    reporting ``None`` from ``tab_close_button``.

    **Test steps:**

    * patch ``tab_close_button`` to report no button
    * add a dock (it becomes current, running the styling that looks for a close button)
    * verify it still became current, without raising
    """
    mocker.patch("borco_pyside.qtads.qtads_focus_tracker.tab_close_button", return_value=None)
    tracker = QtAdsFocusTracker(manager)

    dock = add_dock(manager, "one")

    assert tracker.current_dock is dock


def test_close_button_styling_skips_a_tab_with_no_close_button(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """The close-button styler is a no-op when the tab shows no close button.

    **Test steps:**

    * patch ``tab_close_button`` to report no button
    * call the close-button styler directly with a stand-in dock
    * verify the finder was consulted and nothing raised
    """
    finder = mocker.patch("borco_pyside.qtads.qtads_focus_tracker.tab_close_button", return_value=None)
    tracker = QtAdsFocusTracker(manager)
    dock = mocker.MagicMock()

    tracker._QtAdsFocusTracker__style_close_button(dock)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    finder.assert_called_once_with(dock)


def test_close_button_styling_of_a_deleted_dock_is_swallowed(
    manager: QtAds.CDockManager, mocker: MockerFixture
) -> None:
    """A ``RuntimeError`` from a mid-teardown tab (Shiboken "already deleted") is caught, not raised.

    Expected here because the deferred timer that runs this can fire after ``dock`` was closed.

    **Test steps:**

    * patch ``tab_close_button`` to raise ``RuntimeError``
    * call the close-button styler directly with a stand-in dock
    * verify the finder was consulted and nothing propagated
    """
    finder = mocker.patch(
        "borco_pyside.qtads.qtads_focus_tracker.tab_close_button",
        side_effect=RuntimeError("already deleted"),
    )
    tracker = QtAdsFocusTracker(manager)
    dock = mocker.MagicMock()

    tracker._QtAdsFocusTracker__style_close_button(dock)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    finder.assert_called_once_with(dock)
