"""Runs work off the GUI thread and answers only the last asked ([[plugins#in-app-player]], #317)."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot


class LatestRunner(QObject):
    """Runs a callable on the global thread pool and reports its result back on the GUI thread, dropping the answer of
    any work a later :meth:`start` or :meth:`discard` has outdated.

    One per kind of work a player asks for repeatedly -- a video's format, a tutorial's list of videos -- which every
    request reuses: a runner made per request would leave a child on the player for as long as it lives
    ([[appendices.code-conventions#worker-threads]]). Starting again outdates the one before, so a slow read of a video
    already left never decides what the player does about the next.

    The answer is judged **on the GUI thread**, after the event that carried it, so a worker that posts it a moment
    before the player moves on is still dropped -- the shape
    :class:`~rehuco_agent.fields.background_measurement.BackgroundMeasurement` documents.

    The work runs on a pool thread, so it touches no widget and no ``QObject``.

    :param parent: optional Qt parent.
    """

    read = Signal(str, object)
    """Fires on the GUI thread with ``(tag, result)`` when the work last started has finished: the tag it was started
    with, and what it returned -- or the exception it raised, which a pool job must never let escape
    ([[appendices.code-conventions#worker-threads]], #480)."""

    reported = Signal(int, str, object)
    """The worker's report, ``(serial, tag, result)``: emitted on the pool thread, delivered to :meth:`__deliver` on
    this object's own thread. Internal; connect to :attr:`read`."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__serial = 0
        self.reported.connect(self.__deliver)

    def start(self, tag: str, work: Callable[[], object]) -> None:
        """Run ``work``, outdating every run started before.

        :param tag: what the work is about, handed back with the answer.
        :param work: the callable, run on a pool thread.
        """
        self.__serial += 1
        serial = self.__serial
        QThreadPool.globalInstance().start(lambda: self.__run(serial, tag, work))

    def discard(self) -> None:
        """Drop the answer of every run started so far, as the player does when it stops."""
        self.__serial += 1

    def __run(self, serial: int, tag: str, work: Callable[[], object]) -> None:
        """Run the work on the worker thread and post what it came to.

        :param serial: the run's serial, for :meth:`__deliver` to judge.
        :param tag: what the work is about.
        :param work: the callable.
        """
        result: object
        try:
            result = work()
        except Exception as error:  # pylint: disable=broad-exception-caught
            # a pool job never lets an exception escape: the pool swallows it and no answer ever arrives
            # ([[appendices.code-conventions#worker-threads]], #480) -- the failure is the answer
            result = error
        try:
            self.reported.emit(serial, tag, result)
        except RuntimeError:  # this runner was deleted while the work ran
            pass

    @Slot(int, str, object)
    def __deliver(self, serial: int, tag: str, result: object) -> None:
        """Pass a worker's report on as :attr:`read` unless a later :meth:`start` or :meth:`discard` outdated it.

        :param serial: the run's serial.
        :param tag: what the work is about.
        :param result: what it came to.
        """
        if serial == self.__serial:
            self.read.emit(tag, result)
