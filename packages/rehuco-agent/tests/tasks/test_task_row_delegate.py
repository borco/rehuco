"""Tests for TaskRowDelegate: the selection fill and state tint every task cell delegate shares (#251).

Asserts on painted pixels for the background, the same reasoning
:mod:`~borco_pyside.logging.log_level_delegate`'s own tests give: what this class decides is the color
that ends up on the pixels, and a recorded ``fillRect`` call proves only that it was asked for.
"""

from typing import Final

from borco_pyside.logging import BAND_TINT_ALPHA
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.tasks.task_row_delegate import TaskRowDelegate
from rehuco_core import JobState

QUEUED_COLOR: Final = QColor("#FFB300")
FAILED_COLOR: Final = QColor("#C62828")

STATE_COLORS: Final = {JobState.QUEUED: QUEUED_COLOR, JobState.FAILED: FAILED_COLOR}
"""Two of the six states colored, so the untinted case (``RUNNING``, absent here) is covered too."""

CELL: Final = QRect(0, 0, 120, 24)


# region helpers


def blended_over_white(color: QColor) -> QColor:
    """The color a tint of ``color`` leaves on a white pixel.

    :param color: the caller's untinted color.
    :returns: the expected painted color.
    """
    alpha = BAND_TINT_ALPHA / 255
    return QColor(
        round(color.red() * alpha + 255 * (1 - alpha)),
        round(color.green() * alpha + 255 * (1 - alpha)),
        round(color.blue() * alpha + 255 * (1 - alpha)),
    )


def paint_background_onto_image(delegate: TaskRowDelegate, option: QStyleOptionViewItem, state: JobState) -> QImage:
    """Paint one background onto a white image and hand it back for inspection.

    :param delegate: the delegate to paint with.
    :param option: the item option to paint under.
    :param state: the row's job state.
    :returns: the painted image.
    """
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    delegate.paint_background(painter, option, state)
    painter.end()
    return image


# endregion


# region fixtures


@fixture
def delegate(qapp: object) -> TaskRowDelegate:
    """Provide a delegate with two of the six states colored.

    :param qapp: ensures a QApplication exists.
    :returns: the delegate.
    """
    del qapp
    return TaskRowDelegate(state_colors=STATE_COLORS)


@fixture
def option() -> QStyleOptionViewItem:
    """Provide an unselected item option over a fixed cell rect.

    :returns: the option.
    """
    item = QStyleOptionViewItem()
    item.rect = CELL
    return item


# endregion


# region the tint per state


def test_tint_for_applies_the_alpha_to_a_colored_state(delegate: TaskRowDelegate) -> None:
    """A colored state's tint is the caller's color at this class's own alpha.

    **Test steps:**

    * ask the delegate for the queued state's tint
    * assert the hue is the caller's and the alpha is the delegate's
    """
    tint = delegate.tint_for(JobState.QUEUED)
    assert tint is not None
    assert tint.rgb() == QUEUED_COLOR.rgb()
    assert tint.alpha() == BAND_TINT_ALPHA


@mark.parametrize("state", [JobState.RUNNING, JobState.PAUSED, JobState.DONE, JobState.CANCELLED])
def test_a_state_with_no_color_has_no_tint(delegate: TaskRowDelegate, state: JobState) -> None:
    """A state absent from the map is drawn plain rather than in some invented color.

    **Test steps:**

    * ask the delegate for a state the map does not mention
    * assert there is no tint
    """
    assert delegate.tint_for(state) is None


# endregion


# region painting the background


def test_paints_a_state_in_its_own_tint(delegate: TaskRowDelegate, option: QStyleOptionViewItem) -> None:
    """A queued row's background is the queued color, blended over what was underneath.

    **Test steps:**

    * paint the queued state's background over white
    * assert a background pixel matches the tint blended over white
    """
    image = paint_background_onto_image(delegate, option, JobState.QUEUED)
    expected = blended_over_white(QUEUED_COLOR)
    assert QColor(image.pixelColor(CELL.width() - 2, CELL.height() - 2)).rgb() == expected.rgb()


