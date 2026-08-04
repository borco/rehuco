"""Tests for TaskProgressDelegate: a bar for unfinished work, the reason for a failed one (#202).

Asserts on the ``QStyle`` calls the delegate makes rather than on painted pixels: what this class
decides is *which* control to draw and with what numbers -- determinate vs busy, clamped vs true --
and a pixel comparison would pin the current theme's rendering instead of any of that.
"""

from collections.abc import Iterator
from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.tasks import task_progress_delegate as delegate_module
from rehuco_agent.tasks.task_progress_delegate import PROGRESS_MAXIMUM, TaskProgressDelegate
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_core import JobState, JobStatus

CELL: Final = QRect(0, 0, 120, 20)


# region fixtures


class OneRowModel(QAbstractTableModel):
    """A single-cell model handing out whatever ``payload`` was given for
    :attr:`~rehuco_agent.tasks.task_queue_model.TaskQueueModel.Roles.STATUS`.

    Stands in for the real model so a delegate test never needs a queue, a worker thread, or a
    snapshot to have landed -- what is under test reads exactly one role.

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
def painter(qapp: Any) -> Iterator[QPainter]:
    """A painter over an off-screen pixmap -- the delegate needs a live one to be handed along.

    Takes ``qapp`` because a ``QPixmap`` cannot exist without a ``QGuiApplication``, and ends the
    painter afterwards rather than leaving one active on a pixmap about to be collected.
    """
    del qapp
    pixmap = QPixmap(CELL.size())
    active = QPainter(pixmap)
    yield active
    active.end()


@fixture
def style(mocker: MockerFixture) -> Any:
    """Stand in for ``QApplication.style()`` so the drawn control and its option can be read back.

    :returns: the fake style whose ``drawControl`` records what the delegate asked for.
    """
    fake_application = mocker.patch.object(delegate_module, "QApplication")
    fake_style = mocker.MagicMock()
    fake_application.style.return_value = fake_style
    return fake_style


def paint(status: Any, painter: QPainter) -> None:
    """Run the delegate over a one-row model holding ``status``.

    :param status: what the row's status role answers.
    :param painter: the painter to draw with.
    """
    model = OneRowModel(status)
    TaskProgressDelegate().paint(painter, QStyleOptionViewItem(), model.index(0, 0))


def drawn(style: Any) -> tuple[Any, Any]:
    """The element and option of the style's single ``drawControl`` call.

    :param style: the fake style.
    :returns: the control element drawn, and the option it was drawn with.
    """
    style.drawControl.assert_called_once()
    element, option, _painter = style.drawControl.call_args.args
    return element, option


# endregion


def test_a_determinate_job_draws_a_bar_with_its_true_numbers(painter: QPainter, style: Any) -> None:
    """A job that knows its total gets a real progress bar, labelled with the numbers themselves.

    **Test steps:**

    * paint a running job at 3 of 4
    * verify a progress bar was drawn, filled proportionally and labelled ``3/4``
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=3, total=4), painter)

    element, option = drawn(style)

    assert element == QStyle.ControlElement.CE_ProgressBar
    assert option.maximum == PROGRESS_MAXIMUM
    assert option.progress == PROGRESS_MAXIMUM * 3 // 4
    assert option.text == "3/4"


def test_a_job_with_no_total_draws_a_busy_bar(painter: QPainter, style: Any) -> None:
    """``total is None`` is an honest *indeterminate*, not a bar stalled at either end.

    **Test steps:**

    * paint a running job that has reported no total
    * verify the bar is drawn in Qt's own indeterminate spelling (maximum 0)
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=0, total=None), painter)

    element, option = drawn(style)

    assert element == QStyle.ControlElement.CE_ProgressBar
    assert option.maximum == 0


def test_a_zero_total_draws_a_busy_bar_too(painter: QPainter, style: Any) -> None:
    """``total == 0`` reads the same way as no total -- both mean *nothing to divide by*.

    **Test steps:**

    * paint a running job whose total is zero
    * verify the bar is indeterminate rather than complete or empty
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=0, total=0), painter)

    _element, option = drawn(style)

    assert option.maximum == 0


def test_a_busy_bar_still_shows_what_has_been_done(painter: QPainter, style: Any) -> None:
    """An indeterminate job that has counted something says the count, since it is all it honestly has.

    **Test steps:**

    * paint an indeterminate job that has done 7 units
    * verify the bar is labelled with the bare count
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=7, total=None), painter)

    _element, option = drawn(style)

    assert option.text == "7"


def test_progress_past_the_total_clamps_the_bar_but_prints_the_disagreement(painter: QPainter, style: Any) -> None:
    """``done > total`` clamps the *bar* and still prints both numbers -- the engine clamps nothing, so
    the disagreement is shown rather than silently corrected.

    **Test steps:**

    * paint a job reporting 9 of 4
    * verify the bar is full but the label still reads ``9/4``
    """
    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=9, total=4), painter)

    _element, option = drawn(style)

    assert option.progress == PROGRESS_MAXIMUM
    assert option.text == "9/4"


def test_a_failed_job_draws_its_reason_instead_of_a_bar(painter: QPainter, style: Any) -> None:
    """The progress column carries nothing useful for a failed row, so it carries the reason.

    **Test steps:**

    * paint a failed job carrying an error
    * verify an item (not a bar) was drawn, holding the reason as its text
    """
    status = JobStatus(serial=1, label="job", state=JobState.FAILED, error="ValueError: nope")

    paint(status, painter)

    element, option = drawn(style)

    assert element == QStyle.ControlElement.CE_ItemViewItem
    assert option.text == "ValueError: nope"


def test_a_failed_job_with_no_reason_draws_an_empty_cell(painter: QPainter, style: Any) -> None:
    """A failed row is drawn as text whether or not a reason came with it -- never as a bar.

    **Test steps:**

    * paint a failed job with no error string
    * verify an item was drawn, with empty text
    """
    paint(JobStatus(serial=1, label="job", state=JobState.FAILED), painter)

    element, option = drawn(style)

    assert element == QStyle.ControlElement.CE_ItemViewItem
    assert option.text == ""


def test_a_row_that_is_not_a_job_is_left_to_the_base_delegate(painter: QPainter, style: Any) -> None:
    """A cell whose status role is not a `JobStatus` is handed on untouched, the same deference
    `LogLevelDelegate` shows a foreign model.

    **Test steps:**

    * paint over a model answering something that is not a `JobStatus`
    * verify this delegate drew neither a bar nor an item of its own
    """
    paint("not a status", painter)

    for call in style.drawControl.call_args_list:
        assert call.args[0] != QStyle.ControlElement.CE_ProgressBar


def test_a_missing_style_is_survived(painter: QPainter, mocker: MockerFixture) -> None:
    """With no application style to draw through, the delegate does nothing rather than raise.

    **Test steps:**

    * paint a running job and a failed one with ``QApplication.style()`` answering ``None``
    * verify neither raises
    """
    fake_application = mocker.patch.object(delegate_module, "QApplication")
    fake_application.style.return_value = None

    paint(JobStatus(serial=1, label="job", state=JobState.RUNNING, done=1, total=2), painter)
    paint(JobStatus(serial=2, label="job", state=JobState.FAILED, error="boom"), painter)
