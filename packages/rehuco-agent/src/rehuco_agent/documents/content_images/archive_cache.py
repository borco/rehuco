"""Open archive handles, kept and read through a lock each (#221), standing aside for a rename (#347).

`zipfile` is the project's only archive reader, and a `ZipFile` is neither cheap to open over a NAS
mount nor safe to read from two threads at once: it seeks one shared file object. This holds a bounded
LRU of open handles and serializes reads per handle, so the decode pool's workers share an archive
without reopening it per thumbnail and without racing on it.

**A browse never blocks a rename** (#347). Kept-open handles are exactly what NTFS refuses to rename a
directory over, so the cache takes part in :class:`~rehuco_core.RenameCoordinator`'s protocol from both
ends: a read runs inside :meth:`~rehuco_core.RenameCoordinator.holding` and closes its handle on the way
out when a rename wants through, and a handle nobody is reading is closed by a yield listener. Every
archive is opened at a tracked :class:`~rehuco_core.ResourceLocation` rather than at the entry's path, so
a read that paused for the rename resumes at the new name instead of failing -- a failure here would be
recorded as *unreadable for good* under a tier-0 key that names no archive, and outlive the rename.

**And an idle cache holds nothing** (#355). Only an in-app rename can ask a handle to close; Explorer, a
second host on the same share, or a future swarm node cannot. So handles are pooled across a burst of
reads and closed once reads stop (:data:`IDLE_CLOSE_SECONDS`), on every platform, since a handle kept
open on an SMB share blocks the server's other clients whatever the reader's own operating system.
"""

import threading
import time
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from io import BufferedReader
from pathlib import Path
from typing import Final

from borco_core import shared_read_open
from rehuco_core import (
    ContentImageEntry,
    RenameCoordinator,
    ResourceLocation,
    readers_must_yield_for_directory_rename,
)

HANDLE_LIMIT: Final = 8
"""How many archives stay open at once. A directory-scoped resource's packs are browsed a few at a
time -- the rows in view span one or two -- and an evicted handle is one reopen away."""

HEADER_BYTES: Final = 64 * 1024
"""How much of a member :meth:`ArchiveCache.read_head` inflates for its header: every recognized
format states its dimensions within the first few hundred bytes, except a JPEG carrying a large EXIF
preview ahead of its frame header, for which 64 KiB is the usual ceiling. A header not found in this
much is read in full by the caller."""

IDLE_CLOSE_SECONDS: Final = 2.0
"""How long after the last read every handle is closed (#355). A browse reads in bursts -- a scroll
through the grid, a step in the lightbox -- and a burst reuses one open handle per archive, which is
what the cache is for. Two seconds spans the gaps inside a burst; past it the next read reopens, at the
cost of one central-directory read per archive."""

READ_ATTEMPTS: Final = 3
"""How often a read looks its handle up again after finding it closed under it: once for an eviction
race, once for a rename that closed it, and the read that then goes through."""


