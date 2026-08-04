"""What a job must add to be written down, and what one looks like on disk
([[appendices.task-queue#lifetime]]).

A second protocol rather than a wider one: :class:`~rehuco_core.tasks.TaskJob` is unchanged, and a job
satisfying only that one is legal -- it simply is not saved. The constraint §6 of the appendix warned
about is real and is now accepted **only by the jobs that opt in**.

Grouped rather than split one class per file for the same reason
:mod:`~rehuco_core.tasks.task_job` groups its own vocabulary: the record is what the protocol produces,
and neither means much without the other.
"""

from typing import Any, NotRequired, Protocol, TypedDict, runtime_checkable

from .task_job import TaskJob


@runtime_checkable
class PersistableTaskJob(TaskJob, Protocol):
    """A job that can be written down and reconstructed in a later run of the app.

    **The job class is the unit of responsibility** ([[appendices.task-queue#job-responsibility]]): how
    it captures itself, what that state holds, and how it picks up on reconstruction are one class's
    business. The registry, the queue and the file know only :attr:`kind` and an opaque blob, and
    **nothing in between inspects one** -- the class that wrote a state is the class that reads it.

    Two obligations come with implementing this, and they are worth knowing before starting:

    - the state may hold **only what survives a round trip through JSON**, which is what stops a job
      being an arbitrary object closing over whatever it needs;
    - :attr:`kind` is a promise that cannot be casually renamed, because it is written into files the
      user already has.

    A job that would rather not pay either is not obliged to: it satisfies
    :class:`~rehuco_core.tasks.TaskJob` alone, and :attr:`~rehuco_core.tasks.JobStatus.persistable`
    says so on every status, so a surface can mark the row rather than let it vanish at quit.
    """

    kind: str
    """The stable name this job is written under, e.g. ``"checksum-verify"``.

    **A name, not a class path** ([[appendices.task-queue#lifetime]]). A class path would bake today's
    module layout into the user's saved queue, and this repo has already moved its packages once
    (#157); the registry is the indirection that turns a rename into a one-line map change instead of
    an unreadable file.
    """

    def validate(self) -> str | None:
        """Say whether this job can still be started, **now**.

        Called before *every* start, not only after a restore, so one rule covers both the
        restored-resource-is-gone case and the deleted-while-queued one. A non-``None`` answer puts the
        job in :attr:`~rehuco_core.tasks.JobState.FAILED` with that sentence as its error -- no new
        terminal state -- and because a failed job is kept and retryable, the natural recovery is to fix
        the cause and press Retry.

        Called on the worker thread with the queue's lock held, so it must be **quick**: a stat, not a
        walk.

        :returns: ``None`` when the job is startable, else one sentence a reader can act on, e.g.
            ``"The resource no longer exists: C:/lib/Sculpting/info.rehu"``.
        """

    def capture_state(self) -> dict[str, Any]:  # pyright: ignore[reportReturnType]
        """Hand over everything this job needs to be itself again in a later run.

        **Called only when the job is not running**, so it never reads state that is mutating on the
        worker thread. The engine holds the last state it captured for a job it cannot ask.

        The same pair as the cursor a paused job already keeps ([[appendices.task-queue#cursor]]),
        which is what keeps in-session resume and across-restart resume one concept rather than two.

        :returns: JSON primitives only -- ``dict``, ``list``, ``str``, ``int``, ``float``, ``bool``,
            ``None``. Empty is a legitimate answer for a job that starts over.
        """

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Called once, on a job the registry has just built, before anything else is asked of it.

        :param state: whatever this class's own :meth:`capture_state` returned, verbatim -- or, from a
            file someone edited, whatever was there instead. A job that cannot make sense of it raises,
            and the item is dropped with a logged warning rather than restored half-built.
        """


class TaskQueueItem(TypedDict):
    """One saved job, as it is written down ([[appendices.task-queue#lifetime]]).

    The shape the queue serializes to and restores from, and the only thing the surface that owns the
    file has to understand -- it filters a list of these and never opens one up. ``state`` is the job's
    own and is opaque to everything but the class that wrote it.

    :param kind: the job's :attr:`PersistableTaskJob.kind`, which is what finds its factory again.
    :param label: the job's :attr:`~rehuco_core.tasks.TaskJob.label`, written so a queue file can be
        read by a person and **restored in preference to the rebuilt job's own**, so that the list
        comes back reading exactly as the one that was saved -- a row the user recognizes rather than
        whatever a default-constructed job would have called itself.
    :param job_state: the :class:`~rehuco_core.tasks.JobState` the job was in. Spelled apart from
        ``state`` because they are different things: this is where the job had got to, that is what the
        job kept.
    :param state: the job's own :meth:`PersistableTaskJob.capture_state`.
    :param error: why a failed job failed, kept so a restored failure still says what went wrong.
    :param done: units finished. **Written only for a job that declares**
        :attr:`~rehuco_core.tasks.TaskJob.resumes_where_it_stopped`, because only such a job genuinely
        is as far along as its bar says; for a job that starts over, restoring a bar that is about to
        reset would be a lie the first progress report corrects.
    :param total: units expected, written under the same condition as ``done``.
    """

    kind: str
    label: str
    job_state: str
    state: dict[str, Any]
    error: NotRequired[str | None]
    done: NotRequired[int]
    total: NotRequired[int | None]