def test_paints_an_uncolored_state_without_a_tint(delegate: TaskRowDelegate, option: QStyleOptionViewItem) -> None:
    """A paused row is left on whatever the view already painted.

    **Test steps:**

    * paint the paused state's background over white
    * assert a background pixel is still white
    """
    image = paint_background_onto_image(delegate, option, JobState.PAUSED)
    assert QColor(image.pixelColor(CELL.width() - 2, CELL.height() - 2)).rgb() == QColor(Qt.GlobalColor.white).rgb()


def test_a_selected_row_keeps_its_state_tint(delegate: TaskRowDelegate, option: QStyleOptionViewItem) -> None:
    """Selecting a row does not take away the color the reader picked it out by.

    **Test steps:**

    * paint the failed state's background with the selected state set
    * assert the painted background is neither plain white nor the untinted highlight
    """
    option.state |= QStyle.StateFlag.State_Selected
    image = paint_background_onto_image(delegate, option, JobState.FAILED)
    painted = QColor(image.pixelColor(CELL.width() - 3, CELL.height() - 3))
    highlight = option.palette.highlight().color()
    assert painted.rgb() != QColor(Qt.GlobalColor.white).rgb()
    assert painted.rgb() != highlight.rgb()


def test_a_selected_untinted_row_is_the_plain_highlight(
    delegate: TaskRowDelegate, option: QStyleOptionViewItem
) -> None:
    """A selected row with no tint reads as an ordinary selection.

    **Test steps:**

    * paint the paused state's background with the selected state set
    * assert the painted background is exactly the palette's highlight color
    """
    option.state |= QStyle.StateFlag.State_Selected
    image = paint_background_onto_image(delegate, option, JobState.PAUSED)
    painted = QColor(image.pixelColor(CELL.width() // 2, CELL.height() // 2))
    highlight = option.palette.highlight().color()
    assert painted.rgb() == highlight.rgb()


# endregion


# region text drawn against the background it sits on


def test_selected_text_uses_the_same_highlighted_pen_the_fill_used(
    delegate: TaskRowDelegate, option: QStyleOptionViewItem, mocker: MockerFixture
) -> None:
    """A selected row's text is drawn in the same color the fill it sits on used to declare itself
    selected -- not whatever a style would separately have chosen for it (#251: the two used to
    disagree whenever the view was selected but not focused, since the style computes its own text
    color off ``option.state``'s active/inactive bit, independently of the highlight this class fills).

    **Test steps:**

    * fill a selected, tinted row, then ask for its text to be drawn
    * assert the painter's pen at the moment of drawing was exactly the palette's highlighted-text color
    """
    option.state |= QStyle.StateFlag.State_Selected
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint_background(painter, option, JobState.FAILED)

    pens_when_drawn: list[QColor] = []
    mocker.patch.object(QPainter, "drawText", side_effect=lambda *args: pens_when_drawn.append(painter.pen().color()))

    delegate.paint_text(painter, option, "boom")
    painter.end()

    assert pens_when_drawn == [option.palette.highlightedText().color()]


def test_long_text_is_elided_to_the_cells_width(
    delegate: TaskRowDelegate, option: QStyleOptionViewItem, mocker: MockerFixture
) -> None:
    """Text too long for the cell is elided rather than overflowing it.

    **Test steps:**

    * paint text much longer than the cell
    * assert the drawn string is shorter than the original
    """
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    drawn = mocker.patch.object(QPainter, "drawText")

    original = "a label so long it cannot possibly fit in a narrow task-queue column"
    delegate.paint_text(painter, option, original)
    painter.end()

    drawn.assert_called_once()
    elided = drawn.call_args.args[-1]
    assert elided != original
    assert len(elided) < len(original)


# endregion
