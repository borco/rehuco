"""Bulk save/restore for every registered `DockableDialog`."""

from typing import Final

from PySide6.QtCore import QSettings
from shiboken6 import isValid

from .dockable_dialog import DockableDialog
from .dockable_dialog_settings import DockableDialogSettings

GROUP_PREFIX: Final = "dockable_dialogs"


class DockableDialogManager:
    """Saves/restores every registered `DockableDialog`'s settings in two calls, instead of a
    show/finish method pair per dialog type.
    """

    def __init__(self) -> None:
        self.__dialogs: Final[list[DockableDialog]] = []

    def register(self, dialog: DockableDialog) -> None:
        """Track ``dialog`` for :meth:`save_all`/:meth:`restore_all`.

        A no-op if ``dialog`` is already registered. Auto-unregisters when its dock is destroyed, so
        a dialog torn down without an explicit :meth:`unregister` call can't leave a dead entry
        behind for the bulk loops to trip over.

        :param dialog: the dialog to register; its :attr:`~DockableDialog.object_name` becomes its
            settings group.
        """
        if dialog in self.__dialogs:
            return
        self.__dialogs.append(dialog)
        dialog.dock.destroyed.connect(lambda: self.unregister(dialog))

    def unregister(self, dialog: DockableDialog) -> None:
        """Stop tracking ``dialog``. A no-op if it isn't registered.

        :param dialog: the dialog to drop from :meth:`save_all`/:meth:`restore_all`.
        """
        if dialog in self.__dialogs:
            self.__dialogs.remove(dialog)

    def __live_dialogs(self) -> list[DockableDialog]:
        """The registered dialogs whose docks are still alive, dropping any dead entry found.

        The ``destroyed`` auto-unregister covers ordinary teardown, but a dock destroyed with its
        signal delivery severed (or a bulk call racing a ``deleteLater``) can still leave a wrapper
        whose C++ dock is already gone -- touching it raises ``RuntimeError``, so the bulk loops
        iterate this snapshot instead, which skips (and unregisters) such entries.

        :returns: the still-live dialogs, in registration order.
        """
        for dialog in [dialog for dialog in self.__dialogs if not isValid(dialog.dock)]:
            self.unregister(dialog)
        return list(self.__dialogs)

    def enforce_restore_on_start(self) -> None:
        """Close every registered dialog whose "Restore on start" is unchecked.

        Call before capturing the owning ``CDockManager``'s ``saveState()`` for persistence -- see
        :meth:`~borco_pyside.dialogs.dockable_dialog.DockableDialog.enforce_restore_on_start`.
        """
        for dialog in self.__live_dialogs():
            dialog.enforce_restore_on_start()

    def save_all(self, settings: QSettings) -> None:
        """Persist every registered dialog's current settings.

        :param settings: the ``QSettings`` to write to.
        """
        for dialog in self.__live_dialogs():
            dialog.save_settings().save(settings, f"{GROUP_PREFIX}/{dialog.object_name}")

    def restore_all(self, settings: QSettings) -> None:
        """Apply every registered dialog's persisted settings (restore-on-start + visibility).

        :param settings: the ``QSettings`` to read from.
        """
        for dialog in self.__live_dialogs():
            saved = DockableDialogSettings()
            saved.load(settings, f"{GROUP_PREFIX}/{dialog.object_name}")
            dialog.restore_settings(saved)
