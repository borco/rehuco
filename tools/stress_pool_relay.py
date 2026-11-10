"""Stress the race a pool job's answer runs against the GUI thread deleting its owner
([[appendices.code-conventions#worker-threads]]).

Each round starts a few pool jobs for a runner, then deletes the runner's parent on the GUI thread while the jobs are
answering -- a document closed while its videos are listed. Two runners take the same treatment:

- ``direct`` -- :class:`DirectRunner`, a pool job emitting on its owner's own signal, as every loader did before
  :class:`~rehuco_agent.pool_relay.PoolRelay`. The process dies of an access violation (a segmentation fault on
  Linux) within a few thousand rounds: the ``RuntimeError`` guard around the emit catches only an owner deleted
  *before* the emit, never one deleted during it.
- ``relay`` -- the agent's own :class:`~rehuco_agent.documents.latest_runner.LatestRunner`, which answers through the
  relay. It survives every round, and no answer is delivered for an owner that is gone.

Run it when a loader's hand-off to the GUI thread is changed: ``relay`` must survive, and ``direct`` dying beside it
shows the stress still bites on this machine::

    uv run python tools/stress_pool_relay.py relay
    uv run python tools/stress_pool_relay.py direct
"""

import argparse
import faulthandler
import sys
from collections.abc import Callable
from typing import Final

import shiboken6
from PySide6.QtCore import QCoreApplication, QObject, QThreadPool, Signal, Slot
from rehuco_agent.documents.latest_runner import LatestRunner

DEFAULT_ROUNDS: Final = 20000
JOBS_PER_ROUND: Final = 4
EVENTS_EVERY: Final = 50
"""Rounds between two runs of the event loop: the answers posted meanwhile are for owners already deleted."""


class DirectRunner(QObject):
    """The hand-off this stress exists to show unsafe: the pool thread emits on the runner itself.

    :param parent: optional Qt parent.
    """

    read = Signal(str, object)
    """``(tag, result)``, as :attr:`~rehuco_agent.documents.latest_runner.LatestRunner.read`."""

    reported = Signal(int, str, object)
    """``(serial, tag, result)``, emitted on the pool thread -- on an object the GUI thread may be deleting."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__serial = 0
        self.reported.connect(self.__deliver)

    def start(self, tag: str, work: Callable[[], object]) -> None:
        """Run ``work`` on a pool thread.

        :param tag: what the work is about.
        :param work: the callable.
        """
        self.__serial += 1
        serial = self.__serial
        QThreadPool.globalInstance().start(lambda: self.__run(serial, tag, work))

    def __run(self, serial: int, tag: str, work: Callable[[], object]) -> None:
        """Run the work and emit its result on this runner, guarded the way the loaders were.

        :param serial: the run's serial.
        :param tag: what the work is about.
        :param work: the callable.
        """
        result = work()
        try:
            self.reported.emit(serial, tag, result)
        except RuntimeError:  # deleted before the emit; deleted during it is the crash
            pass

    @Slot(int, str, object)
    def __deliver(self, serial: int, tag: str, result: object) -> None:
        """Pass the last run's result on (GUI thread).

        :param serial: the run's serial.
        :param tag: what the work is about.
        :param result: what it came to.
        """
        if serial == self.__serial:
            self.read.emit(tag, result)


RUNNERS: Final[dict[str, type[DirectRunner] | type[LatestRunner]]] = {"direct": DirectRunner, "relay": LatestRunner}


def spin(count: int) -> int:
    """Burn a little time, a different amount per call, so the delete lands at every point of the answer.

    :param count: how many additions to make.
    :returns: their sum.
    """
    return sum(range(count))


def stress(mode: str, rounds: int) -> int:
    """Delete each round's owner while its jobs answer.

    :param mode: which runner, a key of :data:`RUNNERS`.
    :param rounds: how many owners to make and delete.
    :returns: how many answers were delivered.
    """
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    make = RUNNERS[mode]
    answered: list[str] = []
    for index in range(rounds):
        parent = QObject()
        runner = make(parent)
        runner.read.connect(lambda tag, _result: answered.append(tag))
        for _ in range(JOBS_PER_ROUND):
            runner.start("stress", lambda count=index % 97: spin(count))
        spin((index * 7) % 113)
        shiboken6.delete(parent)
        if index % EVENTS_EVERY == 0:
            app.processEvents()
    QThreadPool.globalInstance().waitForDone()
    app.processEvents()
    return len(answered)


def main(argv: list[str] | None = None) -> int:
    """Run the stress and say it survived; a crash says the rest.

    :param argv: the command line, without the program name; ``None`` for the process's own.
    :returns: the exit code, 0 when every round was survived.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=sorted(RUNNERS), help="which runner to stress")
    parser.add_argument("rounds", nargs="?", type=int, default=DEFAULT_ROUNDS, help="owners to make and delete")
    args = parser.parse_args(argv)
    faulthandler.enable()
    answered = stress(args.mode, args.rounds)
    print(f"{args.mode}: survived {args.rounds} rounds, {answered} answers delivered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
