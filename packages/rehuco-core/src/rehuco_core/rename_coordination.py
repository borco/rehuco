"""Renaming a resource out from under the jobs reading it (#241).

**A rename never waits for a job.** A checksum sweep over a large collection runs for minutes or hours;
if renaming a folder meant waiting for it, a busy catalog would be one nobody could reorganize -- and
with several people using the app, potentially never. So the wait goes the other way round: the rename
asks the readers to let go, they do so at the next chunk boundary, and the rename runs. Measured at
**6.8 to 7.6 ms** per interruption, because the wait is bounded by one chunk read rather than by the
length of the job.

Needed at all because of what an operating system will and will not allow. A reader opened through
:func:`~borco_core.shared_read_open` shares every right it has, so renaming or deleting *the file it is
reading* already works -- but NTFS refuses to rename a **directory** while any handle is open anywhere
beneath it, whatever share mode that handle asked for, and a directory-scoped ``info.rehu``
([[data-model#resource-scoping]]) is the common case. That refusal is not a flag anyone forgot to pass;
it is a rule about the subtree, and the only way through it is for the reader to let go. Whether it must
is :func:`~rehuco_core.readers_must_yield_for_directory_rename`'s to say, so a backend that does not
lock costs its readers nothing.

**A job holds a** :class:`ResourceLocation`\\ **, never a bare** ``Path``. That is what makes "the job
continues at the new location" true rather than aspirational, and it holds across any number of renames
during one job -- the coordinator rewrites every tracked path through
:meth:`~rehuco_core.RehuRenamer.relocate`, from the plan the rename actually executed.

**Honest limit:** another machine renaming over a network share cannot ask our readers to yield, so a
cross-host rename can still be refused. Mitigated rather than solved -- the window in which a handle is
held is one chunk, and share-delete makes file-level operations succeed regardless. Coordinating across
hosts is swarm-era, and belongs with the rename being addressed by resource UUID rather than by path
([[mounts-and-storage#uuid-not-paths]]).
"""

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Condition, RLock
from typing import Final
from weakref import ReferenceType, ref

from .rehu_rename import RehuRenamer

LOG: Final = logging.getLogger(__name__)

DEFAULT_RENAME_YIELD_TIMEOUT: Final = 2.0
"""How long :meth:`RenameCoordinator.rename` waits for readers to let go, in seconds.

Measured need is ~7 ms -- one chunk read -- so this is a ceiling on a reader that is wedged rather than
a budget anyone spends. **Shorter than the task queue's own five-second shutdown wait, deliberately**: a
rename is asked for by someone looking at the window, and a window that stops repainting for five
seconds is one Windows paints its *Not Responding* ghost over. Two seconds stays under that, and a
reader that has not answered by then has something wrong with it that waiting longer will not fix."""


class RenameYieldTimeout(OSError):
    """A rename gave up waiting for readers to release the files beneath it (#241).

    An ``OSError`` subclass, like :class:`~rehuco_core.PartialRenameError`, so a caller that treats
    every rename failure alike still catches it -- what a surface does with this is what it does with a
    collision or a vanished file: report it and leave the name as it was. Nothing on disk was touched.
    """


class ResourceLocation:
    """One path inside a resource, kept current across every rename that moves it (#241).

    What a job holds instead of a ``Path``: the file it is reading, the record it will write. Re-read it
    at each step rather than caching it, and the job survives a rename it never had to know about.

    Tracks **any** path within the resource, not only the ``.rehu``, because a file-scoped rename
    respells the content files too (``foo.zip`` becomes ``bar.zip``) -- a location that only followed
    the record would leave every other job pointed at a name that no longer exists.

    Read and written from two threads at once -- a worker reading it between chunks, the coordinator
    rewriting it mid-rename -- so both go through a lock. ``Path`` is immutable, so what the lock
    protects is the *reference*, and a reader either sees the whole old path or the whole new one.

    :param path: where this location starts.
    """

    def __init__(self, path: Path) -> None:
        self.__lock: Final = RLock()
        self.__path = path

    @property
    def path(self) -> Path:
        """Where this location is **now**.

        :returns: the current path, which may differ from the one this location was created with.
        """
        with self.__lock:
            return self.__path

    def moved_to(self, path: Path) -> None:
        """Record that this location is now at ``path``.

        :class:`RenameCoordinator`'s to call, and nobody else's: it is only true when a rename has
        actually run, and the coordinator is what knows that. Public because Python has no way to say
        *this class and no other*, which is what this sentence is for.

        :param path: the location's new path.
        """
        with self.__lock:
            self.__path = path


