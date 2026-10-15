"""The browsers' rows, read off the GUI thread (#455): one :class:`~rehuco_core.CatalogSnapshot` every browser filters
in memory."""

import gc
import logging
import threading
from collections.abc import Callable, Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from rehuco_core import CatalogQuery, CatalogRow, CatalogSnapshot, CatalogUnreadable

LOG: Final = logging.getLogger(__name__)

type RowsReader = Callable[[CatalogQuery, set[int] | None], list[CatalogRow]]
"""Reads the catalog's rows -- :meth:`~rehuco_agent.rehuco.root_catalog.RootCatalog.rows`; called on a pool thread."""


@dataclass(frozen=True, slots=True)
class CatalogRowsLoad:
    """What one read delivered.

    :param snapshot: every row of the catalog now.
    :param affected: the ids of the rows a change may have touched, for a read of just those; ``None`` for a read of
        every row.
    """

    snapshot: CatalogSnapshot
    affected: frozenset[int] | None = None


@dataclass(frozen=True, slots=True)
class CatalogRowsRequest:
    """One read handed to the pool.

    :param root_ids: the roots' ids, in the roots' order.
    :param affected: the rows to read again, patched into ``base``; ``None`` reads every row.
    :param base: the snapshot a read of a few rows patches.
    """

    root_ids: tuple[UUID, ...]
    affected: frozenset[int] | None = None
    base: CatalogSnapshot | None = None


