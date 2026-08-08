"""Tests for TaskTextDelegate: the label and state columns' plain text, over the row's selection fill
and state tint (#251).

Asserts on the drawn text rather than on painted pixels -- the background tint and the selection color
agreement are `TaskRowDelegate`'s own contract, covered in ``test_task_row_delegate.py``; what this
class decides is which text is drawn.
"""

from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_agent.tasks.task_text_delegate import TaskTextDelegate
from rehuco_core import JobState, JobStatus

CELL: Final = QRect(0, 0, 120, 20)


# region fixtures


class OneRowModel(QAbstractTableModel):
    """A single-cell model handing out a fixed status role and display text.

    Stands in for the real model so a delegate test never needs a queue, a worker thread, or a
    snapshot to have landed -- what is under test reads exactly two roles.

    :param status: what to answer for the status role; deliberately untyped, so a foreign value can be
        handed over too.
    :param text: what to answer for the display role.
    """

    def __init__(self, status: Any, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__status = status
        self.__text = text

    def rowCount(self, parent: Any = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else 1

    def columnCount(self, parent: Any = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else 1

    def data(self, index: Any, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        del index
        if role == TaskQueueModel.Roles.STATUS:
            return self.__status
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__text
        return None


@fixture
def painter(qapp: Any) -> Any:
    """A painter over an off-screen pixmap -- the delegate needs a live one to be handed along.

    Takes ``qapp`` because a ``QPixmap`` cannot exist without a ``QGuiApplication``, and ends the
    painter afterwards rather than leaving one active on a pixmap about to be collected.
    """
    del qapp
    pixmap = QPixmap(CELL.size())
    active = QPainter(pixmap)
    yield active
    active.end()


def paint(status: Any, text: str, painter: QPainter, option: QStyleOptionViewItem | None = None) -> None:
    """Run the delegate over a one-row model holding ``status`` and ``text``.

    :param status: what the row's status role answers.
    :param text: what the row's display role answers.
    :param painter: the painter to draw with.
    :param option: the item option; defaults to an unselected cell over :data:`CELL`.
    """
    if option is None:
        option = QStyleOptionViewItem()
        option.rect = CELL
    model = OneRowModel(status, text)
    TaskTextDelegate().paint(painter, option, model.index(0, 0))


# endregion


def test_draws_the_cells_own_display_text(painter: QPainter, mocker: MockerFixture) -> None:
    """The column's own text is drawn -- the label or the state, whichever column this is.

    **Test steps:**

    * paint a row labelled ``"convert"``
    * verify that text was drawn
    """
    drawn = mocker.patch.object(QPainter, "drawText")

    paint(JobStatus(serial=1, label="convert", state=JobState.RUNNING), "convert", painter)

    assert "convert" in [call.args[-1] for call in drawn.call_args_list]


def test_a_row_with_no_text_draws_an_empty_cell(painter: QPainter, mocker: MockerFixture) -> None:
    """A cell whose display role answers nothing is still drawn, empty rather than skipped.

    **Test steps:**

    * paint a row whose display role is ``None``
    * verify empty text was drawn
    """
    drawn = mocker.patch.object(QPainter, "drawText")

    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING), None, painter)  # type: ignore[arg-type]

    assert "" in [call.args[-1] for call in drawn.call_args_list]


def test_a_row_that_is_not_a_job_is_left_to_the_base_delegate(painter: QPainter, mocker: MockerFixture) -> None:
    """A cell whose status role is not a `JobStatus` is handed on untouched, the same deference
    `LogLevelDelegate` shows a foreign model.

    **Test steps:**

    * paint over a model answering something that is not a `JobStatus`
    * verify the base delegate was handed the call
    """
    base = mocker.patch.object(QStyledItemDelegate, "paint")

    paint("not a status", "text", painter)

    base.assert_called_once()


def test_leaves_the_painter_as_it_found_it(painter: QPainter) -> None:
    """The painter Qt handed over is saved and restored, not left with a highlighted-text pen behind.

    **Test steps:**

    * note the painter's pen colour, paint a selected row, and note it again
    * assert the pen came back unchanged
    """
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.state |= QStyle.StateFlag.State_Selected
    before = painter.pen().color().rgb()

    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING), "job", painter, option)

    assert painter.pen().color().rgb() == before
