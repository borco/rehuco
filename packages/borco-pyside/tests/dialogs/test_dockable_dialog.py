"""Tests for DockableDialog: a CDockWidget-hosted panel with restore-on-start persistence."""

from collections.abc import Iterator
from typing import cast

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogFrame, DockableDialogSettings
from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot


@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real `CDockManager` kept alive for the whole test (see ``test_qtads_focus_tracker.py`` for
    why this is a generator fixture, not a plain ``return``).
    """
    manager = QtAds.CDockManager()
    qtbot.addWidget(manager)
    yield manager


def test_content_is_exposed_and_hosted_by_the_dock(manager: QtAds.CDockManager) -> None:
    """The constructor's content widget is reachable via ``content`` and actually shown by the dock.

    **Test steps:**

    * build a dialog around a label
    * verify ``content`` returns that same label
    * verify the dock's own widget tree contains it
    """
    content = QLabel("hello")
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", content)

    assert dialog.content is content
    assert dialog.dock.widget().findChild(QLabel) is content


def test_object_name_is_set_on_the_dock(manager: QtAds.CDockManager) -> None:
    """The dock's ``objectName`` matches the constructor's ``object_name``, for later lookup.

    **Test steps:**

    * build a dialog with a given object name
    * verify the dock's ``objectName()`` matches
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())

    assert dialog.dock.objectName() == "some_dialog"
    assert dialog.object_name == "some_dialog"


def test_toggle_action_shows_and_hides_the_dock(manager: QtAds.CDockManager) -> None:
    """Triggering ``toggle_action`` shows/hides the dock, once it's actually placed in the manager.

    A dock QtAds just placed via ``addDockWidget`` starts open (confirmed empirically), so the first
    trigger here closes it, not opens it.

    **Test steps:**

    * build a dialog and add its dock to the manager
    * toggle the action off
    * verify the dock is now closed
    * toggle the action on
    * verify the dock is open again
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)

    dialog.toggle_action.trigger()
    assert dialog.dock.isClosed()

    dialog.toggle_action.trigger()
    assert not dialog.dock.isClosed()


def test_place_floating_makes_the_dock_float(manager: QtAds.CDockManager) -> None:
    """``place_floating`` places the dock in its own floating container, not docked into any area.

    **Test steps:**

    * build a dialog and call ``place_floating``
    * verify the dock reports itself as floating, with a real floating container
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())

    dialog.place_floating()

    assert dialog.dock.isFloating()
    assert dialog.dock.floatingDockContainer() is not None


def test_place_floating_stays_hidden_until_the_manager_is_shown(qtbot: QtBot, manager: QtAds.CDockManager) -> None:
    """A freshly-floated dock follows ordinary Qt show semantics -- hidden until its top-level
    ancestor is actually shown -- unlike a later ``CDockManager.restoreState()`` recreating a
    previously-floating dock, which shows its container immediately regardless (#47).

    **Test steps:**

    * build a dialog and call ``place_floating`` without showing the manager
    * verify its floating container is not visible
    * show the manager
    * verify the floating container becomes visible too
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())

    dialog.place_floating()

    container = dialog.dock.floatingDockContainer()
    assert container is not None
    assert not container.isVisible()

    manager.show()
    qtbot.waitExposed(manager)

    assert container.isVisible()


def test_save_settings_reflects_current_visibility_and_checkbox(manager: QtAds.CDockManager) -> None:
    """``save_settings`` captures the dock's current open/closed state and the checkbox value.

    **Test steps:**

    * build a dialog, add its dock, open it, and check "Restore on start"
    * verify ``save_settings`` reports both as True
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)
    dialog.dock.toggleView(True)

    frame = cast(DockableDialogFrame, dialog.dock.widget())
    frame.restore_on_start = True

    saved = dialog.save_settings()

    assert saved.visible is True
    assert saved.restore_on_start is True


def test_restore_settings_reopens_the_dock_only_when_both_flags_were_set(
    manager: QtAds.CDockManager,
) -> None:
    """The dock only reopens on restore when it was both visible and restore-on-start was checked.

    **Test steps:**

    * build a dialog and add its (initially closed) dock
    * restore settings with visible=True but restore_on_start=False
    * verify the dock stays closed
    * restore settings with both True
    * verify the dock is now open
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)

    dialog.restore_settings(DockableDialogSettings(visible=True, restore_on_start=False))
    assert dialog.dock.isClosed()

    dialog.restore_settings(DockableDialogSettings(visible=True, restore_on_start=True))
    assert not dialog.dock.isClosed()


def test_enforce_restore_on_start_closes_an_open_dock_when_unchecked(manager: QtAds.CDockManager) -> None:
    """An open dock whose "Restore on start" checkbox is unchecked gets closed.

    **Test steps:**

    * build a dialog, add its (open-by-default) dock, leave "Restore on start" unchecked
    * call ``enforce_restore_on_start``
    * verify the dock is now closed
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)
    assert not dialog.dock.isClosed()

    dialog.enforce_restore_on_start()

    assert dialog.dock.isClosed()


def test_enforce_restore_on_start_leaves_an_open_dock_alone_when_checked(manager: QtAds.CDockManager) -> None:
    """An open dock whose "Restore on start" checkbox is checked stays open.

    **Test steps:**

    * build a dialog, add its (open-by-default) dock, check "Restore on start"
    * call ``enforce_restore_on_start``
    * verify the dock is still open
    """
    dialog = DockableDialog(manager, "some_dialog", "Some Dialog", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)
    frame = cast(DockableDialogFrame, dialog.dock.widget())
    frame.restore_on_start = True

    dialog.enforce_restore_on_start()

    assert not dialog.dock.isClosed()
