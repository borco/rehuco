"""The comparison of roots through links, and the plan of roots to add, run where they may block -- never on the GUI
thread (#498, #578).

:meth:`RootOverlap.find_resolved <rehuco_core.RootOverlap.find_resolved>` follows links with
:func:`os.path.realpath`, which on Windows also follows a mapped drive to its share and waits out the network's
timeout when the share is switched off (#464); :meth:`RootPlanner.plan <rehuco_core.RootPlanner.plan>` does that and
reads the picked root files besides. So each runs on a daemon :class:`threading.Thread`, as
:class:`borco_core.PresenceScan` does and for the reason [[appendices.code-conventions#worker-threads]] gives: a pool
worker stuck in that call would hold up quitting, and a daemon thread is simply left behind. The thread holds no Qt
object; its answer is emitted on a private signal queued to the GUI thread, judged there by serial.
"""

import itertools
import logging
import threading
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Final
from uuid import UUID

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance, Slot
from rehuco_core import MappedRoot, RehucoFile, RootOverlap, RootPick, RootPlanner

LOG: Final = logging.getLogger(__name__)


class RootOverlapCheck(QObject):
    """Runs one comparison of roots through links, or one plan of roots to add, per call, each on a daemon thread,
    and answers on the GUI thread.

    :param parent: optional Qt parent.
    """

    answered: Signal = Signal(int, object)
    """``(serial, overlaps)`` on the GUI thread: the ``tuple`` of :class:`~rehuco_core.RootOverlap` a check found,
    empty for none. The caller judges a stale answer by its serial."""

    planned: Signal = Signal(int, object)
    """``(serial, candidates)`` on the GUI thread: the ``tuple`` of :class:`~rehuco_core.RootCandidate` a plan made,
    or ``None`` when it failed, which the log says why. The caller judges a stale answer by its serial."""

    __relayed: Signal = Signal(int, object, object)
    """``(serial, answer, signal)``, emitted from a check's thread; its slot runs on the GUI thread, the connection
    queued, and passes the answer on by the signal it names."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__relayed.connect(self.__on_relayed, Qt.ConnectionType.QueuedConnection)
        self.__serials: Final = itertools.count(1)
        self.__stopped: Final = threading.Event()
        # a parent torn down without stop() must not be emitted into from a check's thread after its C++ object is
        # gone: ``set`` is a plain Python bound method, safe to run from here
        self.destroyed.connect(self.__stopped.set)

    def find(self, candidate: Path | str, roots: Sequence[MappedRoot], skip: Collection[UUID]) -> int:
        """Start comparing a candidate root with the roots, through links.

        :param candidate: the folder about to be added.
        :param roots: the file's roots.
        :param skip: the roots not to resolve -- those known unreachable.
        :returns: the check's serial, which its answer carries.
        """
        roots, skip = tuple(roots), frozenset(skip)

        def run() -> tuple[RootOverlap, ...]:
            overlap = RootOverlap.find_resolved(candidate, roots, skip)
            return () if overlap is None else (overlap,)

        return self.__start(
            run, self.answered, (), "Comparing roots through their links failed; only their spellings were compared."
        )

    def among(self, roots: Sequence[MappedRoot], skip: Collection[UUID]) -> int:
        """Start comparing a file's roots with each other, through links.

        :param roots: the file's roots.
        :param skip: the roots not to resolve -- those known unreachable.
        :returns: the check's serial, which its answer carries.
        """
        roots, skip = tuple(roots), frozenset(skip)
        return self.__start(
            lambda: RootOverlap.among_resolved(roots, skip),
            self.answered,
            (),
            "Comparing roots through their links failed; only their spellings were compared.",
        )

    def plan(
        self, file: RehucoFile, picks: Sequence[RootPick], roots: Sequence[MappedRoot], skip: Collection[UUID]
    ) -> int:
        """Start planning what picks would add to a catalog (:meth:`RootPlanner.plan
        <rehuco_core.RootPlanner.plan>`).

        :param file: the catalog; only read.
        :param picks: the paths picked, in order.
        :param roots: the catalog's roots this machine reaches.
        :param skip: the roots not to resolve -- those known unreachable.
        :returns: the plan's serial, which its answer carries.
        """
        picks, roots, skip = tuple(picks), tuple(roots), frozenset(skip)
        return self.__start(
            lambda: RootPlanner.plan(file, picks, roots, skip), self.planned, None, "Planning the roots to add failed."
        )

    def stop(self) -> None:
        """Deliver no more answers. A check still blocked on a switched-off server is not waited for: its thread is a
        daemon, and the process leaves without it."""
        self.__stopped.set()

    def __start(self, check: Callable[[], object], signal: SignalInstance, failed: object, message: str) -> int:
        """Run a check on a daemon thread of its own.

        :param check: the comparison or the plan; it may block.
        :param signal: the signal its answer goes out on, on the GUI thread.
        :param failed: the answer when it raises.
        :param message: what the log says then.
        :returns: its serial.
        """
        serial = next(self.__serials)

        def run() -> None:
            try:
                answer = check()
            except Exception:  # pylint: disable=broad-exception-caught  # a thread's exception would only be printed
                LOG.exception(message)
                answer = failed
            if self.__stopped.is_set():
                return
            try:
                self.__relayed.emit(serial, answer, signal)
            except RuntimeError:  # the check outlived its owner between the test and the emit
                pass

        threading.Thread(target=run, name=f"root-overlap-check-{serial}", daemon=True).start()
        return serial

    @Slot(int, object, object)
    def __on_relayed(self, serial: int, answer: object, signal: SignalInstance) -> None:
        """On the GUI thread: pass the answer on, by the signal it is for, unless the check was stopped meanwhile."""
        if not self.__stopped.is_set():
            signal.emit(serial, answer)
