"""The open ``.rehuco`` and the recently opened ones, for the Root Catalog dock (#377)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings

from .recent_files_settings import RecentFilesSettings

GROUP: Final = "rehuco"
CURRENT_PATH_KEY: Final = "current_path"
RECENT_GROUP: Final = f"{GROUP}/recent"
"""Where the recently opened root catalogs live: a :class:`RecentFilesSettings` of their own, nested under this
section's group."""


@dataclass
class RehucoSettings:
    """Which ``.rehuco`` was open when the window closed, and every one opened successfully.

    One file is open at a time, so ``current_path`` is a single path rather than a set -- the thing reopened on
    start. The recents are a :class:`RecentFilesSettings` under this section's group: the same most-recent-last
    list, cap and storage the ``Documents`` menu's recents use, kept in one place.
    """

    current_path: Path | None = None
    """The ``.rehuco`` open at the last save, or ``None`` when none was."""

    recent: Final[RecentFilesSettings] = field(default_factory=lambda: RecentFilesSettings(group=RECENT_GROUP))
    """The recently opened root catalogs."""

    def record(self, path: Path) -> None:
        """Move ``path`` to the newest end of the recents, dropping the oldest entry past the cap.

        :param path: the resolved path just opened.
        """
        self.recent.record(path)

    def newest_first(self) -> list[Path]:
        """Every remembered path, most recently opened first."""
        return self.recent.newest_first()

    def load(self, settings: QSettings) -> None:
        """Replace the current state with what is in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        current = str(settings.value(CURRENT_PATH_KEY, ""))
        settings.endGroup()
        self.current_path = Path(current).resolve() if current else None
        self.recent.load(settings)

    def save(self, settings: QSettings) -> None:
        """Save the state to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(CURRENT_PATH_KEY, self.current_path.as_posix() if self.current_path is not None else "")
        settings.endGroup()
        self.recent.save(settings)