class CatalogRowsLoader(QObject):
    """Reads the catalog's rows on the pool and keys them there, so the GUI thread only filters (#455).

    **One read at a time, the rest merged while it runs.** A request made while one is out waits; a read of every row
    absorbs every read of a few rows waiting with it, and those merge their ids. So a change announced during a read
    is read again after it, whatever the first one saw, and a read of a few rows always patches the snapshot it was
    started from. An answer a read of every row has since been asked over is dropped unseen: the next one replaces it.

    **The collector is paused while a read builds its rows** (:meth:`collector_paused`): the cyclic collector, run
    over and over as the new rows pile up, frees none of them but walks them all holding the GIL. Measured at 100k rows,
    a read of a few rows, which copies every row, went from 421 ms to 75 ms with the GUI thread never held up past
    15 ms; a read of every row still holds it up once, for the collector's first pass over the rows it built -- 77 ms,
    since a row makes three tracked objects (#500), against several stalls of 50-180 ms unpaused.

    **The answer is judged on the GUI thread** ([[appendices.code-conventions#worker-threads]]): each read carries a
    generation, and :meth:`cancel` moves it on, so a read still out when the catalog closed delivers nothing. The emit
    from the pool is guarded, for a loader destroyed while its read was out.

    :param read: what reads the rows; called on a pool thread.
    :param parent: optional Qt parent.
    """

    loaded: Signal = Signal(object)
    """Emitted with a :class:`CatalogRowsLoad` once a read lands; :attr:`snapshot` is its snapshot by then. A read
    that failed is logged and emits nothing: the old rows stay."""

    class Carrier(QObject):
        """Carries an answer from the pool to the GUI thread, and nothing else."""

        answered = Signal(int, object)
        """``(generation, snapshot or None)``: one read's answer, judged on the GUI thread."""

    __COLLECTOR_LOCK: Final = threading.Lock()
    __collector_pauses = 0
    """How many reads are pausing the collector now, under :attr:`__COLLECTOR_LOCK`."""
    __collector_paused_here = False
    """Whether the collector was on when the first of them paused it -- and so is to be switched back on."""

    @classmethod
    @contextmanager
    def collector_paused(cls) -> Generator[None]:
        """Switch the cyclic collector off for the block, process-wide; it comes back on once the last block pausing
        it ends -- and only if it was on when the first began.
        """
        with cls.__COLLECTOR_LOCK:
            if cls.__collector_pauses == 0:
                cls.__collector_paused_here = gc.isenabled()
                gc.disable()
            cls.__collector_pauses += 1
        try:
            yield
        finally:
            with cls.__COLLECTOR_LOCK:
                cls.__collector_pauses -= 1
                if cls.__collector_pauses == 0 and cls.__collector_paused_here:
                    gc.enable()

    def __init__(self, read: RowsReader, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__read: Final = read
        self.__snapshot = CatalogSnapshot.build((), ())
        self.__generation = 0
        self.__out: CatalogRowsRequest | None = None
        self.__waiting_roots: tuple[UUID, ...] | None = None
        """The roots of a read of every row waiting to start, or ``None`` while none is."""
        self.__waiting_ids: Final[set[int]] = set()
        self.__carrier: Final = CatalogRowsLoader.Carrier(self)
        self.__carrier.answered.connect(self.__on_answered, Qt.ConnectionType.QueuedConnection)

    @property
    def snapshot(self) -> CatalogSnapshot:
        """Every row as the last read that landed left them; empty before the first."""
        return self.__snapshot

    @property
    def busy(self) -> bool:
        """Whether a read is out."""
        return self.__out is not None

    def refresh(self, root_ids: Sequence[UUID]) -> None:
        """Read every row again.

        :param root_ids: the roots' ids, in the roots' order.
        """
        self.__waiting_roots = tuple(root_ids)
        self.__waiting_ids.clear()
        self.__start_next()

    def update(self, affected: Collection[int]) -> None:
        """Read again the rows a change touched, and patch them into the snapshot.

        :param affected: their ids.
        """
        if self.__waiting_roots is None:
            self.__waiting_ids.update(affected)
            self.__start_next()

    def cancel(self) -> None:
        """Forget every row and every read: what is out delivers nothing, what waits never starts."""
        self.__generation += 1
        self.__out = None
        self.__waiting_roots = None
        self.__waiting_ids.clear()
        self.__snapshot = CatalogSnapshot.build((), ())

    def __start_next(self) -> None:
        """Start the read waiting, if one is and none is out."""
        if self.__out is not None:
            return
        if self.__waiting_roots is not None:
            request = CatalogRowsRequest(self.__waiting_roots)
        elif self.__waiting_ids:
            snapshot = self.__snapshot
            request = CatalogRowsRequest(snapshot.root_ids, frozenset(self.__waiting_ids), snapshot)
        else:
            return
        self.__waiting_roots = None
        self.__waiting_ids.clear()
        self.__out = request
        self.__generation += 1
        generation = self.__generation
        QThreadPool.globalInstance().start(lambda: self.__run(generation, request))

    def __run(self, generation: int, request: CatalogRowsRequest) -> None:
        """Read and key the rows on the pool, and answer -- ``None`` for a read that failed.

        :param generation: which read this is.
        :param request: what to read.
        """
        snapshot: CatalogSnapshot | None = None
        try:
            with self.collector_paused():
                snapshot = self.__build(request)
        except CatalogUnreadable as error:
            LOG.error("Could not read the catalog's rows: %s", error)
        except Exception:  # pylint: disable=broad-exception-caught  # the pool swallows what escapes: no answer would come
            LOG.exception("Could not read the catalog's rows.")
        try:
            self.__carrier.answered.emit(generation, snapshot)
        except RuntimeError:  # the loader was destroyed while the read was out
            pass

    def __build(self, request: CatalogRowsRequest) -> CatalogSnapshot:
        """Read and key the rows a request asks for.

        :param request: what to read.
        :returns: the new snapshot.
        :raises CatalogUnreadable: when the catalog cannot be read.
        """
        if request.affected is None or request.base is None:
            return CatalogSnapshot.build(self.__read(CatalogQuery(), None), request.root_ids)
        fresh = self.__read(CatalogQuery(), set(request.affected))
        return request.base.patched(request.affected, fresh)

    def __on_answered(self, generation: int, snapshot: CatalogSnapshot | None) -> None:
        """Take a read's answer, unless it was cancelled or a read of every row has been asked for since; then start
        the next read (GUI thread).

        :param generation: which read answered.
        :param snapshot: what it read; ``None`` when it failed.
        """
        request = self.__out
        if generation != self.__generation or request is None:
            return
        self.__out = None
        if snapshot is not None and self.__waiting_roots is None:
            self.__snapshot = snapshot
            self.loaded.emit(CatalogRowsLoad(snapshot, request.affected))
        self.__start_next()
