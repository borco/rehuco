"""What `Import Legacy Catalog…` remembers between runs: recent roots and the wizard's own geometry
(#192)."""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

GROUP: Final = "import_legacy_catalog_wizard"
GEOMETRY_KEY: Final = "geometry"
ROOTS_KEY: Final = "recent_roots"
ROOT_KEY: Final = "root"

MAXIMUM_RECENT_ROOTS: Final = 10
"""Cap on remembered roots, matching :data:`~rehuco_agent.settings.recent_files_settings.MAXIMUM_RECENT_FILES`."""


@dataclass
class ImportLegacyCatalogWizardSettings:
    """The wizard's saved geometry and the folders it has been pointed at before, newest last -- the
    same ``OrderedDict``-as-ordered-set idiom
    :class:`~rehuco_agent.settings.recent_files_settings.RecentFilesSettings` uses for its own MRU list.

    Owned by the wizard itself, loaded and saved directly rather than through a process-wide shared
    instance (unlike e.g. `~rehuco_agent.settings.checksum_settings.ChecksumSettings`): the same shape
    `~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialogSettings` follows, since nothing
    else needs to read or write this while a wizard is open -- only one is ever on screen at a time.
    """

    geometry: bytes = field(default=b"")
    """The dialog's ``saveGeometry()`` blob, or empty before any session has been saved."""

    recent_roots: Final[OrderedDict[Path, None]] = field(default_factory=OrderedDict)
    """Every root the wizard has scanned, oldest first."""

    def record_root(self, root: Path) -> None:
        """Move ``root`` to the most-recently-scanned end, dropping the oldest entry past the cap.

        :param root: the resolved root the wizard just scanned.
        """
        self.recent_roots.pop(root, None)
        self.recent_roots[root] = None  # pylint: disable=unsupported-assignment-operation
        while len(self.recent_roots) > MAXIMUM_RECENT_ROOTS:
            self.recent_roots.popitem(last=False)

    def newest_roots_first(self) -> list[Path]:
        """Every remembered root, most-recently-scanned first."""
        return list(reversed(self.recent_roots))

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        state = cast(QByteArray, settings.value(GEOMETRY_KEY, QByteArray(), type=QByteArray))
        self.geometry = bytes(state.data())
        self.recent_roots.clear()
        for index in range(settings.beginReadArray(ROOTS_KEY)):
            settings.setArrayIndex(index)
            root = Path(str(settings.value(ROOT_KEY, ""))).resolve()
            self.recent_roots[root] = None  # pylint: disable=unsupported-assignment-operation
        settings.endArray()
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(GEOMETRY_KEY, QByteArray(self.geometry))
        settings.beginWriteArray(ROOTS_KEY)
        for index, root in enumerate(self.recent_roots):
            settings.setArrayIndex(index)
            settings.setValue(ROOT_KEY, root.as_posix())
        settings.endArray()
        settings.endGroup()
