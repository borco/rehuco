"""Tests for `RehuDocumentModel.rename_lock_reason` -- locking the location editor while an unfinished
task-queue job's ``source`` sits among the paths a rename would move (#240).
"""

from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Final

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import JobControl, JobState, RehuDocument, TaskJobBase, TaskQueue

TIMEOUT: Final = 5.0
"""How long a test waits for the worker thread before calling it a failure, in seconds."""

DIRECTORY: Final = Path("C:/tutorials")
FOLDER: Final = DIRECTORY / "old_folder"
INFO_PATH: Final = FOLDER / "info.rehu"
FILE_PATH: Final = DIRECTORY / "old_file.rehu"


class GatedJob(TaskJobBase):
    """A job the test holds mid-run, so it is demonstrably unfinished until released.

    :param label: the job's label.
    :param source: the job's declared :attr:`~rehuco_core.tasks.TaskJob.source`.
    """

    def __init__(self, label: str, source: Path | None) -> None:
        super().__init__()
        self.label = label
        self.source = source
        self.entered: Final = Event()
        self.release: Final = Event()

    def run(self, control: JobControl) -> None:
        """Announce, then wait for the test to let it go.

        :param control: unused.
        """
        del control
        self.entered.set()
        self.release.wait(TIMEOUT)


@fixture(name="queue")
def queue_fixture() -> Iterator[TaskQueue]:
    """A queue that is always shut down, so no test can leave a worker thread behind."""
    queue = TaskQueue()
    yield queue
    queue.shutdown()


def start_gated_job(queue: TaskQueue, source: Path | None, label: str = "busy") -> tuple[GatedJob, int]:
    """Enqueue a :class:`GatedJob` and wait until it is demonstrably running.

    :param queue: the queue to enqueue it on.
    :param source: the job's declared source.
    :param label: the job's label.
    :returns: the running job, held until :attr:`GatedJob.release` is set, and its serial.
    """
    job = GatedJob(label, source)
    serial = queue.enqueue(job)
    assert job.entered.wait(TIMEOUT)
    return job, serial


def mock_file_scoped_siblings(mocker: MockerFixture, siblings: list[Path]) -> None:
    """Mock the directory listing a file-scoped resource's :func:`~rehuco_core.rehu_rename_affects`
    sweeps, so the model's rename-lock check never touches the real filesystem.

    :param mocker: pytest-mock fixture.
    :param siblings: the whole directory listing to hand back.
    """
    mocker.patch.object(Path, "iterdir", autospec=True, side_effect=lambda self: list(siblings))
    mocker.patch.object(Path, "is_dir", autospec=True, side_effect=lambda self: False)


# region directory-scoped resource
def test_a_busy_nested_resource_locks_the_ancestor_directory(queue: TaskQueue) -> None:
    """A job about a resource nested beneath a directory-scoped resource locks it -- renaming the
    directory carries the nested resource along.

    **Test steps:**

    * build a model over a directory-scoped resource
    * start a job whose ``source`` is a resource two levels beneath it
    * verify the model reports a lock reason
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, FOLDER / "sub" / "info.rehu")

    assert model.rename_lock_reason() is not None

    job.release.set()


def test_a_busy_file_scoped_sibling_locks_the_containing_directory(queue: TaskQueue) -> None:
    """A job about a file-scoped resource sitting directly inside the directory locks it too --
    renaming the directory carries it along as well.

    **Test steps:**

    * build a model over a directory-scoped resource
    * start a job whose ``source`` is a file-scoped resource inside that directory
    * verify the model reports a lock reason
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, FOLDER / "xxx.rehu")

    assert model.rename_lock_reason() is not None

    job.release.set()


