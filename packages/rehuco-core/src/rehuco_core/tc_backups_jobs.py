"""Reverting a conversion, and discarding its backups, as task-queue jobs
([[acquisition-tooling#convert-mechanics]], #193).

`rehuco_core.tc_conversion_backups` ships both operations as plain callables; these are the classes that
wrap one call each in the queue's vocabulary, so the backups manager (#193) can act on a whole catalog's
worth of resources without blocking the GUI thread on the first. The mirror of
`rehuco_core.tc_import_job`, which does the same for the forward direction.

**Neither is safely interruptible, and neither resumes.** One resource, one call: the underlying
operation either completes -- rolling back on its own failure, in the revert's case -- or never starts,
and there is no natural division point inside it for
:meth:`~rehuco_core.tasks.TaskJobBase.checkpoint` to divide. A pause or cancel asked of a *running* one
has no effect until it returns on its own; a **queued** one is cancelled outright and never starts
([[appendices.task-queue#job-responsibility]]). That is the whole of what #192's "cancel stops after the
current resource" means here too.

**Not tracked through a** :class:`~rehuco_core.RenameCoordinator`, for the same reason
`rehuco_core.tc_import_job` is not (#241): both operations rename the very files a coordinator would
follow, so there is nothing stable for a running job's ``source`` to track. It answers the same path for
its whole life, which costs nothing.
"""

import logging
from pathlib import Path
from typing import Any, Final

from .resource_scoping import resource_name
from .tasks import DEFAULT_TASK_JOB_REGISTRY, JobControl, TaskJobBase
from .tc_conversion_backups import ConversionBackups, discard_conversion_backups, revert_conversion

LOG: Final = logging.getLogger(__name__)

TC_REVERT_KIND: Final = "tc-revert"
TC_DISCARD_KIND: Final = "tc-discard"
"""What a saved queue spells these jobs as ([[appendices.task-queue#lifetime]]) -- a promise once written
into a user's queue file, never casually renamed."""

STATE_PATH_KEY: Final = "path"
"""The key these jobs write themselves down under, read back by this module and nothing else
([[appendices.task-queue#lifetime]])."""


