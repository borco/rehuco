"""Turns what the backends saw into the change feed's events: debounced, coalesced, a rename's pairs as one plan (#511,
[[mounts-and-storage#out-of-band]]).

A burst on disk is a burst of observations -- a save is a temporary file written, flushed and renamed over the
record; a screenshot reorder parks every file under a temporary name and brings it back. Published one by one, each
would reach every view as its own update. Held until the folder is quiet for :data:`QUIET_SECONDS` -- but never past
:data:`LONGEST_WAIT_SECONDS`, so a steady stream still arrives -- they reach the feed as what they add up to.
"""

import logging
import queue
import re
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final
from uuid import UUID

from ..access import Changed, ChangeEvent, ChangeFeed, FolderChanged, KeyRelocation, Moved, ResourceKey, RootStale
from ..record_file_lock import is_lock_name
from ..resource_scoping import is_record_name
from .raw_change import RawChange, RawChangeKind

LOG: Final = logging.getLogger(__name__)

QUIET_SECONDS: Final = 0.25
"""How long the folder must be still before what was seen is published."""

LONGEST_WAIT_SECONDS: Final = 1.0
"""The longest anything waits to be published, however busy the folder stays."""

POLL_SECONDS: Final = 0.5
"""How often the idle thread looks up to see whether it was stopped."""

ATOMIC_WRITE_NAME: Final = re.compile(r"^\.?(?P<target>.+)\.[a-z0-9_]{8}\.tmp$")
"""The temporary sibling :func:`~borco_core.atomic_write` writes before it replaces the file: ``<name>.<random>.tmp``,
the random part being the eight characters ``tempfile.mkstemp`` draws -- so a user's own ``a.b.tmp`` is no save. A
leading dot is still accepted: the shape builds before #526 gave, whose leftovers a crash may have kept.
"""


