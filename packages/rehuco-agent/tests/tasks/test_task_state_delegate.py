"""Tests for TaskStateDelegate: the state column drawn as one glyph, in the state's own color (#248).

Asserts on what the delegate asks its icon cache for rather than on painted pixels: what this class
decides is *which* glyph and *which* color, and a rendered glyph's pixels would pin the icon artwork
instead of either.
"""

from collections.abc import Iterator
from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_agent.tasks.task_state_delegate import STATUS_ICON_SIZE, TaskStateDelegate
from rehuco_agent.tasks.task_status_icons import PENDING_STOP_ICONS, STATE_ICONS, StatusIconCache
from rehuco_core import JobState, JobStatus, StopRequest

CELL: Final = QRect(0, 0, 52, 24)

RUNNING_COLOR: Final = QColor("#64B5F6")
DONE_COLOR: Final = QColor("#43A047")

STATE_COLORS: Final = {JobState.RUNNING: RUNNING_COLOR, JobState.DONE: DONE_COLOR}
"""Two states colored, so the uncolored case (``PAUSED``, as the app itself leaves it) is covered."""


# region fixtures


class OneRowModel(QAbstractTableModel):
    """A single-cell model answering ``payload`` for the status role, and text for display.

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
        if role == TaskQueueModel.Roles.STATUS:
            return self.__payload
        return "Cancelling…" if role == Qt.ItemDataRole.DisplayRole else None


@fixture
def painter(qapp: Any) -> Iterator[QPainter]:
    """A painter over an off-screen pixmap -- the delegate needs a live one to be handed along."""
    del qapp
    pixmap = QPixmap(CELL.size())
    active = QPainter(pixmap)
    yield active
    active.end()


@fixture
def asked(mocker: MockerFixture) -> Any:
    """Record every ``(path, color)`` the delegate asks its icon cache for.

    :returns: the patched ``StatusIconCache.icon``.
    """
    return mocker.patch.object(StatusIconCache, "icon", autospec=True)


@fixture
def option() -> QStyleOptionViewItem:
    """An unselected item option over the shared cell rect."""
    item = QStyleOptionViewItem()
    item.rect = CELL
    return item


def paint(status: Any, painter: QPainter, option: QStyleOptionViewItem) -> None:
    """Run the delegate over a one-row model holding ``status``.

    :param status: what the row's status role answers.
    :param painter: the painter to draw with.
    :param option: the item option to paint under.
    """
    model = OneRowModel(status)
    TaskStateDelegate(state_colors=STATE_COLORS).paint(painter, option, model.index(0, 0))


def requested(asked: Any) -> tuple[str, QColor]:
    """The single glyph/color pair the delegate asked for.

    :param asked: the patched cache method.
    :returns: the icon path and the color.
    """
    asked.assert_called_once()
    _self, path, color = asked.call_args.args
    return path, color


# endregion


def test_a_state_with_a_color_draws_its_glyph_in_it(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """The glyph takes the state's own color -- the same value that tints the row, at full strength.

    **Test steps:**

    * paint a running row
    * verify the running glyph was asked for, in the running color
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING), painter, option)

    assert requested(asked) == (STATE_ICONS[JobState.RUNNING], RUNNING_COLOR)


def test_a_state_with_no_color_draws_in_the_rows_own_ink(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """``PAUSED`` earns no accent, exactly as it earns no row tint (#251), so its glyph takes the pen.

    **Test steps:**

    * paint a paused row
    * verify the paused glyph was asked for in the painter's own text color, not in a state color
    """
    paint(JobStatus(serial=1, label="job", state=JobState.PAUSED), painter, option)

    path, color = requested(asked)

    assert path == STATE_ICONS[JobState.PAUSED]
    assert color == painter.pen().color()
    assert color not in (RUNNING_COLOR, DONE_COLOR)


def test_a_selected_uncolored_row_draws_in_the_highlighted_ink(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """The pen a selected row's fill established is the one an uncolored glyph follows, so it reads
    against the highlight like every other cell on the row.

    **Test steps:**

    * paint a selected paused row
    * verify the glyph was asked for in the palette's highlighted-text color
    """
    option.state |= QStyle.StateFlag.State_Selected

    paint(JobStatus(serial=1, label="job", state=JobState.PAUSED), painter, option)

    _path, color = requested(asked)

    palette: QPalette = option.palette
    assert color == palette.highlightedText().color()


def test_a_pending_stop_draws_its_own_glyph_in_the_state_it_is_still_in(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """A running job asked to pause is still running, so it keeps the running color and changes glyph.

    **Test steps:**

    * paint a running row with a pause pending
    * verify the *pausing* glyph was asked for, in the running color
    """
    status = JobStatus(serial=1, label="job", state=JobState.RUNNING, stop_requested=StopRequest.PAUSE)

    paint(status, painter, option)

    assert requested(asked) == (PENDING_STOP_ICONS[StopRequest.PAUSE], RUNNING_COLOR)


def test_the_glyph_is_centred_and_never_bigger_than_the_cell(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """A square glyph in the middle of the cell, shrunk rather than clipped by a short row.

    **Test steps:**

    * paint a row into the shared cell
    * verify the rect the icon was painted into is square, centred, and at the icon size
    """
    icon = asked.return_value

    paint(JobStatus(serial=1, label="job", state=JobState.DONE), painter, option)

    icon.paint.assert_called_once()
    rect = QRect(icon.paint.call_args.args[1])
    assert rect.size().width() == rect.size().height() == STATUS_ICON_SIZE
    assert rect.center() == option.rect.center()


def test_the_column_is_sized_for_a_glyph_not_for_the_text_it_does_not_draw(
    painter: QPainter, option: QStyleOptionViewItem
) -> None:
    """The model still answers the state's sentence, and the base delegate would size the column for
    it -- this one asks for the glyph instead.

    **Test steps:**

    * ask the delegate for its size hint over a row whose display text is long
    * verify it asked for the glyph's own square rather than the text's width
    """
    del painter
    model = OneRowModel(JobStatus(serial=1, label="job", state=JobState.DONE))

    hint = TaskStateDelegate(state_colors=STATE_COLORS).sizeHint(option, model.index(0, 0))

    assert hint.width() == hint.height() == STATUS_ICON_SIZE


def test_a_row_that_is_not_a_job_is_left_to_the_base_delegate(
    painter: QPainter, option: QStyleOptionViewItem, asked: Any
) -> None:
    """A cell whose status role is not a `JobStatus` is handed on untouched.

    **Test steps:**

    * paint over a model answering something that is not a `JobStatus`
    * verify no glyph was asked for
    """
    paint("not a status", painter, option)

    asked.assert_not_called()