def test_a_busy_sibling_directory_does_not_lock(queue: TaskQueue) -> None:
    """A job about a resource in a **different** directory beside this one does not lock it.

    **Test steps:**

    * build a model over a directory-scoped resource
    * start a job whose ``source`` is a resource in a sibling directory
    * verify the model reports no lock reason
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, DIRECTORY / "other_folder" / "info.rehu")

    assert model.rename_lock_reason() is None

    job.release.set()


# endregion


# region file-scoped resource
def test_a_busy_job_on_the_resources_own_rehu_locks_it(queue: TaskQueue, mocker: MockerFixture) -> None:
    """A file-scoped resource locks on a job about its own ``.rehu``.

    **Test steps:**

    * mock the directory listing to just the resource's own `.rehu`
    * build a model over it and start a job whose ``source`` is that same path
    * verify the model reports a lock reason
    """
    mock_file_scoped_siblings(mocker, [FILE_PATH])
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FILE_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, FILE_PATH)

    assert model.rename_lock_reason() is not None

    job.release.set()


def test_a_busy_job_on_the_resources_own_screenshot_locks_it(queue: TaskQueue, mocker: MockerFixture) -> None:
    """A file-scoped resource locks on a job about one of its own screenshots -- named after it, so a
    rename would carry it along.

    **Test steps:**

    * mock the directory listing to the resource's `.rehu` plus one screenshot
    * build a model over it and start a job whose ``source`` is that screenshot
    * verify the model reports a lock reason
    """
    screenshot = DIRECTORY / "old_file00.jpg"
    mock_file_scoped_siblings(mocker, [FILE_PATH, screenshot])
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FILE_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, screenshot)

    assert model.rename_lock_reason() is not None

    job.release.set()


def test_a_busy_job_on_a_foreign_rehus_files_does_not_lock(queue: TaskQueue, mocker: MockerFixture) -> None:
    """A file-scoped resource is not locked by a job on a **different**, foreign resource's files, even
    one named after it -- ``old_file2.rehu``'s own set is excluded from ``old_file.rehu``'s sibling set.

    **Test steps:**

    * mock the directory listing to include a foreign ``old_file2.rehu`` and one of its own files
    * build a model over ``old_file.rehu`` and start a job whose ``source`` is the foreign resource's file
    * verify the model reports no lock reason
    """
    foreign_rehu = DIRECTORY / "old_file2.rehu"
    foreign_file = DIRECTORY / "old_file200.jpg"
    mock_file_scoped_siblings(mocker, [FILE_PATH, foreign_rehu, foreign_file])
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FILE_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, foreign_file)

    assert model.rename_lock_reason() is None

    job.release.set()


# endregion


# region finished jobs, no queue, and living reactivity
def test_a_finished_job_locks_nothing(queue: TaskQueue, qtbot: QtBot) -> None:
    """A job that has already run to completion is kept in the queue but is not about to touch
    anything, so it locks nothing -- and the lock a still-running job held lifts once it finishes.

    **Test steps:**

    * build a model over a directory-scoped resource and start a job locking it
    * verify the model reports a lock reason while the job runs
    * release the job, wait for it to finish
    * verify the model reports no lock reason anymore
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, FOLDER / "sub" / "info.rehu")
    assert model.rename_lock_reason() is not None

    job.release.set()
    qtbot.waitUntil(lambda: queue.jobs()[0].state == JobState.DONE, timeout=int(TIMEOUT * 1000))

    assert model.rename_lock_reason() is None


def test_the_lock_lifts_once_the_job_is_removed(queue: TaskQueue) -> None:
    """Removing the busy job from the queue lifts the lock immediately -- ``remove`` drops the row from
    :meth:`~rehuco_core.TaskQueue.jobs` at once, even for a still-physically-running job (it cancels the
    job and lets it finish out of sight, [[appendices.task-queue#kept]]).

    **Test steps:**

    * build a model over a directory-scoped resource and start a job locking it
    * remove the job
    * verify the model reports no lock reason anymore
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH), task_queue=queue)
    job, serial = start_gated_job(queue, FOLDER / "sub" / "info.rehu")
    assert model.rename_lock_reason() is not None

    queue.remove(serial)

    assert model.rename_lock_reason() is None
    job.release.set()


def test_an_unlistable_directory_reads_as_unlocked(queue: TaskQueue, mocker: MockerFixture) -> None:
    """A file-scoped resource whose directory cannot be listed -- an offline mount -- reads as
    unlocked rather than raising out of the render: a rename attempted there fails cleanly through
    ``rename_error`` anyway, where a lock would claim a busy job the model cannot actually see.

    **Test steps:**

    * make any attempt to list a directory raise
    * build a model over a file-scoped resource and start a job on its own path
    * verify the model reports no lock reason, and no error escapes
    """
    mocker.patch.object(Path, "iterdir", autospec=True, side_effect=OSError("offline mount"))
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FILE_PATH), task_queue=queue)
    job, _ = start_gated_job(queue, FILE_PATH)

    assert model.rename_lock_reason() is None

    job.release.set()


def test_a_model_with_no_task_queue_is_never_locked() -> None:
    """A model built with no task queue at all (most tests, most callers with nothing to offer) is
    never locked by this.

    **Test steps:**

    * build a model over a directory-scoped resource with no ``task_queue``
    * verify the model reports no lock reason
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))

    assert model.rename_lock_reason() is None


def test_a_pathless_document_is_never_locked(queue: TaskQueue) -> None:
    """A document with no location yet has no destination a rename could move, so it is never locked.

    **Test steps:**

    * build a model with no path, over a queue holding a job
    * verify the model reports no lock reason
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}), task_queue=queue)
    job, _ = start_gated_job(queue, FOLDER / "sub" / "info.rehu")

    assert model.rename_lock_reason() is None

    job.release.set()


def test_refresh_rename_lock_reason_emits_the_changed_signal() -> None:
    """:meth:`~RehuDocumentModel.refresh_rename_lock_reason` re-announces the answer -- the seam
    `DocumentsDock` calls on every open model when the task queue changes.

    **Test steps:**

    * connect to ``rename_lock_reason_changed``
    * call ``refresh_rename_lock_reason``
    * verify the signal fired
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))
    received: list[None] = []
    model.rename_lock_reason_changed.connect(lambda: received.append(None))  # type: ignore[attr-defined]

    model.refresh_rename_lock_reason()

    assert len(received) == 1


# endregion
