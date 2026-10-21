"""Tests for PendingSavesIndicator: the status bar's count of the saves that have not landed (#497).

The model it follows is a ``Mock(spec=TaskQueueModel)``: what rows it holds and when it re-snapshots are
:class:`~rehuco_agent.tasks.task_queue_model.TaskQueueModel`'s own tests' subject, and what this one reads off it
is a row count, ``status_at`` and the slot it connected to ``snapshot_taken``.
"""

from collections.abc import Callable
from typing import cast
from unittest.mock import Mock

from PySide6.QtWidgets import QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks.pending_saves_indicator import PendingSavesIndicator
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_core import SAVE_RECORD_KIND, JobState, JobStatus


def save(state: JobState) -> JobStatus:
    """A save in ``state``.

    :param state: the state the save is in.
    :returns: the status.
    """
    return JobStatus(serial=1, label="save", state=state, kind=SAVE_RECORD_KIND)


def hold(model: Mock, *rows: JobStatus) -> None:
    """Make ``model`` answer ``rows`` as its rows.

    :param model: the mocked model.
    :param rows: the statuses it holds, in order.
    """
    model.rowCount.return_value = len(rows)
    model.status_at.side_effect = list(rows).__getitem__


def model_holding(*rows: JobStatus) -> Mock:
    """A mocked model holding ``rows``.

    :param rows: the statuses it holds, in order.
    :returns: the model.
    """
    model = Mock(spec=TaskQueueModel)
    hold(model, *rows)
    return model


@fixture
def host(qtbot: QtBot) -> QWidget:
    """A parent for the indicator that is never shown -- so showing the indicator opens no window.

    :param qtbot: registers it for teardown.
    :returns: the parent.
    """
    built = QWidget()
    qtbot.addWidget(built)
    return built


def indicator_over(model: Mock, host: QWidget) -> PendingSavesIndicator:
    """An indicator following ``model``, inside ``host``.

    :param model: the mocked model.
    :param host: the indicator's parent.
    :returns: the indicator.
    """
    return PendingSavesIndicator(cast(TaskQueueModel, model), host)


def resnapshot_of(model: Mock) -> Callable[[], None]:
    """The slot the indicator connected to the model's ``snapshot_taken``, to call as a re-snapshot would.

    :param model: the mocked model.
    :returns: the connected slot.
    """
    (slot,) = model.snapshot_taken.connect.call_args.args
    return slot


def test_it_is_hidden_with_no_pending_save(host: QWidget) -> None:
    """A save that landed is nothing to report: with none pending, the indicator takes no room.

    **Test steps:**

    * build an indicator over a done save, a cancelled one and a waiting job that is not a save
    * verify it is hidden
    """
    model = model_holding(
        save(JobState.DONE),
        save(JobState.CANCELLED),
        JobStatus(serial=2, label="other", state=JobState.WAITING),
    )

    assert indicator_over(model, host).isHidden()


def test_one_pending_save_is_counted_in_the_singular(host: QWidget) -> None:
    """One pending save shows, and says so in the singular.

    **Test steps:**

    * build an indicator over a waiting save beside a done one
    * verify it is shown and reads *1 pending save*
    """
    built = indicator_over(model_holding(save(JobState.WAITING), save(JobState.DONE)), host)

    assert not built.isHidden()
    assert built.text() == "1 pending save"


def test_several_pending_saves_are_counted_in_the_plural(host: QWidget) -> None:
    """A failed save is still pending, and two of them read in the plural.

    **Test steps:**

    * build an indicator over a failed save and a queued one
    * verify it reads *2 pending saves*
    """
    built = indicator_over(model_holding(save(JobState.FAILED), save(JobState.QUEUED)), host)

    assert built.text() == "2 pending saves"


def test_it_follows_each_re_snapshot(host: QWidget) -> None:
    """The count is taken again on every snapshot: it appears, changes, and hides as saves come and land.

    **Test steps:**

    * build an indicator over a model holding nothing
    * re-snapshot holding two pending saves, then one, then none
    * verify it shows *2*, then *1*, then hides
    """
    model = model_holding()
    built = indicator_over(model, host)
    resnapshot = resnapshot_of(model)
    assert built.isHidden()

    hold(model, save(JobState.WAITING), save(JobState.RUNNING))
    resnapshot()
    assert not built.isHidden()
    assert built.text() == "2 pending saves"

    hold(model, save(JobState.DONE), save(JobState.RUNNING))
    resnapshot()
    assert built.text() == "1 pending save"

    hold(model, save(JobState.DONE), save(JobState.DONE))
    resnapshot()
    assert built.isHidden()


def test_clicking_it_says_so(host: QWidget, qtbot: QtBot) -> None:
    """A click is only announced: what it opens is the caller's to wire.

    **Test steps:**

    * build an indicator over a pending save
    * click it
    * verify ``clicked`` was emitted
    """
    built = indicator_over(model_holding(save(JobState.WAITING)), host)

    with qtbot.waitSignal(built.clicked, timeout=1000):
        built.click()
