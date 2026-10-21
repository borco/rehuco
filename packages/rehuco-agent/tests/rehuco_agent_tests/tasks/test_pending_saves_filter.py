"""Tests for PendingSavesFilter and is_pending_save: the task queue narrowed to the saves that have not landed (#497).

The filter's source is a plain ``QStandardItemModel`` whose rows answer a `JobStatus` on the status role -- the one
thing the filter reads off :class:`~rehuco_agent.tasks.task_queue_model.TaskQueueModel`, whose own tests prove it
answers that role.
"""

from typing import Final

from PySide6.QtGui import QStandardItem, QStandardItemModel
from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.tasks.pending_saves_filter import PendingSavesFilter, is_pending_save
from rehuco_agent.tasks.task_queue_model import TaskQueueModel
from rehuco_core import SAVE_RECORD_KIND, JobState, JobStatus

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

OTHER_KIND: Final = "checksum-verify"
"""A persistable job's kind that is not a save."""

STATUS_ROLE: Final = TaskQueueModel.Roles.STATUS


def status(label: str, state: JobState, kind: str | None = SAVE_RECORD_KIND) -> JobStatus:
    """A row of ``kind`` in ``state``.

    :param label: the job's label, which is also how a test reads the row back.
    :param state: the state the job is in.
    :param kind: the job's persistable kind, or ``None`` for one that is not written down.
    :returns: the status.
    """
    return JobStatus(serial=1, label=label, state=state, kind=kind)


def source_of(*rows: object) -> QStandardItemModel:
    """A one-column model whose rows answer ``rows`` on the status role.

    :param rows: what each row's status role answers, in order.
    :returns: the model.
    """
    model = QStandardItemModel()
    for payload in rows:
        item = QStandardItem()
        item.setData(payload, STATUS_ROLE)
        model.appendRow(item)
    return model


def shown_labels(proxy: PendingSavesFilter) -> list[str]:
    """The labels of the rows the filter lets through, top to bottom.

    :param proxy: the filter to read.
    :returns: the labels.
    """
    return [proxy.data(proxy.index(row, 0), STATUS_ROLE).label for row in range(proxy.rowCount())]


def filter_over(source: QStandardItemModel, delete_at_teardown: DeleteAtTeardown) -> PendingSavesFilter:
    """A filter over ``source``, the source parented to it so both go at teardown.

    :param source: the model to filter.
    :param delete_at_teardown: deletes the filter after the test.
    :returns: the filter, not yet enabled.
    """
    proxy = delete_at_teardown(PendingSavesFilter())
    source.setParent(proxy)
    proxy.setSourceModel(source)
    return proxy


# region is_pending_save


@mark.parametrize("state", [state for state in JobState if state not in (JobState.DONE, JobState.CANCELLED)])
def test_a_save_that_has_not_landed_is_pending(state: JobState) -> None:
    """Every save not yet settled is pending -- a failed one included, whose edits are still only in memory.

    **Test steps:**

    * describe a save in each state but done and cancelled
    * verify each is pending
    """
    assert is_pending_save(status("save", state))


@mark.parametrize("state", [JobState.DONE, JobState.CANCELLED])
def test_a_save_that_landed_or_was_dropped_is_not_pending(state: JobState) -> None:
    """A save that landed, or was dropped on purpose, has nothing left to wait for.

    **Test steps:**

    * describe a done save and a cancelled one
    * verify neither is pending
    """
    assert not is_pending_save(status("save", state))


@mark.parametrize("kind", [None, OTHER_KIND])
def test_a_job_that_is_not_a_save_is_never_pending(kind: str | None) -> None:
    """Only a save can be a pending save, however unfinished another job is.

    **Test steps:**

    * describe a waiting job that is not written down, and a waiting one of another kind
    * verify neither is pending
    """
    assert not is_pending_save(status("job", JobState.WAITING, kind))


# endregion


# region the filter


def test_a_new_filter_is_off_and_passes_every_row(delete_at_teardown: DeleteAtTeardown) -> None:
    """Built, the filter is off: the dock shows the whole queue until asked for less.

    **Test steps:**

    * build a filter over a done save, a waiting one and a job that is not a save
    * verify it reads as off and lets all three through
    """
    proxy = filter_over(
        source_of(
            status("landed", JobState.DONE), status("waiting", JobState.WAITING), status("other", JobState.QUEUED, None)
        ),
        delete_at_teardown,
    )

    assert proxy.enabled is False
    assert shown_labels(proxy) == ["landed", "waiting", "other"]


def test_enabled_it_keeps_only_the_pending_saves_in_their_order(delete_at_teardown: DeleteAtTeardown) -> None:
    """On, only the saves that have not landed are left, in the queue's own order.

    **Test steps:**

    * build a filter over a mix of saves, other jobs and a row that is not a job at all, and enable it
    * verify it reads as on and lets only the failed and waiting saves through, in order
    """
    proxy = filter_over(
        source_of(
            status("failed", JobState.FAILED),
            status("landed", JobState.DONE),
            status("other", JobState.WAITING, OTHER_KIND),
            "not a job",
            status("waiting", JobState.WAITING),
            status("dropped", JobState.CANCELLED),
        ),
        delete_at_teardown,
    )

    proxy.set_enabled(True)

    assert proxy.enabled is True
    assert shown_labels(proxy) == ["failed", "waiting"]


def test_disabled_again_every_row_comes_back(delete_at_teardown: DeleteAtTeardown) -> None:
    """Turning the filter off shows the whole queue again.

    **Test steps:**

    * enable a filter over a done save and a waiting one, then disable it
    * verify it reads as off and lets both through
    """
    proxy = filter_over(
        source_of(status("landed", JobState.DONE), status("waiting", JobState.WAITING)), delete_at_teardown
    )
    proxy.set_enabled(True)

    proxy.set_enabled(False)

    assert proxy.enabled is False
    assert shown_labels(proxy) == ["landed", "waiting"]


def test_asking_for_the_state_it_is_in_does_not_refilter(
    delete_at_teardown: DeleteAtTeardown, mocker: MockerFixture
) -> None:
    """Setting the filter to what it already is changes nothing, so nothing is re-tested.

    **Test steps:**

    * patch a fresh filter's ``invalidate``
    * disable it while it is already off
    * verify it never re-filtered
    """
    proxy = filter_over(source_of(status("waiting", JobState.WAITING)), delete_at_teardown)
    invalidate = mocker.patch.object(proxy, "invalidate")

    proxy.set_enabled(False)

    invalidate.assert_not_called()


# endregion
