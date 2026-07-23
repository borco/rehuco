"""The UnsavedChangesDialog's own geometry, persisted across restarts (#38)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

GROUP: Final = "unsaved_changes_dialog"
GEOMETRY_KEY: Final = "geometry"


# Mirrors MainWindowSettings's shape exactly (same geometry-blob load/save, different GROUP) --
# kept as a separate class rather than a shared base since the two may diverge as each widget's
# settings grow.
# pylint: disable=duplicate-code
@dataclass
class UnsavedChangesDialogSettings:
    """The unsaved-changes dialog's saved geometry (size/position)."""

    geometry: bytes = field(default=b"")
    """The dialog's ``saveGeometry()`` blob, or empty before any session has been saved."""

    def load(self, settings: QSettings) -> None:
        """Replace the current geometry with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        state = cast(QByteArray, settings.value(GEOMETRY_KEY, QByteArray(), type=QByteArray))
        self.geometry = bytes(state.data())
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the geometry to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(GEOMETRY_KEY, QByteArray(self.geometry))
        settings.endGroup()


# pylint: enable=duplicate-code
