"""Tests for DockableDialogManager: bulk save/restore across registered DockableDialogs.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_dockable_dialog_settings.py``)
rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

import PySide6QtAds as QtAds
from borco_pyside.dialogs import DockableDialog, DockableDialogManager, DockableDialogSettings
from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot


# region fixtures
# Mirrors test_dockable_dialog_settings.py's FakeSettings exactly -- kept as a separate copy rather
# than a shared import, matching this codebase's settings-test convention (see e.g.
# test_main_window_settings.py / test_unsaved_changes_dialog_settings.py).
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`DockableDialogSettings.load`/:meth:`~DockableDialogSettings.save` call them by
    name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture
def manager(qtbot: QtBot) -> Iterator[QtAds.CDockManager]:
    """A real `CDockManager` kept alive for the whole test."""
    manager = QtAds.CDockManager()
    qtbot.addWidget(manager)
    yield manager


# endregion


def test_save_all_persists_every_registered_dialog_under_its_own_group(
    manager: QtAds.CDockManager, settings: FakeSettings
) -> None:
    """Each registered dialog's settings land under a group keyed by its own object name.

    **Test steps:**

    * build and register two dialogs, one opened, one left closed
    * save all
    * verify each dialog's own group holds its own visibility
    """
    dialog_manager = DockableDialogManager()

    dialog_a = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_a.dock)
    dialog_a.dock.toggleView(True)
    dialog_manager.register(dialog_a)

    dialog_b = DockableDialog(manager, "dialog_b", "Dialog B", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_b.dock)
    dialog_b.dock.toggleView(False)  # a freshly-placed dock defaults open; close it explicitly
    dialog_manager.register(dialog_b)

    dialog_manager.save_all(settings)  # type: ignore[arg-type]

    assert settings.value("dockable_dialogs/dialog_a/visible") is True
    assert settings.value("dockable_dialogs/dialog_b/visible") is False


def test_restore_all_reopens_only_dialogs_that_were_visible_with_restore_on_start_checked(
    manager: QtAds.CDockManager, settings: FakeSettings
) -> None:
    """Restoring reopens exactly the dialogs saved as both visible and restore-on-start.

    **Test steps:**

    * pre-populate settings: dialog_a visible+restore_on_start, dialog_b visible only
    * build and register both dialogs (both start closed)
    * restore all
    * verify only dialog_a reopened
    """
    settings.setValue("dockable_dialogs/dialog_a/visible", True)
    settings.setValue("dockable_dialogs/dialog_a/restore_on_start", True)
    settings.setValue("dockable_dialogs/dialog_b/visible", True)
    settings.setValue("dockable_dialogs/dialog_b/restore_on_start", False)

    dialog_manager = DockableDialogManager()

    dialog_a = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_a.dock)
    dialog_manager.register(dialog_a)

    dialog_b = DockableDialog(manager, "dialog_b", "Dialog B", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_b.dock)
    dialog_manager.register(dialog_b)

    dialog_manager.restore_all(settings)  # type: ignore[arg-type]

    assert not dialog_a.dock.isClosed()
    assert dialog_b.dock.isClosed()


def test_enforce_restore_on_start_closes_every_unchecked_dialog(manager: QtAds.CDockManager) -> None:
    """Every registered dialog whose checkbox is unchecked gets closed; checked ones are untouched.

    **Test steps:**

    * build and register two open dialogs, only one with "Restore on start" checked
    * call ``enforce_restore_on_start``
    * verify the unchecked one is now closed and the checked one is still open
    """
    dialog_manager = DockableDialogManager()

    dialog_a = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_a.dock)
    dialog_manager.register(dialog_a)

    dialog_b = DockableDialog(manager, "dialog_b", "Dialog B", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_b.dock)
    dialog_b.restore_settings(DockableDialogSettings(visible=True, restore_on_start=True))
    dialog_manager.register(dialog_b)

    dialog_manager.enforce_restore_on_start()

    assert dialog_a.dock.isClosed()
    assert not dialog_b.dock.isClosed()


def test_register_is_idempotent_for_the_same_dialog(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """Registering the same dialog twice tracks it once, not twice.

    **Test steps:**

    * build a dialog, register it twice
    * save all
    * verify the dialog's settings were written exactly once (no duplicate-write side effect)
    """
    dialog_manager = DockableDialogManager()

    dialog = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)
    dialog_manager.register(dialog)
    dialog_manager.register(dialog)

    write_count = 0
    original_set_value = settings.setValue

    def counting_set_value(key: str, value: Any) -> None:
        nonlocal write_count
        write_count += 1
        original_set_value(key, value)

    settings.setValue = counting_set_value  # type: ignore[method-assign]

    dialog_manager.save_all(settings)  # type: ignore[arg-type]

    assert write_count == 2  # visible + restore_on_start, once each


def test_unregister_drops_a_previously_registered_dialog(manager: QtAds.CDockManager, settings: FakeSettings) -> None:
    """An unregistered dialog is no longer touched by the bulk calls.

    **Test steps:**

    * build and register two dialogs
    * unregister one
    * save all
    * verify only the still-registered dialog's group was written
    """
    dialog_manager = DockableDialogManager()

    dialog_a = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_a.dock)
    dialog_manager.register(dialog_a)

    dialog_b = DockableDialog(manager, "dialog_b", "Dialog B", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_b.dock)
    dialog_manager.register(dialog_b)

    dialog_manager.unregister(dialog_a)

    dialog_manager.save_all(settings)  # type: ignore[arg-type]

    assert settings.value("dockable_dialogs/dialog_a/visible") is None
    assert settings.value("dockable_dialogs/dialog_b/visible") is not None


def test_unregister_is_a_no_op_for_an_unregistered_dialog(manager: QtAds.CDockManager) -> None:
    """Unregistering a dialog that was never registered (or already removed) doesn't raise."""
    dialog_manager = DockableDialogManager()

    dialog = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog.dock)

    dialog_manager.unregister(dialog)  # never registered
    dialog_manager.register(dialog)
    dialog_manager.unregister(dialog)
    dialog_manager.unregister(dialog)  # already removed


def test_destroyed_dock_auto_unregisters_without_raising_on_later_bulk_calls(
    manager: QtAds.CDockManager, settings: FakeSettings, qtbot: QtBot
) -> None:
    """A dialog destroyed without an explicit ``unregister`` call doesn't leave a dead entry.

    **Test steps:**

    * build and register two dialogs
    * delete one dialog's dock and let the event loop process the deletion
    * call save_all
    * verify it doesn't raise and the surviving dialog is still processed
    """
    dialog_manager = DockableDialogManager()

    dialog_a = DockableDialog(manager, "dialog_a", "Dialog A", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_a.dock)
    dialog_manager.register(dialog_a)

    dialog_b = DockableDialog(manager, "dialog_b", "Dialog B", QLabel())
    manager.addDockWidget(QtAds.CenterDockWidgetArea, dialog_b.dock)
    dialog_manager.register(dialog_b)

    dialog_a.dock.deleteLater()
    qtbot.wait(0)

    dialog_manager.save_all(settings)  # type: ignore[arg-type]

    assert settings.value("dockable_dialogs/dialog_b/visible") is not None
