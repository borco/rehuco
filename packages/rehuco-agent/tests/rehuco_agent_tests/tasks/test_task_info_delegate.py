"""Tests for TaskInfoDelegate: a bar and its figure side by side, the reason for a failed job, or
nothing (#202, #248).

Geometry is asserted against the two rect helpers directly, and painting against the pixels that land
-- the same split ``test_task_row_delegate.py`` uses, and for its reason: what this class decides is
where each half goes and what color fills it. How each unit *reads* is
``test_task_progress_renderers.py``'s subject, not this one's.
"""

from collections.abc import Iterator
from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.tasks import task_info_delegate as delegate_module
from rehuco_agent.tasks.task_info_delegate import BAR_HEIGHT, FIGURE_WIDTH, TaskInfoDelegate
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_core import PROGRESS_UNIT_BYTES, JobState, JobStatus

CELL: Final = QRect(0, 0, 400, 24)
"""Wide enough that the reason text below is never elided, and that a bar and a figure both fit."""

RUNNING_COLOR: Final = QColor("#64B5F6")
DONE_COLOR: Final = QColor("#43A047")

STATE_COLORS: Final = {JobState.RUNNING: RUNNING_COLOR, JobState.DONE: DONE_COLOR}
"""Two states colored, so the uncolored case (``PAUSED``, as the app itself leaves it) is covered."""

COUNTED: Final = "counted"
"""A unit no renderer is registered for, so the fallback figure is what gets drawn."""


# region fixtures


