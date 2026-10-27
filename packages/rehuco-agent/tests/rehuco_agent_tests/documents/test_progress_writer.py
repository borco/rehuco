"""Tests for the writer that runs a document's progress writes off the GUI thread (#316).

The thread is real here; each test holds the first write on an event, so which writes are waiting when another arrives
is made to happen, never waited for.
"""

import threading
from contextlib import nullcontext
from typing import Final

import shiboken6
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.progress_writer import ProgressWriter
from rehuco_core.access import LoadedRecord

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

WAIT_MS: Final = 5000
"""The longest a test waits for the writer's thread to answer."""


@fixture(name="inline_progress_writes", autouse=True)
def fixture_real_writer() -> None:
    """Leave the writer real: every other module's writes run inline, and this one is about the thread."""


@fixture(name="writer")
def fixture_writer(qtbot: QtBot, mocker: MockerFixture, delete_at_teardown: DeleteAtTeardown) -> ProgressWriter:
    """A writer whose rename barrier holds nothing, so the test controls what the thread waits for.

    :param qtbot: pytest-qt fixture.
    :param mocker: pytest-mock fixture.
    :param delete_at_teardown: deletes the bare writer when the test ends.
    :returns: the writer.
    """
    del qtbot
    coordinator = mocker.Mock()
    coordinator.holding.side_effect = nullcontext
    return delete_at_teardown(ProgressWriter(coordinator))


def test_a_write_is_answered_on_the_gui_thread_and_the_writer_is_then_idle(
    qtbot: QtBot, writer: ProgressWriter, mocker: MockerFixture
) -> None:
    """The work runs on the writer's thread, its outcome comes back here, and nothing is left waiting.

    **Test steps:**

    * submit a write that notes its thread and answers a record
    * wait for the answer
    * verify it ran off this thread, the answer is the record and arrived on this thread, and the writer is idle
    """
    record = mocker.Mock(spec=LoadedRecord)
    ran_on: list[int] = []
    answers: list[tuple[object, int]] = []

    def work() -> LoadedRecord:
        ran_on.append(threading.get_ident())
        return record

    writer.submit(("k",), work, lambda outcome: answers.append((outcome, threading.get_ident())))
    assert writer.busy is True
    qtbot.waitUntil(lambda: bool(answers), timeout=WAIT_MS)

    assert ran_on[0] != threading.get_ident()
    assert answers == [(record, threading.get_ident())]
    assert writer.busy is False


def test_a_write_still_waiting_is_replaced_by_a_later_one_of_its_key(qtbot: QtBot, writer: ProgressWriter) -> None:
    """A position every few seconds is the latest position, not a queue of them: the replaced write never runs and is
    never answered, and a write of another key is not touched.

    **Test steps:**

    * submit a write that holds the thread, then three more behind it: two of one key and one of another
    * let the first finish and wait for the rest
    * verify the earlier write of the shared key never ran, and the others ran in submission order
    """
    release = threading.Event()
    started = threading.Event()
    ran: list[str] = []
    answered: list[str] = []

    def holding() -> None:
        started.set()
        release.wait(WAIT_MS / 1000)
        ran.append("holding")

    def work(name: str):
        def run() -> None:
            ran.append(name)

        return run

    writer.submit(("hold",), holding, lambda _outcome: answered.append("holding"))
    assert started.wait(WAIT_MS / 1000)
    writer.submit(("position",), work("first"), lambda _outcome: answered.append("first"))
    writer.submit(("videos",), work("videos"), lambda _outcome: answered.append("videos"))
    writer.submit(("position",), work("second"), lambda _outcome: answered.append("second"))
    release.set()
    qtbot.waitUntil(lambda: len(answered) == 3 and not writer.busy, timeout=WAIT_MS)

    assert ran == ["holding", "videos", "second"]
    assert answered == ["holding", "videos", "second"]


def test_a_write_that_raises_is_answered_with_its_error_and_the_next_still_runs(
    qtbot: QtBot, writer: ProgressWriter
) -> None:
    """A failure is an outcome, not a dead thread: nothing is left waiting for an answer that never comes (#480).

    **Test steps:**

    * submit a write that raises, then one that succeeds
    * wait for both answers
    * verify the first was answered with its error and the second with its result
    """
    answers: list[object] = []

    def failing() -> None:
        raise OSError("the share does not answer")

    writer.submit(("a",), failing, answers.append)
    writer.submit(("b",), lambda: None, answers.append)
    qtbot.waitUntil(lambda: len(answers) == 2, timeout=WAIT_MS)

    assert isinstance(answers[0], OSError) and str(answers[0]) == "the share does not answer"
    assert answers[1] is None


def test_a_write_finishing_after_its_writer_is_gone_ends_quietly(qtbot: QtBot, writer: ProgressWriter) -> None:
    """A document closed while its last write is out leaves that write to finish and nobody to tell.

    **Test steps:**

    * submit a write that holds the thread, and delete the writer
    * let the write finish
    * verify it ran to its end
    """
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def holding() -> None:
        started.set()
        release.wait(WAIT_MS / 1000)
        finished.set()

    writer.submit(("hold",), holding, lambda _outcome: None)
    assert started.wait(WAIT_MS / 1000)
    shiboken6.delete(writer)
    release.set()

    qtbot.waitUntil(finished.is_set, timeout=WAIT_MS)
    qtbot.wait(50)


def test_an_answer_nobody_waits_for_is_dropped(writer: ProgressWriter) -> None:
    """A write replaced after its answer was posted is heard by no one.

    **Test steps:**

    * hand the writer an answer for a ticket it holds no waiter for
    * verify nothing happens
    """
    writer._ProgressWriter__on_answered(12345, None)  # type: ignore[attr-defined]  # pylint: disable=protected-access
