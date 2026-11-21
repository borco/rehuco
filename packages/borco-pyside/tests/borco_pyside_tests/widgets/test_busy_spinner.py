"""Tests for BusySpinner: an arc that turns while something is waited for."""

from borco_pyside.widgets import BusySpinner
from borco_pyside.widgets.busy_spinner import SPINNER_INTERVAL_MS, SPINNER_SIZE, SPINNER_STEP_DEGREES
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPalette
from pytestqt.qtbot import QtBot


def painted(spinner: BusySpinner) -> bool:
    """Whether a spinner paints anything in its text color.

    :param spinner: the spinner, whose text color is set to pure red here.
    :returns: whether any pixel of it carries that color.
    """
    palette = spinner.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("red"))
    palette.setColor(QPalette.ColorRole.Window, QColor("white"))
    spinner.setPalette(palette)
    spinner.setAutoFillBackground(True)
    image = spinner.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    reds = (image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height()))
    return any(color.red() > 200 and color.green() < 80 and color.blue() < 80 for color in reds)


def test_a_spinner_is_a_fixed_square_that_starts_stopped(qtbot: QtBot) -> None:
    """**Test steps:**

    * build a spinner
    * verify its size hint is the square, it is not running, and it paints nothing
    """
    spinner = BusySpinner()
    qtbot.addWidget(spinner)
    spinner.resize(spinner.sizeHint())

    assert (spinner.sizeHint().width(), spinner.sizeHint().height()) == (SPINNER_SIZE, SPINNER_SIZE)
    assert not spinner.running
    assert not painted(spinner)


def test_a_running_spinner_paints_its_arc_and_turns_at_each_tick(qtbot: QtBot) -> None:
    """**Test steps:**

    * start a spinner, twice
    * verify it is running at its interval and paints its arc
    * fire its timer, and verify the arc moved on by one step
    """
    spinner = BusySpinner()
    qtbot.addWidget(spinner)
    spinner.resize(spinner.sizeHint())

    spinner.start()
    spinner.start()

    timer = spinner.findChild(QTimer)
    assert timer is not None
    assert spinner.running
    assert timer.interval() == SPINNER_INTERVAL_MS
    assert painted(spinner)

    timer.timeout.emit()

    assert spinner.angle == SPINNER_STEP_DEGREES


def test_a_stopped_spinner_paints_nothing_again(qtbot: QtBot) -> None:
    """**Test steps:**

    * start a spinner, then stop it twice
    * verify it is not running and paints nothing
    """
    spinner = BusySpinner()
    qtbot.addWidget(spinner)
    spinner.resize(spinner.sizeHint())
    spinner.start()

    spinner.stop()
    spinner.stop()

    assert not spinner.running
    assert not painted(spinner)
