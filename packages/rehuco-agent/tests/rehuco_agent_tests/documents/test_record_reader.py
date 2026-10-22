"""Tests for ``RecordReader``: a record read on a daemon thread and answered on the GUI thread (#564).

``Records`` and the rename barrier are mocks -- each has its own tests -- and the thread is a stand-in that runs its
target only when a test says so, and the answer is delivered when the test sends the posted events: what is under test
is how the reader uses a thread, never the OS's threads.
"""

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock

import shiboken6
from borco_core.logging import LogScope
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents import record_reader
from rehuco_agent.documents.record_reader import RecordReader
from rehuco_agent.settings.identity_settings import IdentitySettings
from rehuco_core import RecordVersion, RehuDocument, RenameCoordinator
from rehuco_core.access import LoadedRecord, Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

PATH: Final = Path.cwd() / "fake" / "info.rehu"
KEY: Final = ResourceKey(PATH)


class FakeThread:
    """Stands in for ``threading.Thread``: keeps what it was built with, and runs its target only when asked.

    :param target: what the thread runs.
    :param args: its arguments.
    :param name: the thread's name.
    :param daemon: whether it is a daemon thread.
    """

    built: list[FakeThread] = []
    """Every stand-in built in the current test, in order."""

    def __init__(self, *, target: Callable[..., None], args: tuple[Any, ...], name: str, daemon: bool) -> None:
        self.target: Final = target
        self.args: Final = args
        self.name: Final = name
        self.daemon: Final = daemon
        self.started = False
        FakeThread.built.append(self)

    def start(self) -> None:
        """Note that the thread was started, running nothing."""
        self.started = True

    def run(self) -> None:
        """Run the target, as the thread would."""
        self.target(*self.args)


@fixture(name="threads")
def fixture_threads(mocker: MockerFixture) -> list[FakeThread]:
    """The reader's threads, each a :class:`FakeThread`.

    :param mocker: pytest-mock fixture.
    :returns: the threads built, in order.
    """
    FakeThread.built = []
    mocker.patch.object(record_reader, "threading", Mock(Thread=FakeThread, Event=threading.Event))
    return FakeThread.built


@fixture(name="records")
def fixture_records(mocker: MockerFixture) -> Any:
    """What the reader reads through, answering a tutorial titled ``Read``.

    :param mocker: pytest-mock fixture.
    :returns: the mock.
    """
    records = mocker.Mock(spec=Records)
    records.load.return_value = a_record()
    return records


@fixture(name="coordinator")
def fixture_coordinator(mocker: MockerFixture) -> Any:
    """The rename barrier the reads hold.

    :param mocker: pytest-mock fixture.
    :returns: the mock; its ``holding()`` is a context manager.
    """
    coordinator = mocker.Mock(spec=RenameCoordinator)
    coordinator.holding.return_value = MagicMock()
    return coordinator


@fixture(name="reader")
def fixture_reader(
    qapp: QApplication, threads: list[FakeThread], records: Any, coordinator: Any, delete_at_teardown: DeleteAtTeardown
) -> RecordReader:
    """The reader under test, over the mocked records and barrier, its threads stand-ins.

    :param qapp: the application, whose event dispatch delivers the answers.
    :param threads: the stand-in threads, patched in first.
    :param records: what it reads through.
    :param coordinator: the barrier it holds.
    :param delete_at_teardown: deletes the bare reader when the test ends.
    :returns: the reader.
    """
    del qapp, threads
    return delete_at_teardown(RecordReader(records, coordinator))


@fixture
def inline_record_reads() -> None:
    """Keep the real :meth:`RecordReader.read`: this module's own stands in for the conftest's autouse one, which
    answers every read inline -- the read itself is what is under test here."""


def a_record(*, failed: bool = False) -> LoadedRecord:
    """A record as ``Records`` answers one: a tutorial titled ``Read``, or the locked stub of one that failed.

    :param failed: answer the stub of a file that could not be read.
    :returns: the record.
    """
    if failed:
        stub = RehuDocument.locked_stub_for_error(PATH, FileNotFoundError(PATH))
        return LoadedRecord(stub, None, tuple(stub.lock_reasons), None)
    document = RehuDocument({"type": "Tutorial", "sources": [{"title": "Read", "primary": True}]}, PATH)
    return LoadedRecord(document, RecordVersion("meta", "read", ()), (), (1, 10))


def deliver() -> None:
    """Deliver what a read's thread posted to the GUI thread, as the event loop would."""
    QCoreApplication.sendPostedEvents()


def test_a_read_runs_on_a_daemon_thread_and_answers_on_the_gui_thread(
    mocker: MockerFixture, reader: RecordReader, threads: list[FakeThread], records: Any
) -> None:
    """A read is made on a daemon thread, under the identity set when it was asked for, and its record reaches the
    caller only through the GUI thread's event loop.

    **Test steps:**

    * set the identity, and ask for a read
    * verify one daemon thread named ``record-read`` was started, and nothing read yet
    * change the identity, then run the thread
    * verify the record was read under the identity set when asked, and nothing answered yet
    * deliver the posted events
    * verify the caller got the record, once
    """
    mocker.patch.object(
        record_reader,
        "shared_identity_settings",
        return_value=IdentitySettings(current_username="alice", unknown_username="strangers"),
    )
    answer = mocker.Mock()

    reader.read(KEY, answer)

    (thread,) = threads
    assert (thread.daemon, thread.name, thread.started) == (True, "record-read", True)
    records.load.assert_not_called()

    mocker.patch.object(record_reader, "shared_identity_settings", return_value=IdentitySettings())
    thread.run()

    records.load.assert_called_once_with(KEY, username="alice", unknown_username="strangers")
    answer.assert_not_called()

    deliver()

    answer.assert_called_once_with(records.load.return_value)


