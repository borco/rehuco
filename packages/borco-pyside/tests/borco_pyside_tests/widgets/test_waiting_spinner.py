"""Tests for WaitingSpinner: a ring of lines lit one after another while something is waited for."""

from borco_pyside.widgets import WaitingSpinner
from borco_pyside.widgets.waiting_spinner import (
    DEFAULT_INNER_RADIUS,
    DEFAULT_LINE_LENGTH,
    DEFAULT_NUMBER_OF_LINES,
    DEFAULT_REVOLUTIONS_PER_SECOND,
    line_distance,
    trail_color,
)
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QWidget
from pytest import approx, fixture, mark, param
from pytestqt.qtbot import QtBot


@fixture(name="parent")
def fixture_parent(qtbot: QtBot) -> QWidget:
    """A shown parent for a spinner to stand over.

    :param qtbot: pytest-qt fixture.
    :returns: the parent.
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(200, 100)
    parent.show()
    qtbot.waitExposed(parent)
    return parent


def timer_of(spinner: WaitingSpinner) -> QTimer:
    """The timer that lights the next line.

    :param spinner: the spinner.
    :returns: its timer.
    """
    timer = spinner.findChild(QTimer)
    assert timer is not None
    return timer


def painted_in(spinner: WaitingSpinner, red: bool) -> bool:
    """Whether a spinner paints a line in pure red or in pure blue, on white.

    :param spinner: the spinner.
    :param red: ``True`` to look for red, ``False`` for blue.
    :returns: whether any pixel is that color.
    """
    # rendered onto a pixmap filled here: a translucent widget's grab() leaves its pixels as they were in memory
    pixmap = QPixmap(spinner.size())
    pixmap.fill(QColor("white"))
    spinner.render(pixmap)
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    colors = (image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height()))
    if red:
        return any(c.red() > 200 and c.green() < 80 and c.blue() < 80 and c.alpha() > 200 for c in colors)
    return any(c.blue() > 200 and c.green() < 80 and c.red() < 80 and c.alpha() > 200 for c in colors)


def test_a_spinner_starts_hidden_and_stopped_at_its_ring_size(qtbot: QtBot) -> None:
    """**Test steps:**

    * build a spinner with no parent
    * verify it is hidden, not spinning, a fixed square fitting its ring, paced to go round at its default speed
    """
    spinner = WaitingSpinner()
    qtbot.addWidget(spinner)

    side = 2 * (DEFAULT_INNER_RADIUS + DEFAULT_LINE_LENGTH)
    assert spinner.isHidden()
    assert not spinner.spinning
    assert (spinner.minimumSize().width(), spinner.maximumSize().height()) == (side, side)
    assert timer_of(spinner).interval() == round(1000 / (DEFAULT_NUMBER_OF_LINES * DEFAULT_REVOLUTIONS_PER_SECOND))


def test_it_spins_shown_lighting_one_line_after_another_and_stops_hidden(parent: QWidget) -> None:
    """**Test steps:**

    * start a spinner twice, and verify it is shown and spinning from the first line
    * fire its timer once per line, and verify the lit line went round to the first again
    * stop it twice, and verify it is hidden and stopped
    """
    spinner = WaitingSpinner(parent)
    spinner.start()
    spinner.start()

    assert spinner.isVisible()
    assert spinner.spinning
    assert spinner.lit == 0

    timer_of(spinner).timeout.emit()
    assert spinner.lit == 1
    for _ in range(DEFAULT_NUMBER_OF_LINES - 1):
        timer_of(spinner).timeout.emit()
    assert spinner.lit == 0

    spinner.stop()
    spinner.stop()

    assert spinner.isHidden()
    assert not spinner.spinning


def test_it_paints_in_the_palettes_text_color_unless_one_is_set(qtbot: QtBot) -> None:
    """**Test steps:**

    * give a spinner a red text color on a white background
    * verify it has no color of its own and paints red
    * set it blue, and verify it reads and paints blue
    * set it back to none, and verify it paints red again
    """
    spinner = WaitingSpinner()
    qtbot.addWidget(spinner)
    palette = spinner.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("red"))
    spinner.setPalette(palette)

    assert spinner.color is None
    assert painted_in(spinner, red=True)

    spinner.color = QColor("blue")

    assert spinner.color == QColor("blue")
    assert painted_in(spinner, red=False)
    assert not painted_in(spinner, red=True)

    spinner.color = None

    assert spinner.color is None
    assert painted_in(spinner, red=True)


def test_its_shape_and_pace_follow_its_properties(qtbot: QtBot) -> None:
    """**Test steps:**

    * set every property of a spinner, lighting a line first
    * verify each reads back, the roundness clamped, the size and the pace following, and the first line lit again
    """
    spinner = WaitingSpinner()
    qtbot.addWidget(spinner)
    timer_of(spinner).timeout.emit()

    spinner.roundness = 150.0
    assert spinner.roundness == 100.0
    spinner.roundness = -5.0
    assert spinner.roundness == 0.0
    spinner.minimum_trail_opacity = 15.0
    spinner.trail_fade_percentage = 70.0
    spinner.number_of_lines = 12
    spinner.revolutions_per_second = 1.0
    spinner.line_length = 8
    spinner.line_width = 50
    spinner.inner_radius = 4

    assert (spinner.minimum_trail_opacity, spinner.trail_fade_percentage) == (15.0, 70.0)
    assert (spinner.number_of_lines, spinner.revolutions_per_second, spinner.lit) == (12, 1.0, 0)
    assert (spinner.line_length, spinner.line_width, spinner.inner_radius) == (8, 50, 4)
    assert timer_of(spinner).interval() == round(1000 / 12)
    assert spinner.width() == 50


def test_it_stands_over_its_parents_middle_and_follows_its_resizes(parent: QWidget, qtbot: QtBot) -> None:
    """**Test steps:**

    * start a spinner centered on a parent, and verify it is in the parent's middle
    * resize the parent, and verify it moved to the new middle
    """
    spinner = WaitingSpinner(parent)
    spinner.start()

    assert spinner.geometry().center() == parent.rect().center()

    parent.resize(300, 240)
    qtbot.waitUntil(lambda: spinner.geometry().center() == parent.rect().center())


def test_one_not_centered_stays_where_it_is_put(parent: QWidget) -> None:
    """**Test steps:**

    * start a spinner not centered on its parent, at the origin
    * resize the parent, and verify it is still at the origin
    """
    spinner = WaitingSpinner(parent, center_on_parent=False)
    spinner.start()
    parent.resize(300, 240)

    assert (spinner.x(), spinner.y()) == (0, 0)


def test_it_disables_its_parent_while_spinning_when_asked(parent: QWidget) -> None:
    """**Test steps:**

    * start a spinner that disables its parent, and verify the parent is disabled
    * stop it, and verify the parent is enabled again
    """
    spinner = WaitingSpinner(parent, disable_parent_when_spinning=True)

    spinner.start()
    assert not parent.isEnabled()

    spinner.stop()
    assert parent.isEnabled()


def test_a_line_is_behind_the_lit_one_going_round() -> None:
    """**Test steps:**

    * verify the distance of the lit line, one after it, and one before it
    """
    assert line_distance(3, 3, 10) == 0
    assert line_distance(2, 3, 10) == 1
    assert line_distance(4, 3, 10) == 9


@mark.parametrize(
    "distance, alpha",
    [
        param(0, 1.0, id="the-lit-line"),
        param(1, 1.0 - 0.9 / 11, id="in-the-trail"),
        param(15, 0.1, id="past-the-trail"),
    ],
)
def test_a_lines_color_fades_along_the_trail(distance: int, alpha: float) -> None:
    """**Test steps:**

    * color a line of a 20-line ring, the trail over half of it, at 10% past it
    * verify its opacity by how far it is behind the lit one, and its hue kept
    """
    color = trail_color(QColor("red"), distance, 20, 50.0, 10.0)

    assert color.alphaF() == approx(alpha, abs=0.01)
    assert (color.red(), color.green(), color.blue()) == (255, 0, 0)
