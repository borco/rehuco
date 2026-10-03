"""What the app itself did to files, announced app-wide ([[mounts-and-storage#out-of-band]], #376).

The in-process form of the explicit notification: a rename, a save, a conversion, a screenshot moved or deleted, a
checksum run finishing -- each is announced here, and every view of those files updates **in place** from it,
with no rescan and no model reset. Still no watcher: what changes outside the app reaches the views through a
refresh or a scan, as before.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, Signal
from rehuco_core import Relocation


class ResourceEvents(QObject):
    """The app's one channel for its own file changes; every signal is emitted on the GUI thread.

    **A move is announced as the rename's executed plan** (:class:`~rehuco_core.Relocation`), never as one
    old/new pair: each holder applies its one rule to everything it holds, which is what makes a record nested
    in a renamed folder, or a file-scoped resource's sibling set, follow without anyone enumerating them.

    The ``announce_*`` methods may be called from any thread. Each goes through a :class:`Marshaller` whose
    signal is connected to the public one, so the public signal fires at once when announced on this object's
    thread and is queued onto it otherwise -- a rename listener runs on whichever thread renamed, and nothing
    listening here has to ask which.

    :param parent: optional Qt parent.
    """

    moved: Signal = Signal(object)
    """Emitted with the :class:`~rehuco_core.Relocation` of a rename that landed -- possibly empty, for a rename to
    the name the resource already had."""

    changed: Signal = Signal(object)
    """Emitted with a tuple of the :class:`~pathlib.Path` objects of files the app wrote or replaced: a saved
    record, a converted record and the ``.tc`` it replaced, a checksum record a run rewrote."""

    folder_changed: Signal = Signal(object)
    """Emitted with the :class:`~pathlib.Path` of a folder whose listing the app changed without saying which
    files: screenshots renumbered, deleted, converted or written."""

    class Marshaller(QObject):
        """Carries each announcement onto the events' own thread."""

        moved: Signal = Signal(object)
        changed: Signal = Signal(object)
        folder_changed: Signal = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__marshaller: Final = ResourceEvents.Marshaller(self)
        self.__marshaller.moved.connect(self.moved)
        self.__marshaller.changed.connect(self.changed)
        self.__marshaller.folder_changed.connect(self.folder_changed)

    def announce_moved(self, relocation: Relocation) -> None:
        """Announce a rename -- the :class:`~rehuco_core.RenameCoordinator` listener the window registers.

        :param relocation: the rename's executed plan.
        """
        self.__marshaller.moved.emit(relocation)

    def announce_changed(self, paths: Sequence[Path]) -> None:
        """Announce files the app wrote or replaced.

        :param paths: the files' absolute paths.
        """
        self.__marshaller.changed.emit(tuple(paths))

    def announce_folder_changed(self, directory: Path) -> None:
        """Announce a folder whose listing the app changed.

        :param directory: the folder's absolute path.
        """
        self.__marshaller.folder_changed.emit(directory)
