"""One `.tc` conversion, as a task-queue job ([[acquisition-tooling#tc-to-rehu]], #192).

`rehuco_core.tc_conversion` ships :func:`~rehuco_core.convert_tc` as a plain callable; this is the class
that wraps one call in the queue's vocabulary, so a bulk import (#192) can enqueue thousands of them and
let the engine run them one at a time rather than blocking the GUI thread on the first.

**Not tracked through a** :class:`~rehuco_core.RenameCoordinator`, unlike the checksum jobs
([[appendices.task-queue#job-responsibility]], #241): a `.tc` file is not a document the app's own
rename UI can touch before it has been converted, so there is nothing for this job's ``source`` to
follow mid-run. It answers the same path for its whole life, which costs nothing.

**Not safely interruptible, and it does not resume.** The one call to :func:`~rehuco_core.convert_tc`
either completes -- rolling back on its own failure -- or never starts; there is no natural division
point inside it for :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint` to divide, so a pause or cancel
asked of a *running* one has no effect until it returns on its own. A **queued** one is cancelled
outright and never starts at all ([[appendices.task-queue#job-responsibility]]) -- which is the whole of
what #192's "cancel stops after the current resource" means: nothing asks a running conversion to stop
mid-file, only the ones still waiting their turn.
"""

import logging
from pathlib import Path
from typing import Any, Final

from .plugins import DEFAULT_UNKNOWN_USERNAME
from .rehu_document import RehuDocument
from .tasks import DEFAULT_TASK_JOB_REGISTRY, JobControl, TaskJobBase
from .tc_conversion import convert_tc
from .tc_conversion_backups import LEGACY_SUFFIX

LOG: Final = logging.getLogger(__name__)

TC_IMPORT_KIND: Final = "tc-import"
"""What a saved queue spells this job as ([[appendices.task-queue#lifetime]]) -- a promise once written
into a user's queue file, never casually renamed."""

INFO_TC_FILENAME: Final = f"info{LEGACY_SUFFIX}"
"""A directory-scoped `.tc` resource's filename, the legacy counterpart of
:data:`~rehuco_core.INFO_REHU_FILENAME` -- what :func:`resource_name` tells apart from a file-scoped one."""

STATE_PATH_KEY: Final = "path"
STATE_OVERWRITE_KEY: Final = "overwrite"
STATE_KEEP_BACKUPS_KEY: Final = "keep_backups"
STATE_USERNAME_KEY: Final = "username"
"""The keys this job writes itself down under, read back by this class and nothing else
([[appendices.task-queue#lifetime]])."""


def resource_name(tc_path: Path) -> str:
    """How a `.tc` resource is named in a job's label -- the directory for ``info.tc``, else the filename.

    The legacy-scoping rule ([[data-model#resource-scoping]]) applied to a label, the same shape
    :func:`~rehuco_core.checksum_jobs.resource_name` follows for a converted ``.rehu``.

    :param tc_path: the resource's `.tc` file.
    :returns: the display name.
    """
    return tc_path.parent.name if tc_path.name == INFO_TC_FILENAME else tc_path.name


