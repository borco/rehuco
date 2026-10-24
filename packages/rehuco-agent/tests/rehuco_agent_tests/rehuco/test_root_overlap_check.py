"""Tests for the comparison of roots through links run off the GUI thread (#498): each answer arrives on the GUI thread
with its serial, a check that raises is answered empty, and nothing is delivered once stopped.

What the comparison finds is ``RootOverlap``'s subject, tested in core: here it is patched.
"""

import logging
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Final
from unittest.mock import MagicMock

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_overlap_check import RootOverlapCheck
from rehuco_core import RootOverlap

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.mapped_roots import mapped_root

WAIT_TIMEOUT_MS: Final = 10_000
"""How long a wait gives the GUI thread to receive an answer."""

GATE_TIMEOUT: Final = 120.0
"""How long a gated check blocks before giving up on being released, in seconds -- a deadlock guard only."""

FOLDER: Final = Path.cwd() / "fake" / "library"
ROOTS: Final = (
    mapped_root(FOLDER / "tutorials", "tutorials"),
    mapped_root(FOLDER / "packs", "packs"),
)
OVERLAP: Final = RootOverlap(ROOTS[0], FOLDER / "tutorials" / "python", encloses=True)


@fixture(name="check")
def fixture_check(delete_at_teardown: DeleteAtTeardown) -> RootOverlapCheck:
    """A check of its own, deleted when the test ends.

    :param delete_at_teardown: deletes the check when the test ends.
    :returns: the check.
    """
    return delete_at_teardown(RootOverlapCheck())


@dataclass(frozen=True)
class Gate:
    """Holds a candidate's comparison until released, and hands over the thread each one runs on."""

    release: threading.Event = field(default_factory=threading.Event)
    """Lets every held comparison answer."""

    threads: Queue[threading.Thread] = field(default_factory=Queue)
    """The thread of each comparison, put there by the comparison itself once it runs."""

    def entered(self) -> threading.Thread:
        """The thread of the next comparison to reach the gate, waited for.

        :returns: the thread -- the check's own, whatever else runs under the same name.
        """
        return self.threads.get(timeout=GATE_TIMEOUT)


@fixture(name="gate")
def fixture_gate(mocker: MockerFixture) -> Generator[Gate]:
    """Make the comparison of a candidate wait until the test lets it answer -- the overlap -- so the state a check
    passes through can be looked at.

    :param mocker: pytest-mock fixture.
    :yields: the gate, released at teardown.
    """
    gate = Gate()

    def find_resolved(*_args: object) -> RootOverlap:
        gate.threads.put(threading.current_thread())
        gate.release.wait(GATE_TIMEOUT)
        return OVERLAP

    mocker.patch.object(RootOverlap, "find_resolved", side_effect=find_resolved)
    yield gate
    gate.release.set()


def test_a_candidates_check_answers_on_the_gui_thread_with_its_serial(
    mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck
) -> None:
    """The comparison runs on another thread, over a copy of the roots and the roots to skip; what it found reaches the
    GUI thread with the serial :meth:`~RootOverlapCheck.find` returned.

    **Test steps:**

    * make the comparison note its thread and answer an overlap, and note the thread the answer is received on
    * check a candidate against two roots, skipping the second
    * verify the answer carries the serial and the overlap, came on the GUI thread, and the comparison ran elsewhere
      over the candidate, the roots and the skipped root
    """
    threads: list[threading.Thread] = []

    def find_resolved(*_args: object) -> RootOverlap:
        threads.append(threading.current_thread())
        return OVERLAP

    find = mocker.patch.object(RootOverlap, "find_resolved", side_effect=find_resolved)
    received: list[threading.Thread] = []
    receive = MagicMock(side_effect=lambda *_: received.append(threading.current_thread()))
    check.answered.connect(receive)

    with qtbot.waitSignal(check.answered, timeout=WAIT_TIMEOUT_MS) as answer:
        serial = check.find(OVERLAP.other, list(ROOTS), [ROOTS[1].root_id])

    assert answer.args == [serial, (OVERLAP,)]
    assert received == [threading.main_thread()]
    assert len(threads) == 1
    assert threads[0] is not threading.main_thread()
    assert find.call_args.args == (OVERLAP.other, ROOTS, frozenset({ROOTS[1].root_id}))


def test_a_candidate_that_overlaps_nothing_is_answered_empty(
    mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck
) -> None:
    """No overlap found is an empty answer, not a missing one -- the caller waits on it to add the root.

    **Test steps:**

    * make the comparison find nothing and check a candidate
    * verify the answer is empty
    """
    mocker.patch.object(RootOverlap, "find_resolved", return_value=None)

    with qtbot.waitSignal(check.answered, timeout=WAIT_TIMEOUT_MS) as answer:
        serial = check.find(FOLDER / "refs", ROOTS, ())

    assert answer.args == [serial, ()]


