"""Tests for the license lookup behind *Copy paths as JSON* (#688): on a daemon thread, the last copy asked for alone
answered, and nothing delivered once stopped.

What is written is :mod:`~rehuco_agent.rehuco.copied_paths`' subject: here a format answers what it was handed.
"""

import threading
from collections.abc import Iterable
from pathlib import Path
from queue import Queue
from typing import Final

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.copied_paths import CopiedPath
from rehuco_agent.rehuco.license_lookup import LicenseLookup

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

TIMEOUT: Final = 10_000
"""How long a wait gives the GUI thread to receive an answer, in milliseconds."""

GATE_TIMEOUT: Final = 120.0
"""How long a held format blocks before giving up on being released, in seconds -- a deadlock guard only."""


def named(copied: Iterable[CopiedPath]) -> str:
    """A format: each resource's license text, or a dash.

    :param copied: the resources.
    :returns: the names, joined by spaces.
    """
    return " ".join("-" if item.license is None else item.license.name for item in copied)


class Held:
    """A format that blocks until released, handing over the thread it runs on."""

    def __init__(self) -> None:
        self.release: Final = threading.Event()
        self.threads: Final = Queue[threading.Thread]()

    def thread(self) -> threading.Thread:
        """The thread the format runs on, waited for.

        :returns: the thread.
        """
        return self.threads.get(timeout=GATE_TIMEOUT)

    def write(self, copied: Iterable[CopiedPath]) -> str:
        """Hold, then write.

        :param copied: the resources.
        :returns: the text.
        """
        self.threads.put(threading.current_thread())
        self.release.wait(GATE_TIMEOUT)
        return f"held {named(copied)}"


@fixture(name="lookup")
def fixture_lookup(delete_at_teardown: DeleteAtTeardown) -> LicenseLookup:
    """A lookup of its own, deleted when the test ends.

    :param delete_at_teardown: deletes the lookup when the test ends.
    :returns: the lookup.
    """
    return delete_at_teardown(LicenseLookup())


def test_a_text_is_named_only_where_it_is_there(qtbot: QtBot, lookup: LicenseLookup, tmp_path: Path) -> None:
    """**Test steps:**

    * look up a resource whose text is there, one whose text is not, and one with no place for one
    * verify only the first names it, in order
    """
    (tmp_path / "a.rehuterms").write_text("x", encoding="utf-8")
    copied = [
        CopiedPath(tmp_path, tmp_path / "a.rehuterms"),
        CopiedPath(tmp_path, tmp_path / "b.rehuterms"),
        CopiedPath(tmp_path),
    ]

    with qtbot.waitSignal(lookup.written, timeout=TIMEOUT) as written:
        lookup.start(copied, named)

    assert written.args == ["a.rehuterms - -"]


def test_a_lookup_runs_on_a_daemon_thread_so_quitting_never_waits_for_a_share(
    qtbot: QtBot, lookup: LicenseLookup
) -> None:
    """**Test steps:**

    * hold a lookup and take the thread it runs on
    * verify it is a daemon, then release it and verify it answers
    """
    held = Held()

    lookup.start([CopiedPath(Path("a"))], held.write)

    assert held.thread().daemon
    with qtbot.waitSignal(lookup.written, timeout=TIMEOUT) as written:
        held.release.set()
    assert written.args == ["held -"]


def test_only_the_last_copy_asked_for_is_answered(qtbot: QtBot, lookup: LicenseLookup) -> None:
    """**Test steps:**

    * hold a lookup, start another and let it answer, then release the first and let its thread end
    * verify only the second was answered
    * hold a third, discard it and release it, and verify it was not answered either
    """
    answers: list[str] = []
    lookup.written.connect(answers.append)
    first, third = Held(), Held()

    lookup.start([CopiedPath(Path("a"))], first.write)
    with qtbot.waitSignal(lookup.written, timeout=TIMEOUT):
        lookup.start([CopiedPath(Path("b"))], named)
    first.release.set()
    first.thread().join(GATE_TIMEOUT)
    lookup.start([CopiedPath(Path("c"))], third.write)
    lookup.discard()
    third.release.set()
    third.thread().join(GATE_TIMEOUT)
    with qtbot.waitSignal(lookup.written, timeout=TIMEOUT):
        lookup.start([CopiedPath(Path("d"))], named)

    assert answers == ["-", "-"]


def test_nothing_is_asked_or_delivered_once_stopped(
    qtbot: QtBot, lookup: LicenseLookup, mocker: MockerFixture, tmp_path: Path
) -> None:
    """**Test steps:**

    * hold a lookup, stop, and let it go on: verify it delivers nothing
    * start one more and verify no disk was asked, and it delivers nothing either
    """
    answers: list[str] = []
    lookup.written.connect(answers.append)
    held, after = Held(), Held()
    lookup.start([CopiedPath(tmp_path)], held.write)
    thread = held.thread()

    lookup.stop()
    held.release.set()
    thread.join(GATE_TIMEOUT)
    asked = mocker.patch("rehuco_agent.rehuco.license_lookup.os.path.isfile")
    after.release.set()
    lookup.start([CopiedPath(tmp_path, tmp_path / "a.rehuterms")], after.write)
    after.thread().join(GATE_TIMEOUT)
    qtbot.wait(50)

    asked.assert_not_called()
    assert not answers


def test_an_answer_on_its_way_as_the_lookups_stop_is_not_passed_on(qtbot: QtBot, lookup: LicenseLookup) -> None:
    """**Test steps:**

    * let a lookup answer without running the GUI thread's events, then stop and run them
    * verify nothing was passed on
    """
    answers: list[str] = []
    lookup.written.connect(answers.append)
    held = Held()
    held.release.set()
    lookup.start([CopiedPath(Path("a"))], held.write)
    held.thread().join(GATE_TIMEOUT)

    lookup.stop()
    qtbot.wait(50)

    assert not answers


def test_a_lookup_whose_owner_is_gone_ends_quietly(
    lookup: LicenseLookup, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """**Test steps:**

    * make the answer's emit fail as on a deleted object, and look up
    * verify the thread ended and nothing was logged
    """
    emitted = mocker.patch.object(lookup, "_LicenseLookup__answered")
    emitted.emit.side_effect = RuntimeError("deleted")
    held = Held()
    held.release.set()

    lookup.start([CopiedPath(Path("a"))], held.write)
    held.thread().join(GATE_TIMEOUT)

    emitted.emit.assert_called_once()
    assert not caplog.records
