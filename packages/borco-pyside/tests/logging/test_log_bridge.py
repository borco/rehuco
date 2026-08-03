"""Tests for LogBridge."""

import logging
import threading
from collections.abc import Callable, Iterator, Sequence

from borco_pyside.logging.log_bridge import DEFAULT_LOG_LIMIT, LogBridge
from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_record_sink import LogRecordSink
from borco_pyside.logging.log_scope import LOG_SCOPE_ATTRIBUTE, LogScope
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

# region helpers


class RecordingSink:
    """A `LogRecordSink` that remembers each batch it was given, and the thread it was given it on."""

    def __init__(self) -> None:
        self.batches: list[list[LogEntry]] = []
        self.threads: list[int] = []

    @property
    def messages(self) -> list[str]:
        """Every message taken, in order, across all batches."""
        return [entry.message for batch in self.batches for entry in batch]

    def handle_log_records(self, entries: Sequence[LogEntry]) -> None:
        """Remember the batch.

        :param entries: the entries handed over.
        """
        self.batches.append(list(entries))
        self.threads.append(threading.get_ident())


# endregion


# region fixtures


@fixture
def bridge() -> Iterator[LogBridge]:
    """Provide a bridge formatting messages bare, detached from ``logging`` on teardown.

    :returns: the bridge.
    """
    built = LogBridge()
    built.setFormatter(logging.Formatter("%(message)s"))
    yield built
    built.close()


@fixture
def log(bridge: LogBridge) -> Iterator[logging.Logger]:
    """Provide a logger feeding only ``bridge``, so nothing reaches the console or another test.

    :param bridge: the handler to install.
    :returns: the logger.
    """
    logger = logging.getLogger("borco_pyside.tests.log_bridge")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bridge)
    yield logger
    logger.removeHandler(bridge)


@fixture
def deliver(qtbot: QtBot) -> Callable[[], None]:
    """Provide a way to run the queued dispatch, which needs the event loop to turn.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: a callable that lets pending batches reach their sinks.
    """
    return lambda: qtbot.wait(10)


# endregion


# region cache and replay


def test_records_logged_before_any_sink_exists_are_replayed_on_attach(bridge: LogBridge, log: logging.Logger) -> None:
    """A sink attached later is handed everything already logged, in order.

    **Test steps:**

    * log three records with no sink attached
    * attach a sink
    * verify it was given all three, in the order they were logged
    """
    log.info("first")
    log.info("second")
    log.info("third")
    sink = RecordingSink()

    bridge.add_sink(sink)

    assert sink.messages == ["first", "second", "third"]


def test_the_replay_arrives_as_one_batch(bridge: LogBridge, log: logging.Logger) -> None:
    """The whole cache is handed over in a single call, not one call per record.

    **Test steps:**

    * log three records with no sink attached
    * attach a sink
    * verify it was called once
    """
    log.info("first")
    log.info("second")
    log.info("third")
    sink = RecordingSink()

    bridge.add_sink(sink)

    assert len(sink.batches) == 1


def test_attaching_with_nothing_logged_hands_over_nothing(bridge: LogBridge) -> None:
    """A sink attached to a silent bridge is not called at all.

    **Test steps:**

    * attach a sink to a bridge that has seen no records
    * verify it was never called
    """
    sink = RecordingSink()

    bridge.add_sink(sink)

    assert not sink.batches