def test_comparing_a_files_roots_answers_every_pair_found(
    mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck
) -> None:
    """:meth:`~RootOverlapCheck.among` compares the roots with each other, and answers what that found.

    **Test steps:**

    * make the comparison among roots answer two overlaps, and compare the roots, skipping the first
    * verify the answer carries both, and the comparison was asked over the roots and the skipped root
    """
    second = RootOverlap(ROOTS[1], FOLDER, encloses=False)
    among = mocker.patch.object(RootOverlap, "among_resolved", return_value=(OVERLAP, second))

    with qtbot.waitSignal(check.answered, timeout=WAIT_TIMEOUT_MS) as answer:
        serial = check.among(list(ROOTS), {ROOTS[0].root_id})

    assert answer.args == [serial, (OVERLAP, second)]
    assert among.call_args.args == (ROOTS, frozenset({ROOTS[0].root_id}))


def test_a_check_that_raises_is_logged_and_answered_empty(
    mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck, caplog: LogCaptureFixture
) -> None:
    """A failure on the thread would only be printed, and leave the caller waiting: it is logged, and answered as
    nothing found -- the spelled comparison still stands.

    **Test steps:**

    * make the comparison raise, and compare the roots
    * verify an empty answer, and the failure logged
    """
    mocker.patch.object(RootOverlap, "among_resolved", side_effect=OSError("share gone"))

    with caplog.at_level(logging.ERROR), qtbot.waitSignal(check.answered, timeout=WAIT_TIMEOUT_MS) as answer:
        serial = check.among(ROOTS, ())

    assert answer.args == [serial, ()]
    assert "Comparing roots through their links failed" in caplog.text


def test_each_check_gets_a_serial_of_its_own(mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck) -> None:
    """Serials grow, so an answer is told from an earlier one by its serial.

    **Test steps:**

    * make the comparison find nothing, and start two checks
    * verify the second serial is greater, and both answers arrive, each with its own
    """
    mocker.patch.object(RootOverlap, "find_resolved", return_value=None)
    answered = MagicMock()
    check.answered.connect(answered)

    first = check.find(FOLDER / "refs", ROOTS, ())
    second = check.find(FOLDER / "more", ROOTS, ())

    assert second > first
    qtbot.waitUntil(lambda: answered.call_count == 2, timeout=WAIT_TIMEOUT_MS)
    assert sorted(call.args for call in answered.call_args_list) == [(first, ()), (second, ())]


def test_a_check_stopped_before_it_answers_delivers_nothing(qtbot: QtBot, check: RootOverlapCheck, gate: Gate) -> None:
    """Stopped while the comparison still waits -- the window closing over a switched-off server -- the check's thread
    ends without a word.

    **Test steps:**

    * start a check held by the gate, stop, then let it answer and wait for its thread to end
    * verify nothing was answered
    """
    answered = MagicMock()
    check.answered.connect(answered)
    check.find(FOLDER / "refs", ROOTS, ())
    thread = gate.entered()

    check.stop()
    gate.release.set()
    thread.join(GATE_TIMEOUT)
    qtbot.wait(50)

    assert not thread.is_alive()
    answered.assert_not_called()


def test_an_answer_already_on_its_way_when_stopped_is_dropped(
    qtbot: QtBot, check: RootOverlapCheck, gate: Gate
) -> None:
    """The answer is queued to the GUI thread; stopped before it is received there, it goes no further.

    **Test steps:**

    * start a check held by the gate, let it answer and wait for its thread to end, the answer still queued
    * stop, then let the GUI thread receive it
    * verify nothing was answered
    """
    answered = MagicMock()
    check.answered.connect(answered)
    check.find(FOLDER / "refs", ROOTS, ())
    thread = gate.entered()
    gate.release.set()
    thread.join(GATE_TIMEOUT)

    check.stop()
    qtbot.wait(50)

    assert not thread.is_alive()
    answered.assert_not_called()


def test_an_owner_gone_between_the_test_and_the_answer_is_not_an_error(
    mocker: MockerFixture, qtbot: QtBot, check: RootOverlapCheck, gate: Gate
) -> None:
    """The check's object deleted just as its thread answers makes the emit raise; the thread swallows it.

    **Test steps:**

    * start a check held by the gate, and make its relay raise as a deleted object's does
    * let it answer and wait for its thread to end
    * verify the relay was tried, the thread ended, and nothing was answered
    """
    answered = MagicMock()
    check.answered.connect(answered)
    check.find(FOLDER / "refs", ROOTS, ())
    thread = gate.entered()
    relayed = mocker.patch.object(check, "_RootOverlapCheck__relayed")
    relayed.emit.side_effect = RuntimeError("Internal C++ object already deleted.")

    gate.release.set()
    thread.join(GATE_TIMEOUT)
    qtbot.wait(50)

    assert not thread.is_alive()
    relayed.emit.assert_called_once()
    answered.assert_not_called()
