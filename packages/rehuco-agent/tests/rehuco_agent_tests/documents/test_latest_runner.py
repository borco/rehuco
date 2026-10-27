"""Tests for the runner that does a player's background reads -- a video's format, a tutorial's list of videos -- and
answers only the last asked (#317)."""

import threading
from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from pytest import CaptureFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.latest_runner import LatestRunner

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

WAIT_MS: Final = 2000


def settle() -> None:
    """Let every run the pool has started finish, and the answers it posted be delivered."""
    assert QThreadPool.globalInstance().waitForDone(WAIT_MS)
    QCoreApplication.sendPostedEvents()


def answers_of(runner: LatestRunner) -> list[tuple[str, object]]:
    """Collect what a runner answers.

    :param runner: the runner.
    :returns: the list its ``(tag, result)`` pairs are appended to.
    """
    answers: list[tuple[str, object]] = []
    runner.read.connect(lambda tag, result: answers.append((tag, result)))
    return answers


def test_the_work_runs_on_the_pool_and_is_answered_with_its_tag(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """**Test steps:**

    * start work that notes its thread and returns a list
    * wait for the answer
    * verify it carries the tag and the result, and the work ran off this thread
    """
    runner = delete_at_teardown(LatestRunner())
    ran_on: list[int] = []

    def work() -> list[str]:
        ran_on.append(threading.get_ident())
        return ["a.mp4", "b.mp4"]

    with qtbot.waitSignal(runner.read, timeout=WAIT_MS) as answer:
        runner.start("list", work)

    assert answer.args == ["list", ["a.mp4", "b.mp4"]]
    assert ran_on != [threading.get_ident()]


def test_work_that_raises_is_answered_with_its_error(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> None:
    """A failure is the answer, not silence, which would leave whoever asked waiting.

    **Test steps:**

    * start work that raises
    * wait for the answer
    * verify the result is the exception
    """
    runner = delete_at_teardown(LatestRunner())
    error = RuntimeError("share gone")

    def work() -> object:
        raise error

    with qtbot.waitSignal(runner.read, timeout=WAIT_MS) as answer:
        runner.start("list", work)

    assert answer.args == ["list", error]


def test_only_the_last_run_started_is_answered(delete_at_teardown: DeleteAtTeardown) -> None:
    """A slow run already left behind must never decide what happens next -- whichever finishes first, the answer is
    judged on the GUI thread against the last one started.

    **Test steps:**

    * start one piece of work, then another
    * let both finish
    * verify only the second was answered
    """
    runner = delete_at_teardown(LatestRunner())
    answers = answers_of(runner)

    runner.start("first", lambda: 1)
    runner.start("second", lambda: 2)
    settle()

    assert answers == [("second", 2)]


def test_a_discarded_run_is_never_answered(delete_at_teardown: DeleteAtTeardown) -> None:
    """What the player does as it stops: what it was reading is no longer in front of anyone.

    **Test steps:**

    * start work and discard the runner's runs
    * let it finish
    * verify nothing was answered
    """
    runner = delete_at_teardown(LatestRunner())
    answers = answers_of(runner)

    runner.start("first", lambda: 1)
    runner.discard()
    settle()

    assert not answers


def test_a_run_outliving_its_runner_reports_into_nothing(capfd: CaptureFixture[str]) -> None:
    """A runner deleted while its work runs -- the player gone with its document -- leaves the worker an answer for
    nobody; the emit on the deleted runner raises, and is swallowed on the pool thread rather than printed by it.

    **Test steps:**

    * start work that waits, and delete its runner while it does
    * let the work finish and the pool settle
    * verify nothing was raised on the pool thread
    """
    release = threading.Event()
    runner = LatestRunner()
    work: Callable[[], object] = lambda: release.wait(WAIT_MS / 1000)  # noqa: E731

    runner.start("first", work)
    runner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    release.set()

    assert QThreadPool.globalInstance().waitForDone(WAIT_MS)
    assert "RuntimeError" not in capfd.readouterr().err