def test_a_read_holds_the_rename_barrier(
    reader: RecordReader, threads: list[FakeThread], records: Any, coordinator: Any
) -> None:
    """The file is read inside the rename barrier, so a rename never moves it from under the read.

    **Test steps:**

    * note the order the barrier is entered and left and the record read
    * read, and run the thread
    * verify the read happened between entering and leaving the barrier
    """
    order: list[str] = []
    holding = coordinator.holding.return_value
    holding.__enter__.side_effect = lambda *_: order.append("enter")
    holding.__exit__.side_effect = lambda *_: order.append("exit")
    records.load.side_effect = lambda *_args, **_kwargs: order.append("load") or a_record()

    reader.read(KEY, lambda _record: None)
    threads[0].run()

    assert order == ["enter", "load", "exit"]


def test_a_read_that_raises_is_answered_as_a_file_that_could_not_be_read(
    mocker: MockerFixture,
    reader: RecordReader,
    threads: list[FakeThread],
    records: Any,
    caplog: LogCaptureFixture,
) -> None:
    """A read that raises still answers -- a locked stub with nothing to save against -- and says why, so a document is
    never left waiting for good (#480).

    **Test steps:**

    * have the read raise, and read
    * run the thread and deliver
    * verify the caller got a locked stub with no version and no signature, and the failure was logged
    """
    records.load.side_effect = RuntimeError("boom")
    answer = mocker.Mock()

    with caplog.at_level(logging.ERROR, logger=record_reader.__name__):
        reader.read(KEY, answer)
        threads[0].run()
    deliver()

    (record,) = answer.call_args.args
    assert record.document.load_failed
    assert record.lock_reasons
    assert (record.version, record.signature) == (None, None)
    assert f"Could not read {PATH}" in caplog.messages


def test_nothing_is_answered_after_a_stop(
    mocker: MockerFixture, reader: RecordReader, threads: list[FakeThread]
) -> None:
    """A stopped reader answers no read still out, and starts none.

    **Test steps:**

    * read, then stop the reader
    * run the thread and deliver
    * verify nothing was answered
    * read again
    * verify no thread was started for it
    """
    answer = mocker.Mock()
    reader.read(KEY, answer)

    reader.stop()
    threads[0].run()
    deliver()

    answer.assert_not_called()

    reader.read(KEY, answer)

    assert len(threads) == 1


def test_a_record_posted_before_a_stop_is_not_answered(
    mocker: MockerFixture, reader: RecordReader, threads: list[FakeThread]
) -> None:
    """A read that finished just before the reader stopped has its record posted already; the stop still keeps it from
    whoever asked.

    **Test steps:**

    * read, and run the thread, so its record is posted
    * stop the reader, then deliver
    * verify nothing was answered
    """
    answer = mocker.Mock()
    reader.read(KEY, answer)
    threads[0].run()

    reader.stop()
    deliver()

    answer.assert_not_called()


def test_a_reader_gone_while_its_read_is_out_answers_nothing(
    mocker: MockerFixture, reader: RecordReader, threads: list[FakeThread]
) -> None:
    """A read that finishes after its reader was destroyed delivers nothing and raises nothing on its thread.

    **Test steps:**

    * read, then destroy the reader
    * run the thread
    * verify it returned, and nothing was answered
    """
    answer = mocker.Mock()
    reader.read(KEY, answer)
    shiboken6.delete(reader)

    threads[0].run()

    answer.assert_not_called()


def test_a_record_read_is_logged_under_its_own_scope(
    mocker: MockerFixture, records: Any, caplog: LogCaptureFixture
) -> None:
    """Reading a record says so, naming its type, in the record's own log (#200).

    **Test steps:**

    * read a record through the mocked records, noting the log scope opened
    * verify it was read with the identity given, the scope was the record's path, and the read was logged
    """
    scope = mocker.spy(LogScope, "open")

    with caplog.at_level(logging.INFO, logger=record_reader.__name__):
        record = RecordReader.read_record(records, KEY, username="alice", unknown_username="strangers")

    assert record is records.load.return_value
    records.load.assert_called_once_with(KEY, username="alice", unknown_username="strangers")
    scope.assert_called_once_with(PATH)
    assert f"Read {KEY} as tutorial" in caplog.messages


def test_a_record_that_could_not_be_read_is_not_logged_as_read(records: Any, caplog: LogCaptureFixture) -> None:
    """A file that could not be read is no read to log: ``Records`` logs why it failed.

    **Test steps:**

    * have the read answer a locked stub
    * verify no read was logged
    """
    records.load.return_value = a_record(failed=True)

    with caplog.at_level(logging.INFO, logger=record_reader.__name__):
        RecordReader.read_record(records, KEY, username="alice", unknown_username="strangers")

    assert not [message for message in caplog.messages if message.startswith("Read ")]


def test_the_identity_read_under_is_the_one_set_now(mocker: MockerFixture) -> None:
    """A read is made under the current and the unknown username the settings name now (#109).

    **Test steps:**

    * set the identity
    * verify the reader names it
    """
    mocker.patch.object(
        record_reader,
        "shared_identity_settings",
        return_value=IdentitySettings(current_username="alice", unknown_username="strangers"),
    )

    assert RecordReader.identity() == ("alice", "strangers")