class TcImportJob(TaskJobBase):
    """Convert one legacy `.tc` into a real `.rehu`, on the queue (#192).

    **Keeps its backups by default** (``keep_backups=True``): the wizard this job exists for never
    offers the discard variant (#193's, deliberately, afterwards) -- retaining every backup is what
    makes an unattended bulk run safe at all, since nothing is deleted and any one resource can be
    reverted (#190) if the conversion made the wrong call.

    :param tc_path: the `.tc` file to convert, or ``None`` for a job about to be handed a saved state.
    :param overwrite: whether an existing target ``.rehu`` may be replaced -- the wizard's per-row
        opt-in for a resource :attr:`~rehuco_core.TcConversionPlan.rehu_exists` flagged as blocked.
    :param keep_backups: whether to keep the ``.orig`` backups after a successful conversion.
    :param username: the identity the imported per-user flags are filed under; see
        :func:`~rehuco_core.convert_tc`.
    :param label: how the job is named to a reader, or ``None`` for one derived from the path.
    """

    kind = TC_IMPORT_KIND
    safely_interruptible = False

    def __init__(
        self,
        tc_path: Path | None = None,
        *,
        overwrite: bool = False,
        keep_backups: bool = True,
        username: str = DEFAULT_UNKNOWN_USERNAME,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.source = tc_path
        self.overwrite = overwrite
        self.keep_backups = keep_backups
        self.username = username
        self.label = label if label is not None else self.__derived_label()
        self.__document: RehuDocument | None = None

    @property
    def document(self) -> RehuDocument | None:
        """What the last completed run produced, or ``None`` before one has finished.

        Held for the surface that enqueued the job, the same discipline
        :attr:`~rehuco_core.ChecksumJob.report` is under: the engine carries progress and an outcome,
        deliberately not a payload, so a caller that wants the result reads it off the job object it
        built, once the job has finished.
        """
        return self.__document

    def validate(self) -> str | None:
        """Say whether this conversion can still start -- a stat, not a walk.

        :returns: ``None`` when the `.tc` is there, else what is wrong with it.
        """
        path = self.source
        if path is None:
            return "This task has no resource."
        if not path.exists():
            return f"The .tc file no longer exists: {path}"
        return None

    def reset(self) -> None:
        """Drop the last run's result along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__document = None

    def run(self, control: JobControl) -> None:
        """Convert this job's `.tc`, reporting nothing but start and finish.

        One call, one file: :func:`~rehuco_core.convert_tc` divides no further, so there is nothing
        finer than *not started* / *done* for :meth:`~rehuco_core.tasks.JobControl.report` to say --
        which is why this job declares no :attr:`~rehuco_core.tasks.TaskJob.progress_unit` (#248): a
        cell jumping from empty to full says nothing the state column does not already.

        :param control: the engine's face to this job.
        :raises FileExistsError: the target ``.rehu`` exists and :attr:`overwrite` is ``False``, or a
            stale ``.orig`` backup is in the way -- see :func:`~rehuco_core.convert_tc`.
        :raises RehuFormatError: the `.tc` could not be parsed.
        """
        control.report(0, 1)
        self.__document = convert_tc(
            self.resource_path(), keep_backups=self.keep_backups, overwrite=self.overwrite, username=self.username
        )
        control.report(1, 1)
        LOG.info("Converted %s.", self.resource_path())

    def resource_path(self) -> Path:
        """This job's `.tc` file, refusing a job that has none.

        :returns: the `.tc` path.
        :raises ValueError: the job was built without a path and never given a state.
        """
        path = self.source
        if path is None:
            raise ValueError("An import job has no resource to convert.")
        return path

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        :returns: JSON primitives only -- the path as text, and the run's parameters.
        """
        path = self.source
        return {
            STATE_PATH_KEY: str(path) if path is not None else "",
            STATE_OVERWRITE_KEY: self.overwrite,
            STATE_KEEP_BACKUPS_KEY: self.keep_backups,
            STATE_USERNAME_KEY: self.username,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Read defensively, matching :meth:`~rehuco_core.ChecksumJob.restore_state`'s discipline: a
        missing or malformed path raises, and the registry logs and drops the item.

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a runnable job.
        """
        path = state.get(STATE_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved import task names no resource.")
        overwrite = state.get(STATE_OVERWRITE_KEY, False)
        keep_backups = state.get(STATE_KEEP_BACKUPS_KEY, True)
        username = state.get(STATE_USERNAME_KEY, DEFAULT_UNKNOWN_USERNAME)
        if not isinstance(username, str):
            raise ValueError("A saved import task's username is not a string.")
        self.source = Path(path)
        self.overwrite = bool(overwrite)
        self.keep_backups = bool(keep_backups)
        self.username = username
        self.label = self.__derived_label()

    def __derived_label(self) -> str:
        """This job's own name for itself, e.g. ``"Import legacy catalog - Sculpting Series"``.

        A fallback rather than the usual answer: a restored item's saved label is used in preference
        ([[appendices.task-queue#lifetime]]), so a row comes back reading exactly as it was written.
        """
        path = self.source
        if path is None:
            return "Import legacy catalog"
        return f"Import legacy catalog - {resource_name(path)}"


DEFAULT_TASK_JOB_REGISTRY.register(TC_IMPORT_KIND, TcImportJob)
