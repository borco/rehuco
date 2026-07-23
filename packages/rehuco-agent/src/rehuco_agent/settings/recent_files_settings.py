"""Most-recently-opened paths for the ``File > Open recents`` menu, newest last (#64)."""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings

MAXIMUM_RECENT_FILES: Final = 10
"""Cap on remembered recent paths. Configurable later in settings (A7); a constant for now."""

GROUP: Final = "recent_files"
PATHS_KEY: Final = "paths"
PATH_KEY: Final = "path"


@dataclass
class RecentFilesSettings:
    """Every path :meth:`~rehuco_agent.main_window.MainWindow.open_file`/``open_folder``/
    ``open_archive`` opened successfully, most-recently-opened last -- an ``OrderedDict`` used as
    an ordered set, the same idiom :class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings`
    uses for its own MRU order.
    """

    paths: Final[OrderedDict[Path, None]] = field(default_factory=OrderedDict)
    """Every remembered path, oldest first."""

    def record(self, path: Path) -> None:
        """Move ``path`` to the most-recently-opened end, dropping the oldest entry past the cap.

        :param path: the resolved path just opened.
        """
        self.paths.pop(path, None)
        self.paths[path] = None  # pylint: disable=unsupported-assignment-operation
        while len(self.paths) > MAXIMUM_RECENT_FILES:
            self.paths.popitem(last=False)

    def newest_first(self) -> list[Path]:
        """Every remembered path, most-recently-opened first."""
        return list(reversed(self.paths))

    def load(self, settings: QSettings) -> None:
        """Replace the current paths with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.paths.clear()
        for index in range(settings.beginReadArray(PATHS_KEY)):
            settings.setArrayIndex(index)
            path = Path(str(settings.value(PATH_KEY, ""))).resolve()
            self.paths[path] = None  # pylint: disable=unsupported-assignment-operation
        settings.endArray()
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the paths to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.beginWriteArray(PATHS_KEY)
        for index, path in enumerate(self.paths):
            settings.setArrayIndex(index)
            settings.setValue(PATH_KEY, path.as_posix())
        settings.endArray()
        settings.endGroup()