def test_a_pending_batch_is_not_replayed_twice(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A record cached but not yet dispatched reaches a newly attached sink exactly once.

    **Test steps:**

    * attach a first sink, then log a record without letting the event loop turn
    * attach a second sink while that batch is still pending
    * let the dispatch run
    * verify the second sink was given the record once
    """
    bridge.add_sink(RecordingSink())
    log.info("pending")
    second = RecordingSink()

    bridge.add_sink(second)
    deliver()

    assert second.messages == ["pending"]


def test_clearing_the_cache_stops_a_later_attach_replaying(bridge: LogBridge, log: logging.Logger) -> None:
    """Clearing the cache means a sink attached afterwards starts empty.

    **Test steps:**

    * log a record, then clear the cache
    * attach a sink
    * verify it was given nothing
    """
    log.info("forgotten")
    bridge.clear_cache()
    sink = RecordingSink()

    bridge.add_sink(sink)

    assert sink.messages == []


def test_clearing_the_cache_takes_nothing_back_from_an_attached_sink(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A sink keeps what it was already given when the bridge's cache is cleared.

    **Test steps:**

    * attach a sink and log a record, letting it be dispatched
    * clear the bridge's cache
    * verify the sink still holds the record
    """
    sink = RecordingSink()
    bridge.add_sink(sink)
    log.info("kept")
    deliver()

    bridge.clear_cache()

    assert sink.messages == ["kept"]


# endregion


# region batching and the thread boundary


def test_records_logged_in_a_burst_arrive_as_one_batch(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Records logged between two turns of the event loop are dispatched together.

    **Test steps:**

    * attach a sink
    * log three records without letting the event loop turn
    * let the dispatch run
    * verify the sink was called once, with all three
    """
    sink = RecordingSink()
    bridge.add_sink(sink)

    log.info("first")
    log.info("second")
    log.info("third")
    deliver()

    assert len(sink.batches) == 1
    assert sink.messages == ["first", "second", "third"]


def test_a_record_logged_on_the_gui_thread_is_still_dispatched_later(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Dispatch is queued even for a record logged on the sink's own thread.

    Same path for both, so a sink is never entered re-entrantly from inside a log call.

    **Test steps:**

    * attach a sink and log a record on the test's own thread
    * verify the sink has not been called yet
    * let the dispatch run and verify it then has
    """
    sink = RecordingSink()
    bridge.add_sink(sink)

    log.info("same thread")

    assert not sink.batches

    deliver()

    assert sink.messages == ["same thread"]


def test_records_logged_off_the_gui_thread_are_handed_over_on_it(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A worker thread's records reach the sink, and the sink is entered on the GUI thread.

    Asserts the marshalling itself, not only that the records arrived: a sink touched on the
    worker's thread would be a model mutated off the GUI thread.

    **Test steps:**

    * attach a sink, then log two records from another thread and join it
    * let the dispatch run
    * verify both records arrived, as one batch
    * verify the sink was entered on this thread, not the worker's
    """
    sink = RecordingSink()
    bridge.add_sink(sink)
    worker_thread: list[int] = []

    def work() -> None:
        worker_thread.append(threading.get_ident())
        log.warning("from the worker")
        log.warning("also from the worker")

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    deliver()

    assert sink.messages == ["from the worker", "also from the worker"]
    assert len(sink.batches) == 1
    assert sink.threads == [threading.get_ident()]
    assert worker_thread != sink.threads


def test_a_worker_carries_the_scope_of_whoever_submitted_its_work(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Work run inside a copied context logs under the scope that was open when it was submitted.

    The mechanism a background queue needs: a thread does not inherit a scope, but a context copied
    at submission carries it.

    **Test steps:**

    * open a scope and copy the context inside it
    * attach a sink scoped to it, then run a worker thread inside the copied context
    * verify the worker's record reached the scoped sink
    """
    import contextvars  # pylint: disable=import-outside-toplevel  # only this test needs it

    sink = RecordingSink()
    bridge.add_scoped_sink(sink, "resource")
    with LogScope.open("resource"):
        context = contextvars.copy_context()

    worker = threading.Thread(target=lambda: context.run(log.warning, "from the worker"))
    worker.start()
    worker.join()
    deliver()

    assert sink.messages == ["from the worker"]


# endregion


# region routing by scope


def test_an_unscoped_sink_sees_every_record(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A sink added unscoped is given scoped and unscoped records alike.

    **Test steps:**

    * attach an unscoped sink
    * log one unscoped record and one under each of two scopes
    * verify all three arrived
    """
    sink = RecordingSink()
    bridge.add_sink(sink)

    log.info("unscoped")
    with LogScope.open("a"):
        log.info("about a")
    with LogScope.open("b"):
        log.info("about b")
    deliver()

    assert sink.messages == ["unscoped", "about a", "about b"]


def test_a_scoped_sink_sees_only_its_own_scope(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """One resource's records do not reach another resource's sink, nor unscoped ones.

    **Test steps:**

    * attach a sink scoped to "a" and another scoped to "b"
    * log an unscoped record and one under each scope
    * verify each sink was given only its own scope's record
    """
    a_sink = RecordingSink()
    b_sink = RecordingSink()
    bridge.add_scoped_sink(a_sink, "a")
    bridge.add_scoped_sink(b_sink, "b")

    log.info("unscoped")
    with LogScope.open("a"):
        log.info("about a")
    with LogScope.open("b"):
        log.info("about b")
    deliver()

    assert a_sink.messages == ["about a"]
    assert b_sink.messages == ["about b"]


def test_a_scoped_sink_is_not_called_at_all_for_a_batch_of_other_scopes(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A batch holding nothing for a scoped sink does not reach it as an empty batch.

    **Test steps:**

    * attach a sink scoped to "a"
    * log a record under a different scope
    * verify the sink was never called
    """
    sink = RecordingSink()
    bridge.add_scoped_sink(sink, "a")

    with LogScope.open("b"):
        log.info("about b")
    deliver()

    assert not sink.batches


def test_a_scoped_sink_replays_only_its_own_scope_on_attach(bridge: LogBridge, log: logging.Logger) -> None:
    """Attaching a scoped sink replays that scope's history, not the whole cache.

    A resource's surface opened after the work was done still shows the work.

    **Test steps:**

    * log an unscoped record and one under each of two scopes, with no sink attached
    * attach a sink scoped to "a"
    * verify it was given only the "a" record
    """
    log.info("unscoped")
    with LogScope.open("a"):
        log.info("about a")
    with LogScope.open("b"):
        log.info("about b")
    sink = RecordingSink()

    bridge.add_scoped_sink(sink, "a")

    assert sink.messages == ["about a"]


def test_an_explicit_scope_on_one_call_routes_that_record(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """A record scoped through logging's own extra= reaches that scope's sink.

    **Test steps:**

    * attach a sink scoped to "a"
    * log a record naming that scope explicitly, with no scope open
    * verify it arrived
    """
    sink = RecordingSink()
    bridge.add_scoped_sink(sink, "a")

    log.info("named at the call site", extra={LOG_SCOPE_ATTRIBUTE: "a"})
    deliver()

    assert sink.messages == ["named at the call site"]


def test_a_detached_sink_is_given_nothing_further(
    bridge: LogBridge, log: logging.Logger, deliver: Callable[[], None]
) -> None:
    """Removing a sink stops its records, scoped or not, and takes nothing back.

    **Test steps:**

    * attach an unscoped and a scoped sink, log a scoped record and let it be dispatched
    * remove both sinks and log another
    * verify neither received the second record, and both kept the first
    """
    unscoped = RecordingSink()
    scoped = RecordingSink()
    bridge.add_sink(unscoped)
    bridge.add_scoped_sink(scoped, "a")
    with LogScope.open("a"):
        log.info("before")
    deliver()

    bridge.remove_sink(unscoped)
    bridge.remove_sink(scoped)
    with LogScope.open("a"):
        log.info("after")
    deliver()

    assert unscoped.messages == ["before"]
    assert scoped.messages == ["before"]


def test_removing_a_sink_that_was_never_attached_is_accepted(bridge: LogBridge) -> None:
    """Detaching an unknown sink is a no-op, so teardown never has to ask first.

    **Test steps:**

    * remove a sink that was never added
    * verify nothing was raised
    """
    bridge.remove_sink(RecordingSink())


# endregion


# region the cap


def test_the_cache_holds_the_default_number_of_entries(bridge: LogBridge) -> None:
    """A bridge built with no limit uses the shared default.

    **Test steps:**

    * read a fresh bridge's limit
    * verify it is the default
    """
    assert bridge.limit == DEFAULT_LOG_LIMIT


def test_the_cache_keeps_the_newest_entries_within_its_cap(log: logging.Logger) -> None:
    """Past the cap, the oldest cached entries are dropped and the newest kept.

    **Test steps:**

    * build a bridge capped at two and log three records
    * attach a sink
    * verify it was replayed the last two
    """
    bridge = LogBridge(limit=2)
    bridge.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(bridge)
    try:
        log.info("first")
        log.info("second")
        log.info("third")
        sink = RecordingSink()

        bridge.add_sink(sink)
    finally:
        log.removeHandler(bridge)

    assert sink.messages == ["second", "third"]


def test_the_cache_reports_what_it_dropped(log: logging.Logger) -> None:
    """The bridge counts the entries it discarded to stay within its cap.

    **Test steps:**

    * build a bridge capped at two and log three records
    * verify it reports one dropped
    """
    bridge = LogBridge(limit=2)
    bridge.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(bridge)
    try:
        log.info("first")
        log.info("second")
        log.info("third")
    finally:
        log.removeHandler(bridge)

    assert bridge.dropped == 1


def test_a_cap_below_one_still_holds_one(bridge: LogBridge) -> None:
    """A cap of zero or less is raised to one rather than making the cache useless.

    **Test steps:**

    * build a bridge with a cap of zero
    * verify its limit is one
    """
    del bridge  # this test builds its own

    assert LogBridge(limit=0).limit == 1


def test_lowering_the_cap_trims_the_cache_at_once(bridge: LogBridge, log: logging.Logger) -> None:
    """A cap lowered while running applies now, not at the next restart.

    **Test steps:**

    * log three records, then lower the cap to one
    * attach a sink
    * verify only the newest record was replayed, and two are reported dropped
    """
    log.info("first")
    log.info("second")
    log.info("third")

    bridge.limit = 1
    sink = RecordingSink()
    bridge.add_sink(sink)

    assert sink.messages == ["third"]
    assert bridge.dropped == 2


def test_raising_the_cap_keeps_what_is_cached(bridge: LogBridge, log: logging.Logger) -> None:
    """A cap raised while running drops nothing.

    **Test steps:**

    * log a record, then raise the cap
    * attach a sink
    * verify the record was replayed and nothing is reported dropped
    """
    log.info("kept")

    bridge.limit = DEFAULT_LOG_LIMIT * 2
    sink = RecordingSink()
    bridge.add_sink(sink)

    assert sink.messages == ["kept"]
    assert bridge.dropped == 0


def test_setting_the_same_cap_changes_nothing(bridge: LogBridge, log: logging.Logger) -> None:
    """Re-setting the cap to what it already is leaves the cache alone.

    **Test steps:**

    * log a record, then set the cap to its current value
    * attach a sink
    * verify the record is still there
    """
    log.info("kept")

    bridge.limit = bridge.limit
    sink = RecordingSink()
    bridge.add_sink(sink)

    assert sink.messages == ["kept"]


def test_clearing_the_cache_does_not_reset_what_was_dropped(log: logging.Logger) -> None:
    """The drop count survives a clear, because clearing brings nothing back.

    **Test steps:**

    * build a bridge capped at one and log two records, dropping one
    * clear the cache
    * verify it still reports one dropped
    """
    bridge = LogBridge(limit=1)
    log.addHandler(bridge)
    try:
        log.info("first")
        log.info("second")
    finally:
        log.removeHandler(bridge)

    bridge.clear_cache()

    assert bridge.dropped == 1


# endregion


# region failure


def test_a_record_that_cannot_be_formatted_is_reported_not_raised(
    bridge: LogBridge, log: logging.Logger, mocker: MockerFixture
) -> None:
    """A formatting failure goes to logging's own error path instead of into the caller.

    **Test steps:**

    * make the bridge's formatter raise
    * log a record and verify nothing propagated
    * verify handleError was called with that record
    """
    mocker.patch.object(bridge, "format", side_effect=ValueError("bad format string"))
    handle_error = mocker.patch.object(bridge, "handleError")

    log.info("unformattable")

    handle_error.assert_called_once()
    assert handle_error.call_args.args[0].getMessage() == "unformattable"


def test_a_record_that_cannot_be_formatted_is_not_cached(
    bridge: LogBridge, log: logging.Logger, mocker: MockerFixture
) -> None:
    """A record that failed to format reaches no sink, rather than reaching one half-built.

    **Test steps:**

    * make the bridge's formatter raise and log a record
    * attach a sink
    * verify it was given nothing
    """
    mocker.patch.object(bridge, "format", side_effect=ValueError("bad format string"))
    mocker.patch.object(bridge, "handleError")
    log.info("unformattable")
    sink = RecordingSink()

    bridge.add_sink(sink)

    assert sink.messages == []


# endregion


# region the protocol


def test_a_recording_sink_satisfies_the_protocol() -> None:
    """The sink contract is satisfied structurally, with no inheritance.

    **Test steps:**

    * check a plain class implementing the one method against the protocol
    * verify it satisfies it
    """
    assert isinstance(RecordingSink(), LogRecordSink)


# endregion
