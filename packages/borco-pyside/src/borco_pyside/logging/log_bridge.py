"""The seam between Python's logging and Qt: a handler that caches, batches, and routes."""

from collections import deque
from collections.abc import Hashable, Iterable, Sequence
from logging import Handler, LogRecord
from typing import Final, override

from PySide6.QtCore import QObject, Qt, Signal

from .log_entry import LogEntry
from .log_record_sink import LogRecordSink
from .log_scope import LogScope

DEFAULT_LOG_LIMIT: Final = 500
"""How many entries a ring buffer holds unless told otherwise.

Chosen as what a person actually scrolls back through, not as what fits in memory. A buffer exists so
that a job logging once per file over a large tree cannot grow the process without bound; keeping the
whole run instead would trade a bounded leak for an unbounded one and give the reader a haystack."""


# Nine, and each is a distinct fact this class is the only one holding: the buffer and its cap, what
# the cap has cost, where the serials are up to, how far dispatch has got, the two sink lists, whether
# a wake-up is already scheduled, and the object that carries it. Folding any pair together would be a
# tuple pretending to be a concept -- the two sink lists especially, which differ by whether a scope is
# matched at all rather than by its value.
# pylint: disable-next=too-many-instance-attributes
class LogBridge(Handler):
    """A `logging.Handler` that hands records to Qt sinks -- on the GUI thread, in batches, by scope.

    Four jobs, each of which exists because the obvious version of it is wrong:

    **It caches, so attaching late loses nothing.** Records are logged before there is a GUI to show
    them: startup, the settings read, a failure during ``main()``. This handler is installed first and
    holds what it receives, so a surface attached later is handed the history immediately -- which is
    also what lets a per-document surface, opened after the document was converted, still show the
    conversion.

    **It batches, so a loud job cannot lock the window.** A record is not dispatched where it is
    logged; instead one queued signal wakes the GUI thread, which then takes everything that arrived
    in the meantime as a single batch. A thousand records logged in one burst become one wake-up and
    one insert, not a thousand of each.

    **It marshals, so a worker thread never touches a model.** ``logging`` calls handlers
    synchronously on whatever thread logged, and the loudest client of this one is background work.
    The connection is explicitly queued rather than automatic, so a record logged *on* the GUI thread
    takes the same path as one logged off it: no sink is ever entered re-entrantly from inside a log
    call, and a sink that logs while handling a batch queues another batch instead of recursing.

    **It routes, so surfaces do not have to filter.** A sink added with :meth:`add_sink` sees
    everything; one added with :meth:`add_scoped_sink` sees only records made under its scope, wherever
    that scope sits in the record's stack
    (:class:`~.log_scope.LogScope`). Every sink keeps its own history and clears it independently --
    this class holds no opinion about what any of them contains, which is why no sink is asked for a
    ``cleared`` signal.

    Meant to be built and installed before any ``QApplication`` exists, and it buffers correctly with
    no event loop running -- nothing is dispatched until there is one, and the ring buffer keeps that
    from growing without bound in the meantime. It takes the thread it is built on as the thread its
    sinks live on, so build it there.

    **Not a `QObject`**, though it needs a signal: `logging.Handler.emit` and ``QObject.emit`` are
    unrelated methods that happen to share a name, and a class inheriting both would silently give
    ``logging`` the one and Qt the other. The signal lives on :class:`Marshaller` instead, which is
    the whole of what Qt is needed for here.

    :param limit: how many entries to cache for replay; see :attr:`limit`.
    """

    class Marshaller(QObject):
        """Carries "there is a batch waiting" across the thread boundary, and nothing else.

        Exists because a signal has to live on a `QObject` and this handler must not be one (see
        :class:`LogBridge`). Takes its thread affinity from whoever built the bridge, which is what
        makes the queued connection land on that thread.

        Nested and undocumented outside this class rather than name-mangled, only because a mangled
        class name is not a class name Qt or the linters will accept -- nothing outside
        :class:`LogBridge` has a reason to build one.
        """

        batch_ready = Signal()
        """Fires when entries are waiting for the sinks' thread.

        Carries nothing: the payload is whatever has accumulated by the time the slot runs, which is
        the point of batching. Emitted once per batch rather than once per record -- a record arriving
        before the other thread wakes up joins the batch instead of scheduling another."""

    def __init__(self, *, limit: int = DEFAULT_LOG_LIMIT) -> None:
        super().__init__()
        self.__marshaller = LogBridge.Marshaller()
        self.__limit = max(1, limit)
        self.__entries: deque[LogEntry] = deque(maxlen=self.__limit)
        self.__next_serial = 0
        self.__dispatched_through = -1
        self.__sinks: list[LogRecordSink] = []
        self.__scoped_sinks: list[tuple[LogRecordSink, Hashable]] = []
        self.__batch_pending = False
        self.__marshaller.batch_ready.connect(self.__dispatch, Qt.ConnectionType.QueuedConnection)

    # region cache

    @property
    def limit(self) -> int:
        """How many entries the cache holds before dropping its oldest.

        Settable while running: lowering it trims immediately rather than at the next restart, so a
        change made in a settings dialog is visible in what the next attach replays.

        **This is also the ceiling on one batch.** The cache is not only the replay buffer -- it is
        where entries wait for their thread, since keeping a second, unbounded queue for them would
        just move the leak. So a burst longer than this arriving while that thread is busy loses its
        oldest. A bounded sink would have let those entries go on arrival anyway, as long as it is not
        asked to hold more than this; an unbounded one would have kept them, which is the one case
        where this ceiling costs a reader something ([[appendices.logging#buffers]]).
        """
        return self.__limit

    @limit.setter
    def limit(self, limit: int) -> None:
        """Re-cap the cache, dropping the oldest entries if it no longer fits.

        :param limit: the new cap; anything below 1 is raised to 1.
        """
        limit = max(1, limit)
        if limit == self.__limit:
            return
        self.acquire()
        try:
            self.__limit = limit
            # a deque's maxlen is read-only, so re-capping means building the replacement; the slice
            # keeps the newest, and what falls off goes for the same reason an overflow does
            self.__entries = deque(list(self.__entries)[-limit:], maxlen=limit)
        finally:
            self.release()

    def clear_cache(self) -> None:
        """Forget the cached entries, so a later attach replays nothing from before now.

        Affects only what future attaches see. Sinks already attached keep everything they were given:
        each holds its own history, and this class is not the place from which theirs is emptied.
        """
        self.acquire()
        try:
            self.__entries.clear()
        finally:
            self.release()

    # endregion

    # region sinks

    def add_sink(self, sink: LogRecordSink) -> None:
        """Attach a sink that sees every record, and replay the cache into it.

        :param sink: where to put entries from now on.
        """
        self.__attach(sink, self.__entries)
        self.__sinks.append(sink)

    def add_scoped_sink(self, sink: LogRecordSink, scope: Hashable) -> None:
        """Attach a sink that sees only records made under ``scope``, and replay its share of the cache.

        A scoped sink is shown neither another scope's records nor unscoped ones: it is the log *of
        that thing*, and a reader who wants the rest has the unscoped surface for it.

        **Matched anywhere in the record's stack**, not only innermost: a record about a document and
        about the job hashing it belongs to both surfaces, and neither is a filtered copy of the other
        (:class:`~.log_entry.LogEntry`). A sink is still attached under exactly one scope -- two of them
        would be a surface that is the log of two things, which no reader has asked for.

        :param sink: where to put matching entries from now on.
        :param scope: the scope to match, compared by equality (:class:`~.log_scope.LogScope`).
        """
        self.__attach(sink, (entry for entry in self.__entries if scope in entry.scopes))
        self.__scoped_sinks.append((sink, scope))

    def remove_sink(self, sink: LogRecordSink) -> None:
        """Stop giving entries to ``sink``, whether it was attached scoped or not.

        What it already holds is its own; nothing is taken back. A sink that is not attached is
        silently accepted, so teardown never has to ask first.

        :param sink: the sink to detach.
        """
        self.__sinks = [attached for attached in self.__sinks if attached is not sink]
        self.__scoped_sinks = [pair for pair in self.__scoped_sinks if pair[0] is not sink]

    def __attach(self, sink: LogRecordSink, replay: Iterable[LogEntry]) -> None:
        """Hand a not-yet-registered sink its share of the cache, exactly once.

        Dispatches first, deliberately: any entry that arrived but has not reached the GUI thread yet
        is still in the cache, so replaying without draining first would give the new sink those
        entries now and again when the pending batch runs.

        :param sink: the sink about to be registered.
        :param replay: its share of the cache, oldest first.
        """
        self.__dispatch()
        entries = list(replay)
        if entries:
            sink.handle_log_records(entries)

    # endregion

    # region the record path

    @override
    def emit(self, record: LogRecord) -> None:
        """Cache one record and wake the GUI thread if it is not already awake.

        Runs on whatever thread logged, under the lock `logging.Handler.handle` holds. Everything that
        can only be answered here is answered here: the record is formatted **once**, and its scopes are
        resolved while the context that opened them is still the current one.

        :param record: the record ``logging`` is handing over.
        """
        try:
            entry = LogEntry(record, self.format(record), LogScope.of(record), self.__next_serial)
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            # logging's own contract: a handler reports its failure through handleError and never
            # raises into the code that logged -- a broken format string is not the caller's problem
            self.handleError(record)
            return
        self.__next_serial += 1
        self.__entries.append(entry)
        if not self.__batch_pending:
            self.__batch_pending = True
            self.__marshaller.batch_ready.emit()

    def __dispatch(self) -> None:
        """Give every sink the entries it has not been given yet, as one batch each.

        Runs on the GUI thread -- either from the queued signal, or directly from :meth:`__attach`,
        which is already there. The batch is taken under the lock and the sinks are called outside it,
        so a sink that logs while handling one cannot deadlock against the thread that is logging.
        """
        self.acquire()
        try:
            self.__batch_pending = False
            batch = [entry for entry in self.__entries if entry.serial > self.__dispatched_through]
            if batch:
                self.__dispatched_through = batch[-1].serial
        finally:
            self.release()
        if not batch:
            return
        for sink in self.__sinks:
            sink.handle_log_records(batch)
        for sink, scope in self.__scoped_sinks:
            self.__dispatch_scoped(sink, scope, batch)

    @staticmethod
    def __dispatch_scoped(sink: LogRecordSink, scope: Hashable, batch: Sequence[LogEntry]) -> None:
        """Give one scoped sink its share of a batch, if it has one.

        :param sink: the scoped sink.
        :param scope: the scope it was attached under; matched anywhere in a record's stack.
        :param batch: the whole batch, oldest first.
        """
        entries = [entry for entry in batch if scope in entry.scopes]
        if entries:
            sink.handle_log_records(entries)

    # endregion