class TcBackupsJob(TaskJobBase):
    """One operation over one converted resource's retained backups, queued rather than run inline (#193).

    Subclasses supply :attr:`kind`, :attr:`verb` and :meth:`perform`; the location, the label, the validation
    and the saved state are the same for both, because what differs between reverting and discarding is
    entirely inside the two callables `rehuco_core.tc_conversion_backups` already ships.

    :param rehu_path: the converted resource's ``.rehu`` file, or ``None`` for a job about to be handed a
        saved state -- the only way one is legitimately built without a path, and why the registry can
        use the class itself as a factory.
    :param label: how the job is named to a reader, or ``None`` for one derived from the path.
    """

    kind: str = ""
    """The stable saved name; set by each subclass, empty on this base, which is never registered."""

    verb: str = ""
    """What this job does, for the label and the log -- ``"Revert conversion"`` or ``"Discard backups"``."""

    safely_interruptible = False

    def __init__(self, rehu_path: Path | None = None, *, label: str | None = None) -> None:
        super().__init__()
        self.source = rehu_path
        self.label = label if label is not None else self.__derived_label()

    def validate(self) -> str | None:
        """Say whether this operation can still start -- a stat, not a walk.

        :returns: ``None`` when the resource's directory is still there, else what is wrong with it.
            The ``.rehu`` itself is deliberately **not** required to exist: a discard is about the
            ``.orig`` siblings, and a revert over a resource whose ``.rehu`` was deleted by hand still
            has originals to put back.
        """
        path = self.source
        if path is None:
            return "This task has no resource."
        if not path.parent.exists():
            return f"The resource folder no longer exists: {path.parent}"
        return None

    def run(self, control: JobControl) -> None:
        """Do this job's one operation, reporting nothing but start and finish.

        One call, one resource: neither underlying operation divides further, so there is nothing finer
        than *not started* / *done* for :meth:`~rehuco_core.tasks.JobControl.report` to say -- and with
        no division there is nothing for :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint` to interrupt,
        which is what :attr:`safely_interruptible` reports. Nothing worth drawing either, so this job
        declares no :attr:`~rehuco_core.tasks.TaskJob.progress_unit` (#248).

        :param control: the engine's face to this job.
        :raises OSError: whatever the operation refuses with; see each subclass's :meth:`perform`. The
            engine turns it into a failed status carrying the message.
        """
        control.report(0, 1)
        self.perform(self.resource_path())
        control.report(1, 1)
        LOG.info("%s: %s.", self.verb, self.resource_path())

    def perform(self, rehu_path: Path) -> None:
        """Make the change this job is for, keeping whatever it produced for the enqueuer to read back.

        The one thing a subclass adds, and the reason there are two of them: everything around it -- the
        location, the label, the stop declarations, the progress bracket and the log line -- is
        :meth:`run`'s.

        :param rehu_path: the converted resource's ``.rehu`` file.
        :raises NotImplementedError: always; this base is not a job on its own.
        """
        raise NotImplementedError

    def resource_path(self) -> Path:
        """This job's ``.rehu`` file, refusing a job that has none.

        :returns: the ``.rehu`` path.
        :raises ValueError: the job was built without a path and never given a state.
        """
        path = self.source
        if path is None:
            raise ValueError(f"A {self.kind} job has no resource to work on.")
        return path

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        :returns: JSON primitives only -- the path, as text.
        """
        path = self.source
        return {STATE_PATH_KEY: str(path) if path is not None else ""}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Read defensively, matching :meth:`~rehuco_core.TcImportJob.restore_state`'s discipline: a missing
        or malformed path raises, and the registry logs and drops the item.

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a runnable job.
        """
        path = state.get(STATE_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError(f"A saved {self.kind} task names no resource.")
        self.source = Path(path)
        self.label = self.__derived_label()

    def __derived_label(self) -> str:
        """This job's own name for itself, e.g. ``"Revert conversion - Sculpting Series"``.

        A fallback rather than the usual answer: a restored item's saved label is used in preference
        ([[appendices.task-queue#lifetime]]), so a row comes back reading exactly as it was written.
        """
        path = self.source
        if path is None:
            return self.verb
        return f"{self.verb} - {resource_name(path)}"


class RevertConversionJob(TcBackupsJob):
    """Undo one completed conversion from its retained backups, on the queue (#193).

    **The written ``.rehu`` is deleted**, discarding any edit made since the conversion -- the honest
    meaning of *undo the conversion* (:func:`~rehuco_core.revert_conversion`). Warning about that is the
    enqueuer's job, before the row ever reaches the queue: by the time this runs there is nobody left to
    ask.
    """

    kind = TC_REVERT_KIND
    verb = "Revert conversion"

    def __init__(self, rehu_path: Path | None = None, *, label: str | None = None) -> None:
        super().__init__(rehu_path, label=label)
        self.__reverted: ConversionBackups | None = None

    @property
    def reverted(self) -> ConversionBackups | None:
        """What the last completed run put back, or ``None`` before one has finished.

        Held for the surface that enqueued the job, the same discipline
        :attr:`~rehuco_core.TcImportJob.document` is under: the engine carries progress and an outcome,
        deliberately not a payload, so a caller that wants the result reads it off the job object it
        built, once the job has finished.
        """
        return self.__reverted

    def reset(self) -> None:
        """Drop the last run's result along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__reverted = None

    def perform(self, rehu_path: Path) -> None:
        """See :meth:`TcBackupsJob.perform` -- :func:`~rehuco_core.revert_conversion`.

        :param rehu_path: the converted resource's ``.rehu`` file.
        :raises FileNotFoundError: no backed-up ``.tc`` sits beside the resource.
        :raises FileExistsError: a restore target is occupied, or a leftover staging file is in the way.
        """
        self.__reverted = revert_conversion(rehu_path)


class DiscardBackupsJob(TcBackupsJob):
    """Delete one converted resource's retained backups, making the conversion permanent (#193).

    **The one irreversible step in the whole import flow.** Nothing here confirms anything -- by the time
    a job is on the queue the decision has been made, and the confirmation belongs where a human is
    (#193's dialog and the document's own action).
    """

    kind = TC_DISCARD_KIND
    verb = "Discard backups"

    def __init__(self, rehu_path: Path | None = None, *, label: str | None = None) -> None:
        super().__init__(rehu_path, label=label)
        self.__discarded: tuple[Path, ...] | None = None

    @property
    def discarded(self) -> tuple[Path, ...] | None:
        """What the last completed run deleted, or ``None`` before one has finished; see
        :attr:`RevertConversionJob.reverted` for why this is read off the job rather than carried."""
        return self.__discarded

    def reset(self) -> None:
        """Drop the last run's result along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__discarded = None

    def perform(self, rehu_path: Path) -> None:
        """See :meth:`TcBackupsJob.perform` -- :func:`~rehuco_core.discard_conversion_backups`.

        :param rehu_path: the converted resource's ``.rehu`` file.
        """
        self.__discarded = discard_conversion_backups(rehu_path)


DEFAULT_TASK_JOB_REGISTRY.register(TC_REVERT_KIND, RevertConversionJob)
DEFAULT_TASK_JOB_REGISTRY.register(TC_DISCARD_KIND, DiscardBackupsJob)
