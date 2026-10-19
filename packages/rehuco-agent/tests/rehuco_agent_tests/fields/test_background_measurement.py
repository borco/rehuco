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


def test_the_runner_belongs_to_the_owner_and_not_to_the_row(qtbot: QtBot) -> None:
    """The runner is parented to the owner -- the document, which outlives every form built over it -- so the pool's
    callable is never the last to hold it, and it is never destroyed on a worker thread (#529).

    **Test steps:**

    * wire a row to a measurement, with an owner
    * verify the owner holds one runner, and the row none
    * press Compute and verify the answer reaches the row
    """
    owner = QObject()
    row = FakeRow()

    measure_in_background(row, lambda: 7, owner=owner)  # type: ignore[arg-type]

    assert len(owner.findChildren(BackgroundMeasurement)) == 1
    assert not row.findChildren(BackgroundMeasurement)
    row.compute_requested.emit()
    qtbot.waitUntil(lambda: row.shown == [7], timeout=2000)
    owner.deleteLater()
    row.deleteLater()


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
