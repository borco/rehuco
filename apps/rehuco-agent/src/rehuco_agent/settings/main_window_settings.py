"""MainWindow's own geometry, persisted across restarts ([[implementation-plan]] A2.1/#21)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

GROUP: Final = "main_window"
GEOMETRY_KEY: Final = "geometry"


# Mirrors UnsavedChangesDialogSettings's shape exactly (same geometry-blob load/save, different
# GROUP) -- kept as a separate class rather than a shared base since the two may diverge as each
# widget's settings grow (e.g. #38's dialog vs. this window).
# pylint: disable=duplicate-code
@dataclass
class MainWindowSettings:
    """The main window's saved geometry (size/position)."""

    geometry: bytes = field(default=b"")
    """The window's ``saveGeometry()`` blob, or empty before any session has been saved."""

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