class ChangeCoalescer:
    """Collects a watched folder's :class:`~rehuco_core.notify.RawChange` observations from any thread and publishes
    them on a feed from its own daemon thread, in batches.

    What a batch adds up to (:meth:`events_of`) is published in a fixed order: one :class:`~rehuco_core.access.Moved`,
    then one :class:`~rehuco_core.access.Changed`, then a :class:`~rehuco_core.access.FolderChanged` per folder whose
    listing changed.

    :param feed: where to publish.
    :param folder: the watched folder.
    :param root_id: the root it is, or ``None`` for a folder watched for an open document under no root.
    """

    class Tally:
        """What a batch adds up to so far: the rename plan, the files changed, and which entries were there before
        the batch and are there after it."""

        def __init__(self) -> None:
            self.pairs: Final[list[tuple[ResourceKey, ResourceKey]]] = []
            self.changed: Final[dict[ResourceKey, None]] = {}
            self.__before: Final[dict[ResourceKey, bool]] = {}
            self.__after: Final[dict[ResourceKey, bool]] = {}

        def presence(self, key: ResourceKey, there: bool, directory: bool) -> None:
            """An entry appeared or went.

            :param key: the entry.
            :param there: whether it is there now.
            :param directory: whether it is a folder; one that appeared is no file changed.
            """
            self.__before.setdefault(key, not there)
            self.__after[key] = there
            if not directory or not there:
                self.changed[key] = None

        def saved(self, key: ResourceKey) -> None:
            """A file was replaced by an atomic save -- or written for the first time by one.

            :param key: the file.
            """
            self.changed[key] = None
            self.__before.setdefault(key, False)
            self.__after[key] = True

        def moved(self, source: ResourceKey, destination: ResourceKey, directory: bool) -> None:
            """An entry was renamed: a move, unless a file stopped or started being a record by it.

            :param source: where it was.
            :param destination: where it went.
            :param directory: whether it is a folder.
            """
            if not directory and is_record_name(source.name) != is_record_name(destination.name):
                self.presence(source, False, False)
                self.presence(destination, True, False)
            else:
                ChangeCoalescer.compose(self.pairs, source, destination)

        def events(self) -> list[ChangeEvent]:
            """What the batch adds up to, in the order to publish it.

            :returns: the events.
            """
            listings = dict.fromkeys(key.parent for key, there in self.__after.items() if there != self.__before[key])
            events: list[ChangeEvent] = []
            if self.pairs:
                events.append(Moved(KeyRelocation(tuple(self.pairs))))
            if self.changed:
                events.append(Changed(tuple(self.changed)))
            events.extend(FolderChanged(listing) for listing in listings)
            return events

    def __init__(self, feed: ChangeFeed, folder: Path, root_id: UUID | None) -> None:
        self.__feed: Final = feed
        self.__folder: Final = folder
        self.__root_id: Final = root_id
        self.__queue: Final = queue.SimpleQueue[RawChange]()
        self.__stopped: Final = threading.Event()
        self.__started = False

    def start(self) -> None:
        """Begin publishing. A no-op the second time."""
        if self.__started:
            return
        self.__started = True
        threading.Thread(target=self.__run, name=f"change-coalescer {self.__folder}", daemon=True).start()

    def stop(self) -> None:
        """Publish nothing more; what is still held is dropped."""
        self.__stopped.set()

    def push(self, change: RawChange) -> None:
        """Hold one observation for the next batch -- from any thread.

        :param change: what was seen.
        """
        if not self.__stopped.is_set():
            self.__queue.put(change)

    @classmethod
    def events_of(cls, batch: Sequence[RawChange], folder: Path, root_id: UUID | None) -> list[ChangeEvent]:
        """What a batch of observations adds up to.

        - **An overflow** means more changed than was seen: the root is :class:`~rehuco_core.access.RootStale`, or, for
          a folder with no root, the whole folder has changed -- published after what *was* seen, which still holds.
        - **A rename** joins the batch's plan; one that continues an earlier pair -- ``A -> B`` then ``B -> C`` --
          rewrites it (:meth:`compose`), so a reorder that parked every screenshot under a temporary name arrives as
          the reorder.
        - **A file renamed into or out of being a record is no rename of it**: ``info.tc`` renamed to ``info.tc.orig``
          -- a conversion keeping its backup -- is the record gone and an unrelated file created, never the record
          moved to a name that no holder can open. Both ends are changed, and their folder's listing.
        - **An atomic save** -- its temporary sibling renamed over the file -- is that file changed; the temporary
          sibling's own creation and writes are no one's business.
        - **A record's lock file** (#512) is no one's business either: taken and removed by every save, it changes
          nothing anyone holds.
        - **A file created, written or deleted** is changed; a deleted folder is itself changed: whoever holds records
          beneath it looks them up.
        - **A folder's listing changed** when an entry in it is there at the end of the batch and was not at the start,
          or the other way round. A file replaced -- NTFS reports an atomic save as the file deleted, then the
          temporary sibling renamed onto its name -- is there at both ends, so a save relists nothing.

        :param batch: the observations, in the order seen.
        :param folder: the watched folder.
        :param root_id: its root, or ``None``.
        :returns: the events, in the order to publish them.
        """
        tally = ChangeCoalescer.Tally()
        for change in batch:
            if change.kind is not RawChangeKind.OVERFLOW and is_lock_name(change.path.name):
                continue
            key = ResourceKey(change.path)
            temporary = cls.is_atomic_write_temporary(change.path)
            match change.kind:
                case RawChangeKind.MOVED:
                    assert change.destination is not None  # nosec  # B101: a move always names where it went
                    if not temporary:
                        tally.moved(key, ResourceKey(change.destination), change.is_directory)
                    elif not cls.is_atomic_write_temporary(change.destination):
                        tally.saved(ResourceKey(change.destination))
                case RawChangeKind.CREATED | RawChangeKind.DELETED if not temporary:
                    tally.presence(key, change.kind is RawChangeKind.CREATED, change.is_directory)
                case RawChangeKind.MODIFIED if not temporary and not change.is_directory:
                    tally.changed[key] = None
                case _:
                    pass
        events = tally.events()
        if any(change.kind is RawChangeKind.OVERFLOW for change in batch):
            events.append(RootStale(root_id) if root_id is not None else FolderChanged(ResourceKey(folder)))
        return events

    @staticmethod
    def compose(pairs: list[tuple[ResourceKey, ResourceKey]], source: ResourceKey, destination: ResourceKey) -> None:
        """Add one rename to a plan whose keys are read *as they were before the plan ran*.

        :class:`~rehuco_core.access.KeyRelocation` maps a key by its first matching pair, so a rename of what an
        earlier pair already moved is folded into that pair: one of its destination continues it (``A -> B`` and
        ``B -> C`` make ``A -> C``); one beneath its destination gets a pair of its own, spelled from the earlier
        pair's source and put before it, so it matches first.

        :param pairs: the plan so far; changed in place.
        :param source: the renamed entry, as the disk spelled it when renamed.
        :param destination: where it went.
        """
        for index, (earlier_source, earlier_destination) in enumerate(pairs):
            if source == earlier_destination:
                pairs[index] = (earlier_source, destination)
                return
            if source.is_at_or_beneath(earlier_destination):
                tail = source.parts[len(earlier_destination.parts) :]
                pairs.insert(index, (earlier_source.joinpath(*tail), destination))
                return
        pairs.append((source, destination))

    @staticmethod
    def is_atomic_write_temporary(path: Path) -> bool:
        """Whether ``path`` is the temporary sibling an atomic write replaces its file with.

        :param path: any path.
        :returns: whether its name has :data:`ATOMIC_WRITE_NAME`'s shape.
        """
        return ATOMIC_WRITE_NAME.match(path.name) is not None

    def __run(self) -> None:
        """Wait for a first observation, gather until the folder is quiet, publish; until stopped."""
        while not self.__stopped.is_set():
            try:
                first = self.__queue.get(timeout=POLL_SECONDS)
            except queue.Empty:
                continue
            batch = [first]
            deadline = time.monotonic() + LONGEST_WAIT_SECONDS
            while (remaining := min(QUIET_SECONDS, deadline - time.monotonic())) > 0:
                try:
                    batch.append(self.__queue.get(timeout=remaining))
                except queue.Empty:
                    break
            try:
                events = self.events_of(batch, self.__folder, self.__root_id)
            # a batch that cannot be read must not end the watch: what it said is lost, so everything is read again
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.exception(
                    "Could not make sense of %d changes under %s; reading it all again.", len(batch), self.__folder
                )
                events = self.events_of(
                    [RawChange(RawChangeKind.OVERFLOW, self.__folder)], self.__folder, self.__root_id
                )
            for event in events:
                if self.__stopped.is_set():
                    return
                self.__feed.publish(event)
