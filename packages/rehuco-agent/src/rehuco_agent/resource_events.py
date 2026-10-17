"""What changed under the resources the app reaches, announced app-wide as Qt signals
([[mounts-and-storage#out-of-band]], #376, #414).

The Qt side of the change feed ([[nodes#access-seam]]): a rename, a save, a conversion, a screenshot moved or deleted,
a checksum run finishing -- each is published on a :class:`~rehuco_core.access.ChangeFeed`, and every view of those
resources updates **in place** from the signal this adapter turns it into, with no rescan and no model reset.
Everything is named by :class:`~rehuco_core.access.ResourceKey`. Still no watcher: what changes outside the app reaches
the views through a refresh or a scan, as before.
"""

from collections.abc import Sequence
from typing import Final, assert_never

from PySide6.QtCore import QObject, Signal
from rehuco_core import Relocation
from rehuco_core.access import (
    Changed,
    ChangeEvent,
    ChangeFeed,
    FolderChanged,
    KeyRelocation,
    Moved,
    ResourceKey,
    RootStale,
)


class ResourceEvents(QObject):
    """The app's one channel for changes to the resources it reaches; every signal is emitted on the GUI thread.

    **A move is announced as the rename's executed plan** (:class:`~rehuco_core.access.KeyRelocation`), never as one
    old/new pair: each holder applies its one rule to everything it holds, which is what makes a record nested
    in a renamed folder, or a file-scoped resource's sibling set, follow without anyone enumerating them.

    The events arrive from the feed on whichever thread published them -- a rename listener runs on the thread that
    renamed -- and go through a :class:`Marshaller` whose signals are connected to the public ones, so a public signal
    fires at once when published on this object's thread and is queued onto it otherwise.

    :param changes: the feed to adapt; a private one when not given, for a holder with no window around it.
    :param parent: optional Qt parent.
    """

    moved: Signal = Signal(object)
    """Emitted with the :class:`~rehuco_core.access.KeyRelocation` of a rename that landed -- possibly empty, for a
    rename to the name the resource already had."""

    changed: Signal = Signal(object)
    """Emitted with a tuple of the keys of files written or replaced: a saved record, a converted record and the
    ``.tc`` it replaced, a checksum record a run rewrote."""

    folder_changed: Signal = Signal(object)
    """Emitted with the key of a folder whose listing changed without saying which files: screenshots renumbered,
    deleted, converted or written."""

    root_stale: Signal = Signal(object)
    """Emitted with the :class:`~uuid.UUID` of a root nothing held about can be trusted any more."""

    accessed: Signal = Signal(object)
    """Emitted with a tuple of the keys of records the app is about to show -- a document just opened -- so the
    catalog cache can be checked against them (verify-on-access, #487). Nothing was written, so it is no change and
    never goes through the feed."""

    class Marshaller(QObject):
        """Carries each announcement onto the events' own thread."""

        moved: Signal = Signal(object)
        changed: Signal = Signal(object)
        folder_changed: Signal = Signal(object)
        root_stale: Signal = Signal(object)
        accessed: Signal = Signal(object)

    def __init__(self, changes: ChangeFeed | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__changes: Final = changes if changes is not None else ChangeFeed()
        self.__marshaller: Final = ResourceEvents.Marshaller(self)
        self.__marshaller.moved.connect(self.moved)
        self.__marshaller.changed.connect(self.changed)
        self.__marshaller.folder_changed.connect(self.folder_changed)
        self.__marshaller.root_stale.connect(self.root_stale)
        self.__marshaller.accessed.connect(self.accessed)
        self.__changes.add_listener(self.__on_change)

    @property
    def changes(self) -> ChangeFeed:
        """The feed these signals adapt."""
        return self.__changes

    def detach(self) -> None:
        """Stop adapting the feed, before this object goes: the feed outlives it, and would call into a deleted one."""
        self.__changes.remove_listener(self.__on_change)

    def announce_moved(self, relocation: Relocation) -> None:
        """Publish a rename this machine ran -- the :class:`~rehuco_core.RenameCoordinator` listener the window
        registers.

        :param relocation: the rename's executed plan.
        """
        self.__changes.publish(Moved(KeyRelocation.from_local(relocation)))

    def announce_changed(self, keys: Sequence[ResourceKey]) -> None:
        """Publish files the app wrote or replaced.

        :param keys: the files' keys.
        """
        self.__changes.publish(Changed(tuple(keys)))

    def announce_folder_changed(self, key: ResourceKey) -> None:
        """Publish a folder whose listing the app changed.

        :param key: the folder's key.
        """
        self.__changes.publish(FolderChanged(key))

    def announce_accessed(self, keys: Sequence[ResourceKey]) -> None:
        """Announce records the app is opening, for the cache to verify them (#487).

        :param keys: the records' keys.
        """
        self.__marshaller.accessed.emit(tuple(keys))

    def __on_change(self, event: ChangeEvent) -> None:
        """Hand one published event to its signal, on the publisher's thread.

        :param event: what changed.
        """
        match event:
            case Moved(relocation):
                self.__marshaller.moved.emit(relocation)
            case Changed(keys):
                self.__marshaller.changed.emit(keys)
            case FolderChanged(key):
                self.__marshaller.folder_changed.emit(key)
            case RootStale(root_id):
                self.__marshaller.root_stale.emit(root_id)
            case _:
                assert_never(event)
