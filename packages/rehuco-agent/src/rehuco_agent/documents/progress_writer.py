"""Watch progress and measured lengths written to a record off the GUI thread, so a share that has gone silent never
holds the window (#316, [[field-schema#watch-progress]])."""

import threading
from collections.abc import Callable, Hashable
from itertools import count
from typing import Final

from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Qt, Signal
from rehuco_core import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from rehuco_core.access import LoadedRecord

type Work = Callable[[], LoadedRecord | None]
"""One write, run on the writer's thread: it answers the record as read after it, or ``None`` when it wrote nothing."""

type Answer = Callable[[LoadedRecord | Exception | None], None]
"""What hears a write's outcome on the GUI thread: the record read after it, the error it ended in, or ``None`` when it
wrote nothing."""


class ProgressWriter(QObject):
    """Runs one document's progress writes one at a time on a daemon thread, and answers each on the GUI thread.

    **Writes are serialized**, so a document's progress, its renamed-file moves and its measured lengths never race one
    another, and **coalesced by key**: a write still waiting when a newer one for the same key is submitted is replaced
    by it -- the player's position every few seconds is the latest position, not a queue of them. A write runs under the
    rename barrier, like every off-GUI use of a record, so a rename never
    moves the file under it.

    **It runs on a daemon thread** ([[appendices.code-conventions#worker-threads]]): a write waits for the record's lock
    file, and a share can hold it for its whole timeout; nothing may hold up quitting for that. The thread lives while
    there is something to write and ends when the queue is empty, so a document closed with its last write still out
    finishes that write -- the answer simply has nobody left to hear it: a child of its document, it goes with it, and
    Qt drops what was posted to it.

    :param coordinator: the rename barrier the writes hold; the app's default when ``None``.
    :param parent: optional Qt parent.
    """

    __answered: Signal = Signal(int, object)
    """Emitted from the writer's thread with a write's ticket and outcome; its slot runs on the GUI thread (the
    connection is queued because the sender's thread is not the receiver's)."""

    def __init__(self, coordinator: RenameCoordinator | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__tickets: Final = count()
        self.__waiting: Final[dict[int, Answer]] = {}
        """Each write still out, by ticket: who hears its outcome."""
        self.__queue: Final[dict[Hashable, tuple[int, Work, Hashable | None]]] = {}
        """The writes not started yet, oldest first, by key: each with its ticket, its work and its log scope."""
        self.__lock: Final = threading.Lock()
        self.__running = False
        """Whether the thread is alive: set and cleared under the lock, so a write submitted as it ends starts a new
        one."""
        self.__answered.connect(self.__on_answered, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self) -> bool:
        """Whether a write is waiting or running."""
        return bool(self.__waiting)

    def submit(self, key: Hashable, work: Work, answer: Answer, scope: Hashable | None = None) -> None:
        """Queue ``work`` to run on the writer's thread, replacing a write of the same ``key`` still waiting.

        :param key: what makes two writes the same one: the later replaces the earlier while that has not started.
        :param work: the write.
        :param answer: what hears its outcome on the GUI thread; never called for a write a later one replaced.
        :param scope: the record's path, which the log records the write makes are scoped to.
        """
        ticket = next(self.__tickets)
        with self.__lock:
            replaced = self.__queue.pop(key, None)
            if replaced is not None:
                self.__waiting.pop(replaced[0], None)
            self.__waiting[ticket] = answer  # pylint: disable=unsupported-assignment-operation
            self.__queue[key] = (ticket, work, scope)  # pylint: disable=unsupported-assignment-operation
            if not self.__running:
                self.__running = True
                threading.Thread(target=self.__run, name="progress-write", daemon=True).start()

    def __run(self) -> None:
        """Take the oldest waiting write, run it and post its outcome, until none is left (the daemon thread)."""
        while True:
            with self.__lock:
                if not self.__queue:
                    self.__running = False
                    return
                key = next(iter(self.__queue))
                ticket, work, scope = self.__queue.pop(key)
            outcome = self.__execute(work, scope)
            try:
                self.__answered.emit(ticket, outcome)
            except RuntimeError:  # the writer was destroyed while the write was out
                continue

    def __execute(self, work: Work, scope: Hashable | None) -> LoadedRecord | Exception | None:
        """Run one write under the rename hold, an error answered rather than raised.

        :param work: the write.
        :param scope: the record's path, which the log records the write makes are scoped to.
        :returns: what the write answered, or the error it ended in.
        """
        try:
            with LogScope.open(scope), self.__coordinator.holding():
                return work()
        # a write that raised would otherwise answer nothing, leaving its document waiting for good (#480)
        except Exception as error:  # pylint: disable=broad-exception-caught
            return error

    def __on_answered(self, ticket: int, outcome: LoadedRecord | Exception | None) -> None:
        """Hand a write's outcome to whoever submitted it (GUI thread) -- unless a later write replaced it.

        :param ticket: the write.
        :param outcome: what it answered.
        """
        answer = self.__waiting.pop(ticket, None)
        if answer is not None:
            answer(outcome)
