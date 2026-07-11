"""Persisted visibility/restore-on-start state for a `DockableDialog` (#47)."""

from dataclasses import dataclass
from typing import Final, cast

from PySide6.QtCore import QSettings

VISIBLE_KEY: Final = "visible"
RESTORE_ON_START_KEY: Final = "restore_on_start"


@dataclass
class DockableDialogSettings:
    """Whether a dockable dialog was open, and whether to reopen it automatically on the next start.

    One shared shape for every `DockableDialog` -- unlike `MainWindowSettings`/
    `UnsavedChangesDialogSettings` (each a geometry blob), a dockable dialog's own geometry rides on
    its `CDockManager`'s ``saveState()`` instead of needing its own (it's an ordinary dock, not a
    standalone top-level window), so these two booleans are all that's dialog-specific.
    """

    visible: bool = False
    """Whether the dialog was shown when it was last saved (i.e. at app close)."""

    restore_on_start: bool = False
    """Whether to reopen the dialog automatically next start, if it was :attr:`visible` then."""

    def load(self, settings: QSettings, group: str) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        :param group: this dialog's settings group (its `DockableDialog.object_name`).
        """
        settings.beginGroup(group)
        self.visible = cast(bool, settings.value(VISIBLE_KEY, False, type=bool))
        self.restore_on_start = cast(bool, settings.value(RESTORE_ON_START_KEY, False, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings, group: str) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        :param group: this dialog's settings group (its `DockableDialog.object_name`).
        """
        settings.beginGroup(group)
        settings.setValue(VISIBLE_KEY, self.visible)
        settings.setValue(RESTORE_ON_START_KEY, self.restore_on_start)
        settings.endGroup()
