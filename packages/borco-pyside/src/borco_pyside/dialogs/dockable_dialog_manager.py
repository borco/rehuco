"""Bulk save/restore for every registered `DockableDialog` (#47)."""

from typing import Final

from PySide6.QtCore import QSettings

from borco_pyside.dialogs.dockable_dialog import DockableDialog
from borco_pyside.dialogs.dockable_dialog_settings import DockableDialogSettings

GROUP_PREFIX: Final = "dockable_dialogs"


class DockableDialogManager:
    """Saves/restores every registered `DockableDialog`'s settings in two calls, instead of a
    show/finish method pair per dialog type.
    """

    def __init__(self) -> None:
        self.__dialogs: Final[list[DockableDialog]] = []

    def register(self, dialog: DockableDialog) -> None:
        """Track ``dialog`` for :meth:`save_all`/:meth:`restore_all`.

        :param dialog: the dialog to register; its :attr:`~DockableDialog.object_name` becomes its
            settings group.
        """
        self.__dialogs.append(dialog)

    def save_all(self, settings: QSettings) -> None:
        """Persist every registered dialog's current settings.

        :param settings: the ``QSettings`` to write to.
        """
        for dialog in self.__dialogs:
            dialog.save_settings().save(settings, f"{GROUP_PREFIX}/{dialog.object_name}")

    def restore_all(self, settings: QSettings) -> None:
        """Apply every registered dialog's persisted settings (restore-on-start + visibility).

        :param settings: the ``QSettings`` to read from.
        """
        for dialog in self.__dialogs:
            saved = DockableDialogSettings()
            saved.load(settings, f"{GROUP_PREFIX}/{dialog.object_name}")
            dialog.restore_settings(saved)