class RenameCoordinator:
    """Runs a rename against the readers working inside the resource (#241).

    The protocol, from a reader's side: hold a handle only inside :meth:`holding`, check
    :attr:`yield_wanted` between chunks, and when it says so, leave the block -- closing whatever is
    open -- and come back through :meth:`holding`, which returns once the rename is done. From the
    rename's side: raise the flag, wait for the last holder to leave, rename, rewrite every tracked
    location, lower the flag.

    **Deliberately not** :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint`. A checkpoint *raises to
    stop*; a yield *pauses and continues*. Folding the two together would make a rename look to a job
    like a cancellation, which is the one thing it must not look like.

    **A counted barrier rather than a single flag**, because the count is the same amount of code and is
    already right for the parallel lane [[appendices.task-queue#serial]] leaves the door open to. Today's
    queue is serial, so there is at most one reader and the count is never above one; nothing here needs
    to change if that stops being true.

    **One rename at a time**, held by a lock outside the barrier. Two renames sharing one flag is not a
    theoretical worry: the second would lower it while the first was still mid-rename, releasing every
    reader onto a directory about to move -- exactly the refusal this exists to avoid. Today the GUI
    thread serializes renames by being blocked in one, but that is an accident of there being a single
    caller, and it stops being true the moment a rename arrives from anywhere else.

    Readers are **not** protected against starvation: a stream of renames could keep one out
    indefinitely. Renames are asked for by a person clicking a name, so the arrival rate is human;
    should that ever stop being so, this is the sentence to come back to.
    """

    def __init__(self) -> None:
        self.__condition: Final = Condition(RLock())
        self.__renaming: Final = RLock()
        self.__yield_wanted = False
        self.__holders = 0
        self.__locations: list[ReferenceType[ResourceLocation]] = []
        self.__listeners: list[Callable[[], None]] = []

    def track(self, path: Path) -> ResourceLocation:
        """Start following ``path`` across renames.

        Held **weakly**: a job that has finished stops being anyone's concern without having to say so,
        and a coordinator that lives as long as the app would otherwise accumulate one entry per file
        ever read. The caller's own reference is what keeps a location alive, which is the same thing as
        saying a location matters exactly as long as the job holding it does.

        :param path: the file or directory to follow.
        :returns: a location starting at ``path``.
        """
        location = ResourceLocation(path)
        with self.__condition:
            self.__locations.append(ref(location))
        return location

    def add_rename_listener(self, listener: Callable[[], None]) -> None:
        """Be told, after the fact, that a rename moved something.

        A plain callable rather than a
        :class:`~rehuco_core.tasks.TaskQueueListener`-style protocol, because there is one event and it
        carries nothing: whoever cares re-reads what they hold. It is how the task queue learns to
        re-read its jobs' ``source`` without core growing a dependency in either direction -- the app
        wires the two together.

        :param listener: called with no arguments once a rename has landed and every tracked location
            has been rewritten. Called on whichever thread asked for the rename, with no lock held.
        """
        with self.__condition:
            self.__listeners.append(listener)

    @property
    def yield_wanted(self) -> bool:
        """Whether a rename is waiting for readers to let go.

        What a reader checks between chunks. Cheap by construction -- one lock and one boolean -- since
        it is asked once per chunk for the whole length of a job.

        :returns: whether whoever holds a handle should close it and leave :meth:`holding`.
        """
        with self.__condition:
            return self.__yield_wanted

    @contextmanager
    def holding(self) -> Generator[None]:
        """Hold a handle inside this block, and nowhere else.

        Entering waits for any pending rename to finish, so a reader that has just let go comes back
        only once the resource has stopped moving -- and then re-reads its
        :class:`ResourceLocation`, which by that point says where the file went.

        Brackets **handle ownership**, not one chunk read: it is the open handle that a directory rename
        collides with, so a reader entered here once and reading a hundred chunks is holding for all of
        them. Leaving the block is the acknowledgement the rename is waiting for.

        **The entry wait is unbounded**, unlike the rename's own. It ends when the flag comes down,
        which :meth:`rename` guarantees in a ``finally`` -- so the only way to sit here forever is for
        the rename itself to be stuck inside the filesystem call, e.g. a mount that has gone away
        mid-operation ([[mounts-and-storage#offline-mounts]]). A reader parked here cannot reach its
        own :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint`, so a cancel would not bite until the
        queue's daemon-thread shutdown gives up on it. Left unbounded deliberately: the flag is up for
        the milliseconds a local rename takes, and a reader that gave up waiting would have nothing
        useful to do but ask again.

        :yields: nothing; the block does the reading.
        """
        with self.__condition:
            self.__condition.wait_for(lambda: not self.__yield_wanted)
            self.__holders += 1
        try:
            yield
        finally:
            with self.__condition:
                self.__holders -= 1
                self.__condition.notify_all()

    def rename(self, path: Path, new_name: str, timeout: float = DEFAULT_RENAME_YIELD_TIMEOUT) -> Path:
        """Rename the resource at ``path``, asking any readers beneath it to let go first.

        Blocks its caller for as long as the readers take -- ~7 ms in practice, one chunk read -- which
        is why the ceiling matters and why it is short (:data:`DEFAULT_RENAME_YIELD_TIMEOUT`).

        Every tracked location is rewritten **before** the flag is lowered, so a reader coming back
        through :meth:`holding` never sees a resource that has moved but locations that have not.

        A rename to the name the resource already has still raises the flag and costs its readers one
        chunk: the no-op is decided inside :class:`~rehuco_core.RehuRenamer`, which is where the
        resource's current name is known, and buying the shortcut would mean duplicating that here.

        :param path: the resource's ``.rehu`` file.
        :param new_name: the destination folder/file name.
        :param timeout: how long to wait for readers, in seconds.
        :returns: the resource's ``.rehu`` path under its new name.
        :raises RenameYieldTimeout: the readers did not let go in time; nothing on disk was touched.
        :raises OSError: whatever :func:`~rehuco_core.rename_rehu_resource` raises -- a name that is not
            a plain name, a missing ``.rehu``, an occupied destination, a failure part-way through.
        """
        with self.__renaming:
            self.__wait_for_readers(timeout)
            try:
                renamer = RehuRenamer(path, new_name)
                renamed = renamer.rename()
                self.__relocate_tracked(renamer)
            finally:
                self.__release_readers()
        self.__announce()
        return renamed

    def __wait_for_readers(self, timeout: float) -> None:
        """Raise the yield flag and wait for every holder to leave.

        The flag goes up first and stays up whatever happens next, which is what keeps a reader from
        slipping in behind the wait: a would-be holder blocks in :meth:`holding` rather than opening a
        handle the rename is about to trip over.

        :param timeout: how long to wait, in seconds.
        :raises RenameYieldTimeout: a holder was still there when the wait ran out; the flag is lowered
            again on the way out, so the next rename starts from a clean state rather than inheriting
            this one's.
        """
        with self.__condition:
            self.__yield_wanted = True
            self.__condition.notify_all()
            if self.__condition.wait_for(lambda: self.__holders == 0, timeout):
                return
            self.__yield_wanted = False
            self.__condition.notify_all()
        raise RenameYieldTimeout(f"A task is still reading these files and did not stop within {timeout:.0f}s.")

    def __release_readers(self) -> None:
        """Lower the yield flag and wake everyone waiting to hold again.

        In a ``finally``, so a rename that failed for its own reasons -- a collision, a vanished
        ``.rehu`` -- does not leave the resource permanently unreadable. The readers come back to paths
        that never changed, which is correct: nothing moved.
        """
        with self.__condition:
            self.__yield_wanted = False
            self.__condition.notify_all()

    def __relocate_tracked(self, renamer: RehuRenamer) -> None:
        """Rewrite every tracked location that this rename moved.

        Asks the renamer itself (:meth:`~rehuco_core.RehuRenamer.relocate`), so the answer comes from
        the plan that just ran rather than from a second opinion about what it must have done. A
        location the rename did not touch is handed back its own path and is written unchanged -- not
        worth a comparison, since the write is a lock and an assignment either way.

        Dead references are dropped in the same pass: a location outlives its job by no time at all, and
        this is the one place already walking the list.

        :param renamer: the rename that has just run.
        """
        alive: list[ReferenceType[ResourceLocation]] = []
        with self.__condition:
            for reference in self.__locations:
                location = reference()
                if location is None:
                    continue
                alive.append(reference)
                location.moved_to(renamer.relocate(location.path))
            self.__locations = alive

    def __announce(self) -> None:
        """Tell every listener that a rename landed.

        Called with no lock held and after the flag is down, so a listener is free to do real work --
        re-read a queue, redraw a row -- without holding a rename open behind it.

        **A listener's exception is logged, never propagated**, the same contract
        :class:`~rehuco_core.TaskQueue` gives its own: the rename has already happened, and raising out
        of the notification would tell the caller an operation failed that in fact succeeded.
        """
        with self.__condition:
            listeners = tuple(self.__listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.exception("A rename listener failed; detach it or fix it -- it was skipped.")
