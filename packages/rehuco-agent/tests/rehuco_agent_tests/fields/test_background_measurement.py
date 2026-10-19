"""Tests for BackgroundMeasurement and measure_in_background: who owns the runner Compute starts (#529)."""

import threading

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool, Signal
from pytest import CaptureFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.background_measurement import BackgroundMeasurement, measure_in_background


class FakeRow(QObject):
    """A `MeasureRow`: a Compute request going out and the answer coming back."""

    compute_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[int | None] = []

    def show_measurement(self, value: int | None) -> None:
        """Remember the answer.

        :param value: what was measured.
        """
        self.shown.append(value)


def test_the_runner_belongs_to_its_row_and_goes_with_it(qtbot: QtBot) -> None:
    """The runner is the row's child: the pool's callable is never the last to hold it, so it is never destroyed on a
    worker thread, and a form rebuild taking the row takes the runner too, rather than leaving one behind per row
    until the document closes (#529).

    **Test steps:**

    * wire a row to a measurement
    * verify the row holds one runner
    * press Compute and verify the answer reaches the row
    * delete the row and verify the runner went with it
    """
    row = FakeRow()

    measure_in_background(row, lambda: 7)  # type: ignore[arg-type]

    runners = row.findChildren(BackgroundMeasurement)
    assert len(runners) == 1
    row.compute_requested.emit()
    qtbot.waitUntil(lambda: row.shown == [7], timeout=2000)
    destroyed: list[bool] = []
    runners[0].destroyed.connect(lambda: destroyed.append(True))
    row.deleteLater()
    qtbot.waitUntil(lambda: destroyed == [True], timeout=2000)


def test_a_measurement_outliving_its_runner_reports_into_nothing(qtbot: QtBot, capfd: CaptureFixture[str]) -> None:
    """A runner deleted while its measurement runs -- the document closed -- leaves the worker an answer for nobody;
    the emit on the deleted runner raises, and is swallowed on the pool thread rather than printed by it (#529).

    **Test steps:**

    * start a measurement that waits, and delete its runner while it does
    * let the measurement finish and the pool settle
    * verify nothing was raised on the pool thread
    """
    del qtbot
    release = threading.Event()
    measurement = BackgroundMeasurement()

    def measure() -> int:
        release.wait(2)
        return 7

    measurement.start(measure)
    measurement.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    release.set()

    assert QThreadPool.globalInstance().waitForDone(2000)
    assert "RuntimeError" not in capfd.readouterr().err
