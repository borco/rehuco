"""Runs a field's measurement off the GUI thread ([[plugins#field-toolkit]], #223)."""

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QThreadPool, Signal, SignalInstance


class BackgroundMeasurement(QObject):
    """Runs one measurement on a worker thread and reports the result back on the GUI thread (#223).

    A size scan is a ``stat`` per file over a whole directory tree, on a resource that lives on an SMB
    mount ([[packaging-deployment#ts230-as-nas]]) -- seconds of round trips for a large tutorial. Running
    it inline would freeze the window for that whole time, so the measurement goes to
    ``QThreadPool.globalInstance()`` and its answer comes back through :attr:`finished`, which is a
    **queued** connection because the emit happens on the pool's thread and the receiver lives on the
    GUI one. The caller's job is to disable what must not be pressed twice while it runs.

    Deliberately tiny, and **an interim owner**. The task-queue engine (#201) and its dock (#202) are
    where every background measurement is headed: each scan becomes a queue job, so it can be watched
    while it runs, paused, resumed, cancelled and reordered against the checksum runs beside it (#204),
    instead of being a thing that has quietly started and can only be waited out. That also supersedes
    the app-wide *"the disk is busy"* flag tc4 carried -- one queue is a better answer than one boolean.
    What this class owes that future is the shape it already has: the measurement is a plain callable
    handed in, the result comes back as one signal, and the widget knows neither -- so moving the middle
    from a thread pool to the queue touches this file and nothing else.

    Until then, a per-row busy state is what the measure rows need and all this builds.

    The measurement callable runs on the worker thread, so it must touch no widget and no ``QObject``:
    what it may read is the filesystem and plain Python state (a `pathlib.Path`, a settings dataclass).

    :param parent: optional Qt parent.
    """

    finished = Signal(object)
    """Fires on the GUI thread with the measurement's result -- an ``int``, or ``None`` when nothing
    could be measured. Fires exactly once per :meth:`start`, **including when the measurement raised**,
    so a caller that disabled its controls always gets them back."""

    def start(self, measure: Callable[[], int | None]) -> None:
        """Run ``measure`` on a pool thread and emit :attr:`finished` with what it returns.

        Returns immediately; nothing is awaited here. Starting a second measurement before the first
        finishes runs both -- the caller keeps that from happening by disabling the control that starts
        one (every measure row disables Compute for exactly as long as a scan is in flight).

        :param measure: the measurement, called on a worker thread.
        """
        QThreadPool.globalInstance().start(lambda: self.__run(measure))

    def __run(self, measure: Callable[[], int | None]) -> None:
        """Call ``measure`` on the worker thread and emit its result, raise or no raise.

        The blanket catch is the point rather than a shortcut: this runs on a pool thread, where an
        escaping exception is printed and swallowed by the pool -- and the ``finished`` that never
        arrived would leave the caller's controls disabled for the rest of the document's life, turning
        a failed scan into a permanently dead button. A failure is reported as *nothing measured*, which
        is the same answer the enumeration already gives for an unreadable directory.

        :param measure: the measurement to run.
        """
        try:
            result = measure()
        except Exception:  # pylint: disable=broad-exception-caught
            result = None
        self.finished.emit(result)


class MeasureRow(Protocol):
    """What a measure row offers a field that wants to measure for it ([[plugins#field-toolkit]]).

    Deliberately just the two members :func:`measure_in_background` touches -- a request going out and an
    answer coming back -- so the wiring is written once rather than per field. Every row that has them is
    a :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit` today (#224), which this deliberately does
    **not** name: what the wiring needs is the two members, not that one class, and a plugin's own row
    satisfying them is wired by the same call.
    """

    @property
    def compute_requested(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Fires when the row's ``Compute`` is pressed; the row is already busy by then."""

    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state.

        :param value: what was measured, or ``None`` when nothing could be.
        """


def measure_in_background(row: MeasureRow, measure: Callable[[], int | None]) -> None:
    """Wire ``row``'s ``Compute`` to ``measure``, run off the GUI thread ([[plugins#field-toolkit]], #223).

    The runner is deliberately **not** parented to the row: a running measurement holds it through the
    callable it handed the thread pool, and a parented one would have its C++ half deleted under that
    thread the moment a form rebuild (a type switch, a revert) took the row. Unparented, it is kept alive
    by the connection made here for as long as the row lives, and by the pool's callable for as long as
    the measurement runs, and is collected once both are done. Its result lands on a bound slot of the
    row, which Qt drops on destruction -- so a measurement outliving its row reports into nothing rather
    than into a deleted widget.

    :param row: the measure row to wire, which owns its own busy state.
    :param measure: the measurement, called on a worker thread on every ``Compute``.
    """
    measurement = BackgroundMeasurement()
    measurement.finished.connect(row.show_measurement)
    row.compute_requested.connect(lambda: measurement.start(measure))