class ArchiveHandle:
    """One open archive: the zip, the file it reads, and the lock every read of it takes (#347).

    The file is kept beside the zip because a `ZipFile` handed a file object does not close it -- and it
    is handed one so that the file is opened through :func:`~borco_core.shared_read_open`, whose
    share-delete lets a file-scoped rename respell the archive itself under an open handle.

    :param file: the open file.
    :param archive: the zip reading it.
    :param must_close: whether this handle has to close before a directory above it can be renamed
        (:func:`~rehuco_core.readers_must_yield_for_directory_rename`).
    """

    def __init__(self, file: BufferedReader, archive: zipfile.ZipFile, must_close: bool) -> None:
        self.file: Final = file
        self.archive: Final = archive
        self.must_close: Final = must_close
        self.lock: Final = threading.Lock()

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has run -- a read that finds it so looks the handle up again."""
        return self.archive.fp is None

    def close(self) -> None:
        """Close the zip and the file under it. Idempotent; the caller holds :attr:`lock`."""
        self.archive.close()
        self.file.close()


class ArchiveCache:  # pylint: disable=too-many-instance-attributes
    """A bounded LRU of open `zipfile.ZipFile` handles, each read under its own lock (#221).

    Every failure -- an offline mount, a truncated zip, a member gone from a re-packed archive -- is
    reported as ``None`` rather than raised: a browse over an unreachable pack paints placeholders and
    says nothing, the same document-level tolerance the enumeration itself has.

    Lock order is the cache's lock, then a handle's, then the coordinator's; the yield listener runs on
    the renaming thread with none of them held and never *waits* on a handle's lock, so the GUI thread a
    rename is asked from is never parked behind a member read.

    The idle close (#355) runs on a daemon timer thread, one at a time and only while reads have
    happened since the last one closed everything -- a cache nobody reads has no timer at all, which is
    what an app left in the tray all session wants.

    :param coordinator: the rename barrier to take part in (#347), or ``None`` for none -- a document
        renamed without one.
    :param limit: how many handles to keep open.
    :param idle_after: how long after the last read every handle is closed, in seconds.
    """

    def __init__(
        self,
        coordinator: RenameCoordinator | None = None,
        limit: int = HANDLE_LIMIT,
        idle_after: float = IDLE_CLOSE_SECONDS,
    ) -> None:
        self.__coordinator: Final = coordinator
        self.__limit: Final = limit
        self.__idle_after: Final = idle_after
        self.__lock: Final = threading.Lock()
        self.__handles: Final[OrderedDict[Path, ArchiveHandle]] = OrderedDict()
        # held strongly for the cache's life: the coordinator tracks weakly, and a location dropped
        # between two reads would stop following the resource
        self.__locations: Final[dict[Path, ResourceLocation]] = {}
        # the idle close's state, all under the cache lock: when the last read finished, the one pending
        # check (if any), and whether the cache has gone away so no check may start again
        self.__last_read = 0.0
        self.__idle_timer: threading.Timer | None = None
        self.__closed = False
        # a stable callable, so removing it finds the one that was added
        self.__on_yield: Final[Callable[[], None]] = self.__close_handles_for_rename
        if coordinator is not None:
            coordinator.add_yield_listener(self.__on_yield)

    def read(self, entry: ContentImageEntry) -> bytes | None:
        """The member's whole bytes.

        :param entry: the member.
        :returns: its bytes, or ``None`` when the archive or the member cannot be read.
        """
        return self.__read(entry, None)

    def read_head(self, entry: ContentImageEntry, limit: int = HEADER_BYTES) -> bytes | None:
        """The member's leading ``limit`` bytes -- a partial inflate, enough for its header.

        :param entry: the member.
        :param limit: how many bytes to inflate.
        :returns: the bytes, or ``None`` when the archive or the member cannot be read.
        """
        return self.__read(entry, limit)

    def release_handles(self) -> None:
        """Close every open handle, still following every archive seen (#347).

        What a path change asks for: the handles may name files that have moved, and the next read
        reopens at the tracked location. The locations are kept, so a read queued before the change
        still finds its archive.
        """
        with self.__lock:
            handles = list(self.__handles.values())
            self.__handles.clear()
        # each under its own lock, so a read in flight on it finishes first
        for handle in handles:
            with handle.lock:
                handle.close()

    def close_idle_handles(self) -> None:
        """Close every handle no reader is on, without waiting for one that is (#355).

        What the idle check calls, and what hiding the Content Images dock asks for: nothing on screen
        will read the archives now. A handle a reader is on is left, and its read reschedules the idle
        check on the way out, so it closes once that reader is done.
        """
        self.__close_unused(lambda _handle: True)

    def close(self) -> None:
        """Close every open handle and leave the rename barrier, for a cache that is going away."""
        with self.__lock:
            self.__closed = True
            timer, self.__idle_timer = self.__idle_timer, None
        if timer is not None:
            timer.cancel()
        if self.__coordinator is not None:
            self.__coordinator.remove_yield_listener(self.__on_yield)
        self.release_handles()

    def __read(self, entry: ContentImageEntry, limit: int | None) -> bytes | None:
        """Read ``limit`` bytes (or all) of ``entry`` through its archive's handle, under that handle's
        lock, inside the rename barrier -- and, however it ends, make sure the idle check is pending.

        :param entry: the member.
        :param limit: how many bytes, or ``None`` for all.
        :returns: the bytes, or ``None`` on any failure.
        """
        try:
            return self.__read_through_handle(entry, limit)
        finally:
            self.__note_read()

    def __read_through_handle(self, entry: ContentImageEntry, limit: int | None) -> bytes | None:
        """The read itself, retried when its handle was closed under it; see :meth:`__read`.

        :param entry: the member.
        :param limit: how many bytes, or ``None`` for all.
        :returns: the bytes, or ``None`` on any failure.
        """
        # a handle can be closed between its lookup and its lock -- evicted, or let go for a rename.
        # Neither is a fact about the member, and a read that fails is recorded as unreadable for good
        # by its callers (a header's size, a thumbnail), so the read looks the handle up again rather
        # than failing. Leaving the hold first is what lets a pending rename finish, and re-entering it
        # is what waits for that
        for _ in range(READ_ATTEMPTS):
            with self.__holding():
                handle = self.__handle(entry.archive)
                if handle is None:
                    return None
                try:
                    with handle.lock:
                        if handle.closed:
                            continue
                        with handle.archive.open(entry.name) as member:
                            return member.read() if limit is None else member.read(limit)
                except OSError, zipfile.BadZipFile, KeyError, RuntimeError, ValueError:
                    # KeyError: the member is not in this archive any more; RuntimeError: encrypted;
                    # ValueError: a member whose compression this zipfile cannot inflate
                    return None
                finally:
                    self.__let_go_if_wanted(entry.archive, handle)
        return None

    def __holding(self) -> AbstractContextManager[None]:
        """The coordinator's hold, or nothing to hold when there is no coordinator."""
        return self.__coordinator.holding() if self.__coordinator is not None else nullcontext()

    def __let_go_if_wanted(self, path: Path, handle: ArchiveHandle) -> None:
        """Close ``handle`` before the hold ends when a rename is waiting for it to.

        Asked **after** the handle's lock is released and still inside the hold. That order is what
        closes the race with :meth:`__close_handles_for_rename`: a listener that fails to take the lock has
        found a reader on it, and that reader asks here only afterwards -- when the flag the listener
        was called for is already up. A handle this read opened while the flag was up is covered the
        same way.

        :param path: the archive, as the cache keys it.
        :param handle: the handle the read used.
        """
        if not handle.must_close or self.__coordinator is None or not self.__coordinator.yield_wanted:
            return
        with self.__lock:
            if self.__handles.get(path) is handle:
                del self.__handles[path]
        with handle.lock:
            handle.close()

    def __close_handles_for_rename(self) -> None:
        """Close every handle no reader is on that stands in a directory rename's way (#347).

        The yield listener, called on the renaming thread -- usually the GUI one -- so it never waits:
        a handle whose lock is taken belongs to a reader inside the hold, which closes it itself on the
        way out (:meth:`__let_go_if_wanted`), and the rename's own bounded wait covers that reader.
        """
        self.__close_unused(lambda handle: handle.must_close)

    def __note_read(self) -> None:
        """Record that a read just finished, and start the idle check unless one is already pending
        (#355)."""
        with self.__lock:
            self.__last_read = time.monotonic()
            if self.__idle_timer is None and not self.__closed:
                self.__start_idle_timer(self.__idle_after)

    def __start_idle_timer(self, delay: float) -> None:
        """Start the one pending idle check; the cache lock is held.

        A daemon thread, so a check still pending at exit never holds the process open.

        :param delay: seconds until it runs.
        """
        timer = threading.Timer(delay, self.__on_idle)
        timer.daemon = True
        self.__idle_timer = timer
        timer.start()

    def __on_idle(self) -> None:
        """The idle check, on its timer thread (#355): once reads have stopped for ``idle_after``,
        close every handle nobody is on; while they have not, check again when they might have.

        A handle a reader was still on is left to the next check, which that reader's own
        :meth:`__note_read` has already started -- or, if it finished between the two, this one starts
        -- so the last handle open always closes eventually.
        """
        with self.__lock:
            self.__idle_timer = None
            if self.__closed:
                return
            remaining = self.__last_read + self.__idle_after - time.monotonic()
            if remaining > 0:
                self.__start_idle_timer(remaining)
                return
        self.close_idle_handles()
        with self.__lock:
            if self.__handles and self.__idle_timer is None and not self.__closed:
                self.__start_idle_timer(self.__idle_after)

    def __close_unused(self, wanted: Callable[[ArchiveHandle], bool]) -> None:
        """Close every ``wanted`` handle no reader is on, without waiting for one that is.

        :param wanted: which handles to close.
        """
        with self.__lock:
            candidates = [(path, handle) for path, handle in self.__handles.items() if wanted(handle)]
        for path, handle in candidates:
            if not handle.lock.acquire(blocking=False):
                continue
            try:
                handle.close()
            finally:
                handle.lock.release()
            with self.__lock:
                if self.__handles.get(path) is handle:
                    del self.__handles[path]

    def __location(self, path: Path) -> ResourceLocation:
        """Where the archive first seen at ``path`` is now; the cache lock is held.

        :param path: the archive's path as its entries name it.
        :returns: its location, tracked by the coordinator when there is one.
        """
        location = self.__locations.get(path)
        if location is None:
            location = self.__coordinator.track(path) if self.__coordinator is not None else ResourceLocation(path)
            self.__locations[path] = location
        return location

    def __handle(self, path: Path) -> ArchiveHandle | None:
        """The open handle for ``path``, opening it (and evicting the least recently used) if needed.

        A closed cache opens nothing (#355): a read still on the pool when the document went away would
        otherwise leave a handle that nothing closes, since :meth:`close` has already run.

        :param path: the archive, as its entries name it.
        :returns: the handle, or ``None`` when the archive cannot be opened, or the cache is closed.
        """
        with self.__lock:
            if self.__closed:
                return None
            if path in self.__handles:
                self.__handles.move_to_end(path)
                return self.__handles[path]
            current = self.__location(path).path
        # opened outside the cache lock: a NAS open can take a while, and it need not stall a read
        # of another archive already open. Kept open past this read on purpose -- the cache is what
        # closes it, on eviction, for a rename, or once reads go idle (#355).
        opened = self.__open(current)
        if opened is None:
            return None
        evicted: list[ArchiveHandle] = []
        with self.__lock:
            if self.__closed:
                # the cache closed while this was opening: nothing would close it later
                opened.close()
                return None
            if path in self.__handles:
                # another thread opened it first: keep theirs, drop ours
                opened.close()
                self.__handles.move_to_end(path)
                return self.__handles[path]
            self.__handles[path] = opened
            while len(self.__handles) > self.__limit:
                evicted.append(self.__handles.popitem(last=False)[1])
        # closed under each handle's own lock, so a read in flight on it finishes first
        for old in evicted:
            with old.lock:
                old.close()
        return opened

    @staticmethod
    def __open(path: Path) -> ArchiveHandle | None:
        """Open the archive at ``path`` without locking it against a rename.

        :param path: where the archive is now.
        :returns: the handle, or ``None`` when it cannot be opened.
        """
        try:
            file = shared_read_open(path)
        except OSError:
            return None
        try:
            archive = zipfile.ZipFile(file)  # pylint: disable=consider-using-with
        except OSError, zipfile.BadZipFile:
            file.close()
            return None
        return ArchiveHandle(file, archive, readers_must_yield_for_directory_rename(path))