class OneRowModel(QAbstractTableModel):
    """A single-cell model handing out whatever ``payload`` was given for the status role.

    :param payload: what to answer for the status role; deliberately untyped, so a foreign value can
        be handed over too.
    """

    def __init__(self, payload: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__payload = payload

    def rowCount(self, parent: Any = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else 1

    def columnCount(self, parent: Any = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else 1

    def data(self, index: Any, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        del index
        return self.__payload if role == TaskQueueModel.Roles.STATUS else None


@fixture
def image(qapp: Any) -> Iterator[QImage]:
    """A white image the size of the cell, for a delegate to paint onto and a test to read back."""
    del qapp
    canvas = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.white)
    yield canvas


@fixture
def selected_option() -> QStyleOptionViewItem:
    """A *selected* item option over the shared cell rect."""
    item = QStyleOptionViewItem()
    item.rect = CELL
    item.state |= QStyle.StateFlag.State_Selected
    return item


def paint(status: Any, image: QImage, *, selected: bool = False, cell: QRect = CELL) -> QStyleOptionViewItem:
    """Run the delegate over a one-row model holding ``status``.

    :param status: what the row's status role answers.
    :param image: the image to paint onto.
    :param selected: whether to paint the row selected.
    :param cell: the rect to paint into.
    :returns: the option it was painted with.
    """
    model = OneRowModel(status)
    option = QStyleOptionViewItem()
    option.rect = cell
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    painter = QPainter(image)
    TaskInfoDelegate(state_colors=STATE_COLORS).paint(painter, option, model.index(0, 0))
    painter.end()
    return option


def running(done: int, total: int | None, unit: str = PROGRESS_UNIT_BYTES) -> JobStatus:
    """A running job reporting ``done`` of ``total`` in ``unit``."""
    return JobStatus(serial=1, label="job", state=JobState.RUNNING, done=done, total=total, progress_unit=unit)


def color_at(image: QImage, x: int, y: int) -> str:
    """The painted color at a point, as a hex name."""
    return QColor(image.pixelColor(x, y)).name()


def bar_is_bare(image: QImage) -> bool:
    """Whether nothing was drawn where the bar would go.

    Compared against the cell's own background rather than against white: every row carries its state
    tint, so an untouched bar area is *tinted*, not blank.

    :param image: the painted cell.
    :returns: whether the bar's middle matches the untouched strip above it.
    """
    groove = TaskInfoDelegate.bar_rect(CELL)
    middle = groove.center()
    return color_at(image, middle.x(), middle.y()) == color_at(image, middle.x(), CELL.top() + 1)


# endregion


# region where each half goes


def test_the_figure_keeps_the_cells_right_hand_edge() -> None:
    """A fixed slot, so a running row's digits do not walk left and right as they change.

    **Test steps:**

    * ask for the figure's rect over the shared cell
    * verify it is the rightmost `FIGURE_WIDTH` of it, full height
    """
    figure = TaskInfoDelegate.figure_rect(CELL)

    assert figure.width() == FIGURE_WIDTH
    assert figure.right() == CELL.right()
    assert figure.height() == CELL.height()


def test_the_bar_takes_what_is_left_and_never_reaches_the_figure() -> None:
    """The two halves are side by side, which is the whole point -- they must not overlap by a pixel.

    **Test steps:**

    * ask for both rects over the shared cell
    * verify the bar starts inside the cell, ends before the figure, and is `BAR_HEIGHT` tall and centred
    """
    groove = TaskInfoDelegate.bar_rect(CELL)
    figure = TaskInfoDelegate.figure_rect(CELL)

    assert groove.left() > CELL.left()
    assert groove.right() < figure.left()
    assert groove.height() == BAR_HEIGHT
    assert groove.center().y() == CELL.center().y()


def test_a_cell_too_narrow_for_both_keeps_the_figure_and_drops_the_bar() -> None:
    """Shrinking the column takes the bar away rather than squeezing the numbers out of the cell: the
    figure is the part that carries the answer.

    **Test steps:**

    * ask for both rects over a cell narrower than the figure's own slot
    * verify the figure shrank to the cell and the bar is empty
    """
    narrow = QRect(0, 0, FIGURE_WIDTH - 20, 24)

    assert TaskInfoDelegate.figure_rect(narrow).width() == narrow.width()
    assert TaskInfoDelegate.bar_rect(narrow).isEmpty()


def test_a_cell_with_no_room_for_a_bar_draws_none(image: QImage, mocker: MockerFixture) -> None:
    """The geometry above is not just advisory -- a determinate job in a column squeezed down to the
    figure's slot draws its numbers and no bar at all.

    **Test steps:**

    * paint a determinate running job into a cell too narrow to hold both halves
    * verify no bar was drawn
    """
    drawn_bar = mocker.patch.object(QPainter, "drawRoundedRect")

    paint(running(3, 4), image, cell=QRect(0, 0, FIGURE_WIDTH - 20, 24))

    drawn_bar.assert_not_called()


def test_a_short_row_shrinks_the_bar_rather_than_letting_it_overflow() -> None:
    """**Test steps:**

    * ask for the bar's rect over a cell shorter than the bar
    * verify it took the cell's height instead
    """
    short = QRect(0, 0, 400, BAR_HEIGHT - 6)

    assert TaskInfoDelegate.bar_rect(short).height() == short.height()


# endregion


# region what gets painted


def test_a_determinate_job_fills_its_bar_in_the_states_own_color(image: QImage) -> None:
    """The filled part takes the same value that tints the row and colors the status glyph.

    **Test steps:**

    * paint a running job at half of its total
    * verify the bar's filled end is the running color and its empty end is not
    """
    groove = TaskInfoDelegate.bar_rect(CELL)

    paint(
        running(4, 8),
        image,
    )

    filled = color_at(image, groove.left() + groove.width() // 4, groove.center().y())
    empty = color_at(image, groove.right() - groove.width() // 4, groove.center().y())
    assert filled == RUNNING_COLOR.name()
    assert empty != RUNNING_COLOR.name()


def test_a_state_with_no_color_fills_its_bar_in_the_rows_own_ink(image: QImage) -> None:
    """``PAUSED`` earns no accent here either (#251) -- its bar is the row's ink, muted.

    **Test steps:**

    * paint a paused job at half of its total
    * verify the filled end is neither of the state colors, and is darker than the empty end
    """
    groove = TaskInfoDelegate.bar_rect(CELL)
    status = JobStatus(serial=1, label="job", state=JobState.PAUSED, done=4, total=8, progress_unit=PROGRESS_UNIT_BYTES)

    paint(status, image)

    filled = QColor(color_at(image, groove.left() + groove.width() // 4, groove.center().y()))
    empty = QColor(color_at(image, groove.right() - groove.width() // 4, groove.center().y()))
    assert filled.name() not in (RUNNING_COLOR.name(), DONE_COLOR.name())
    assert filled.lightness() < empty.lightness()


def test_the_bar_is_filled_in_proportion(image: QImage) -> None:
    """A quarter done is a quarter filled, which is the one thing a bar is for.

    **Test steps:**

    * paint a running job at a quarter of its total
    * verify the color changes between just inside the quarter mark and just past it
    """
    groove = TaskInfoDelegate.bar_rect(CELL)
    middle = groove.center().y()

    paint(running(1, 4), image)

    assert color_at(image, groove.left() + groove.width() // 4 - 4, middle) == RUNNING_COLOR.name()
    assert color_at(image, groove.left() + groove.width() // 4 + 4, middle) != RUNNING_COLOR.name()


def test_progress_past_the_total_clamps_the_bar_but_prints_the_disagreement(
    image: QImage, mocker: MockerFixture
) -> None:
    """``done > total`` clamps the *bar* and still prints both numbers -- the engine clamps nothing, so
    the disagreement is shown rather than silently corrected.

    **Test steps:**

    * paint a job reporting 9 of 4
    * verify the bar is filled to its right-hand end, and the figure still reads ``9/4``
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")
    groove = TaskInfoDelegate.bar_rect(CELL)

    paint(running(9, 4, COUNTED), image)

    assert color_at(image, groove.right() - 4, groove.center().y()) == RUNNING_COLOR.name()
    assert "9/4" in [call.args[-1] for call in drawn_text.call_args_list]


def test_the_renderers_figure_is_drawn_in_its_own_slot(image: QImage, mocker: MockerFixture) -> None:
    """Whatever the job's renderer said goes in the reserved slot, right-aligned -- never across the
    cell and never on the bar.

    The figure is stubbed rather than spelled out: *what* each unit reads as belongs to
    ``test_task_progress_renderers.py``, and a real figure's length would make this assertion depend
    on the font the test happens to run under.

    **Test steps:**

    * paint a running job whose renderer is made to answer a known string
    * verify exactly that string was drawn, inside the figure's own rect, aligned right
    """
    mocker.patch.object(delegate_module, "progress_text", return_value="XX")
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(running(3, 4), image)

    drawn_text.assert_called_once()
    rect, alignment, text = drawn_text.call_args.args
    assert text == "XX"
    assert TaskInfoDelegate.figure_rect(CELL).contains(rect)
    assert alignment & Qt.AlignmentFlag.AlignRight


def test_a_job_with_no_total_draws_its_figure_and_no_bar(image: QImage, mocker: MockerFixture) -> None:
    """``total is None`` has no fraction to draw, so the figure stands alone in its slot.

    **Test steps:**

    * paint a running byte-counting job that has reported no total
    * verify the figure was drawn and nothing was painted where the bar would be
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(running(1536, None), image)

    assert "1.5K" in [call.args[-1] for call in drawn_text.call_args_list]
    assert bar_is_bare(image)


def test_a_job_with_nothing_to_do_leaves_its_cell_empty(image: QImage, mocker: MockerFixture) -> None:
    """A verify whose files were all checked recently reports ``(0, 0)`` and has **nothing to say** --
    no bar, and no ``0B`` either: *nothing to do* is not *did nothing*.

    **Test steps:**

    * paint a running byte-counting job that reported 0 of 0
    * verify neither a bar nor any figure was drawn
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(running(0, 0), image)

    drawn_text.assert_not_called()
    assert bar_is_bare(image)


def test_a_job_declaring_no_unit_draws_nothing_at_all(image: QImage, mocker: MockerFixture) -> None:
    """One indivisible step reports ``1/1`` and has nothing to say about it, so its cell stays empty --
    a bar jumping from empty to full says nothing the state column does not (#248).

    **Test steps:**

    * paint a running job that has reported 1 of 1 and declares no unit
    * verify neither a bar nor any text was drawn
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=1, total=1), image)

    drawn_text.assert_not_called()
    assert bar_is_bare(image)


def test_an_unregistered_unit_falls_back_to_the_bare_numbers(image: QImage, mocker: MockerFixture) -> None:
    """A unit this build has no renderer for still draws honest figures rather than nothing.

    **Test steps:**

    * paint a running job declaring a unit nothing is registered for
    * verify the figure is the plain ``done/total`` pair
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(running(3, 4, COUNTED), image)

    assert "3/4" in [call.args[-1] for call in drawn_text.call_args_list]


def test_a_renderer_with_nothing_to_say_draws_nothing(image: QImage, mocker: MockerFixture) -> None:
    """A declared unit is not a promise that there is anything to show yet.

    **Test steps:**

    * paint a running job declaring a unit, with nothing reported against it
    * verify no text was drawn
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(running(0, None, COUNTED), image)

    drawn_text.assert_not_called()


def test_a_selected_figure_is_drawn_in_the_rows_own_highlighted_pen(
    image: QImage, selected_option: QStyleOptionViewItem, mocker: MockerFixture
) -> None:
    """The figure reads in the same color the label and glyph do, because the row's fill sits under it
    and nothing else does.

    **Test steps:**

    * paint a selected, determinate job
    * assert the pen at the moment the figure was drawn is the palette's highlighted-text color
    """
    canvas = QPainter(image)
    model = OneRowModel(running(3, 4))

    pens: list[QColor] = []
    mocker.patch.object(QPainter, "drawText", side_effect=lambda *args: pens.append(canvas.pen().color()))
    TaskInfoDelegate(state_colors=STATE_COLORS).paint(canvas, selected_option, model.index(0, 0))
    canvas.end()

    palette: QPalette = selected_option.palette
    assert pens == [palette.highlightedText().color()]


# endregion


# region the failure reason


def test_a_failed_job_draws_its_reason_across_the_whole_cell(image: QImage, mocker: MockerFixture) -> None:
    """A reason is a sentence, not a figure, so it gets the cell rather than the figure's slot.

    **Test steps:**

    * paint a failed job carrying an error and a unit
    * verify the reason was drawn into the whole cell, and no bar was painted
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")
    groove = TaskInfoDelegate.bar_rect(CELL)
    status = JobStatus(
        serial=1,
        label="job",
        state=JobState.FAILED,
        done=3,
        total=4,
        progress_unit=PROGRESS_UNIT_BYTES,
        error="OSError: the mount is not there",
    )

    paint(status, image)

    drawn_text.assert_called_once()
    rect, _alignment, text = drawn_text.call_args.args
    assert text == "OSError: the mount is not there"
    assert rect.width() > FIGURE_WIDTH
    assert color_at(image, groove.center().x(), groove.center().y()) != RUNNING_COLOR.name()


def test_a_failed_job_with_no_reason_draws_an_empty_cell(image: QImage, mocker: MockerFixture) -> None:
    """A failed row is drawn as text whether or not a reason came with it -- never as a bar.

    **Test steps:**

    * paint a failed job with no error string
    * verify empty text was drawn rather than nothing at all
    """
    drawn_text = mocker.patch.object(QPainter, "drawText")

    paint(JobStatus(serial=1, label="job", state=JobState.FAILED), image)

    assert "" in [call.args[-1] for call in drawn_text.call_args_list]


# endregion


def test_a_row_that_is_not_a_job_is_left_to_the_base_delegate(image: QImage, mocker: MockerFixture) -> None:
    """A cell whose status role is not a `JobStatus` is handed on untouched, the same deference
    `LogLevelDelegate` shows a foreign model.

    **Test steps:**

    * paint over a model answering something that is not a `JobStatus`
    * verify this delegate drew no bar of its own
    """
    drawn_bar = mocker.patch.object(QPainter, "drawRoundedRect")

    paint("not a status", image)

    drawn_bar.assert_not_called()
