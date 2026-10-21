"""What the open documents' files look like on disk now, and the watches of the ones under no root (#511,
[[mounts-and-storage#out-of-band]])."""

import threading
from collections.abc import Callable, Collection, Iterable
from pathlib import Path
from typing import Final

from borco_core import Presence, presence_of
from PySide6.QtCore import QObject, Signal
from rehuco_core import DEFAULT_RENAME_COORDINATOR, RenameCoordinator, is_directory_scoped
from rehuco_core.access import ChangeFeed, Records, ResourceKey
from rehuco_core.notify import FileNotifier, WatchedFolder


class HeldFilesWatch(QObject):
    """The disk side of :class:`~.document_registry.DocumentRegistry`: reads the held documents' files when asked, and
    watches the folders of those under no root.

    **A read runs on a daemon thread** ([[appendices.code-conventions#worker-threads]]): a share can block a ``stat``
    for its whole timeout, and nothing may hold up quitting for it. What it read arrives as :attr:`statted`, queued to
    this object's thread; nothing arrives after :meth:`stop`.

    **A held document under no root has its folder watched** -- one :class:`~rehuco_core.notify.FileNotifier` per
    folder, publishing on the app's change feed: everything beneath a directory-scoped record's folder, a file-scoped
    one's folder alone, and a folder covered by another's watch not again, so no watch sits beneath a held document's
    folder that a rename could move.

    :param feed: the app's change feed, where the folder watches publish.
    :param records: what the files are read through, under the rename hold.
    :param coordinator: the rename coordinator the watches answer to.
    :param roots: where the open ``.rehuco``'s roots are; ``None`` watches nothing, for a registry with no window around
        it.
    :param parent: optional Qt parent.
    """

    statted: Signal = Signal(object)
    """Emitted with a ``dict`` of each file's :class:`~pathlib.Path` and its ``(modification time in ns, size)``."""

    missing: Signal = Signal(object)
    """Emitted with a ``dict`` of each file that is not there, its device having answered, and whether its folder is
    gone too (#497). A file on a share that does not answer is in neither signal: nothing is known of it."""

    def __init__(
        self,
        feed: ChangeFeed,
        records: Records,
        coordinator: RenameCoordinator | None,
        roots: Callable[[], Collection[Path]] | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__feed: Final = feed
        self.__records: Final = records
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__roots: Final = roots
        self.__notifiers: Final[dict[WatchedFolder, FileNotifier]] = {}
        self.__stopped: Final = threading.Event()

    def stop(self) -> None:
        """Stop every watch and every read still out: nothing is delivered after."""
        self.__stopped.set()
        for notifier in self.__notifiers.values():
            notifier.stop()
        self.__notifiers.clear()

    def read(self, keys: Iterable[ResourceKey]) -> None:
        """Read the files' modification times and sizes on a daemon thread, for :attr:`statted`.

        :param keys: the files.
        """
        wanted = list(keys)
        if wanted and not self.__stopped.is_set():
            threading.Thread(target=self.__stat, args=(wanted,), name="held-files-read", daemon=True).start()

    def follow(self, held: Collection[ResourceKey]) -> None:
        """Watch exactly the folders of the held documents under no root.

        :param held: the held documents' keys.
        """
        if self.__roots is None or self.__stopped.is_set():
            return
        roots = tuple(ResourceKey(root) for root in self.__roots())
        wanted: dict[ResourceKey, bool] = {}
        for key in held:
            if not any(key.is_at_or_beneath(root) for root in roots):
                wanted[key.parent] = wanted.get(key.parent, False) or is_directory_scoped(key.path)
        folders = {
            WatchedFolder(folder.path, None, recursive)
            for folder, recursive in wanted.items()
            if not any(deep and other != folder and folder.is_at_or_beneath(other) for other, deep in wanted.items())
        }
        for folder in tuple(self.__notifiers):
            if folder not in folders:
                self.__notifiers.pop(folder).stop()
        for folder in folders - self.__notifiers.keys():
            notifier = FileNotifier(folder, self.__feed, HeldFilesWatch.known(folder, held), self.__coordinator)
            self.__notifiers[folder] = notifier  # pylint: disable=unsupported-assignment-operation
            notifier.start()

    @staticmethod
    def known(folder: WatchedFolder, held: Collection[ResourceKey]) -> Callable[[], dict[Path, tuple[int, int] | None]]:
        """What a sweep of a watched folder compares with the disk, should it be polled: the held documents in it, as
        they were when the watch started.

        :param folder: the folder.
        :param held: the held documents' keys.
        :returns: the reader; it expects nothing of a file it has not seen.
        """
        top = ResourceKey(folder.path)
        inside = tuple(
            key.path for key in held if (key.is_at_or_beneath(top) if folder.recursive else key.parent == top)
        )
        return lambda: dict.fromkeys(inside)

    def __stat(self, keys: list[ResourceKey]) -> None:
        """Read the files, each under the rename hold, and deliver them unless stopped (a daemon thread).

        :param keys: the files.
        """
        signatures: dict[Path, tuple[int, int]] = {}
        missing: dict[Path, bool] = {}
        for key in keys:
            signature = self.__records.signature(key)
            if signature is not None:
                signatures[key.path] = signature
                continue
            # judged here, off the GUI thread: a folder on a share that does not answer is not gone, only unknown
            presence = presence_of(key.path.parent)
            if presence is not Presence.OFFLINE:
                missing[key.path] = presence is Presence.GONE
        if self.__stopped.is_set():
            return
        try:
            if signatures:
                self.statted.emit(signatures)
            if missing:
                self.missing.emit(missing)
        except RuntimeError:  # the watch was destroyed while the read was out
            pass
