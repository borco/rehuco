"""The two checksum runs, as task-queue jobs ([[data-model#checksums]], #204).

`rehuco_core.rehu_checksums` ships generate and verify as plain callables taking a progress callback
and a checkpoint (#203); this is the class that wraps one in the queue's vocabulary, and it is the only
place the two halves meet. **A gigabyte-scale hash never runs inline**: that is what the queue exists
to prevent, and it is why a surface offering these operations enqueues rather than calls.

**Two classes, not one with a flag.** Each carries its own :attr:`~rehuco_core.tasks.PersistableTaskJob.kind`,
which is written into the user's saved queue and cannot be casually renamed
([[appendices.task-queue#lifetime]]) -- so the distinction has to be a class either way. What they
genuinely share is everything *around* the run: where the resource is, how the selection is spelled,
what a stop costs, and how the run is written down. That lives in :class:`ChecksumJob`, and each
subclass is its verb plus its call.

**Reads go through a rename coordinator** (#241), so a folder renamed mid-hash costs one chunk rather
than the length of the job, and the row keeps naming the resource rather than the path it started at.
A job holds a :class:`~rehuco_core.ResourceLocation` for exactly that reason: ``source`` is re-read
from another thread while ``run`` executes ([[appendices.task-queue#job-responsibility]]).
"""

import logging
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

from .checksum_algorithms import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM
from .checksum_record import checksum_record_path
from .constants import EXCLUDED_FILE_PATTERNS, INFO_REHU_FILENAME
from .rehu_checksums import ChecksumReport, generate_checksums, verify_checksums
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .tasks import DEFAULT_TASK_JOB_REGISTRY, JobControl, TaskJobBase

LOG: Final = logging.getLogger(__name__)

CHECKSUM_GENERATE_KIND: Final = "checksum-generate"
CHECKSUM_VERIFY_KIND: Final = "checksum-verify"
"""What a saved queue spells these jobs as ([[appendices.task-queue#lifetime]]).

Names rather than class paths, and a promise once written into a user's queue file: renaming one
strands every saved job that carries it."""

STATE_PATH_KEY: Final = "path"
STATE_ALGORITHM_KEY: Final = "algorithm"
STATE_ONLY_KEY: Final = "only"
STATE_EXCLUDED_PATTERNS_KEY: Final = "excluded_patterns"
"""The keys one of these jobs writes itself down under.

Read back by the class that wrote them and by nothing else ([[appendices.task-queue#lifetime]]) -- the
registry, the queue and the file all treat the state as opaque.

The exclusion set is captured with the rest rather than re-resolved from the settings on restore: a
restored job is meant to be *the job that was queued*, and the list decides which unlisted files a run
adopts, which is part of what was asked for."""


def resource_name(rehu_path: Path) -> str:
    """How a resource is named in a job's label -- the directory for an ``info.rehu``, else the filename.

    The ``.rehu``-scoping rule ([[data-model#resource-scoping]]) applied to a label: every
    directory-scoped resource's record is called ``info.rehu``, so naming the file would give a queue of
    fifty jobs fifty identical rows.

    :param rehu_path: the resource's ``.rehu`` file.
    :returns: the display name.
    """
    return rehu_path.parent.name if rehu_path.name == INFO_REHU_FILENAME else rehu_path.name


class ChecksumJob(TaskJobBase):
    """One checksum run over one resource, queued rather than run inline (#204).

    Subclasses supply :attr:`kind`, :attr:`verb` and :meth:`perform`; everything else -- the location,
    the selection, the label, the validation and the saved state -- is the same for both, because what
    differs between generating and verifying is entirely inside #203's callables.

    **Safely interruptible, and it starts over.** The record is written once, at the end, through the
    atomic writer, so a stop between chunks leaves the previous record exactly as it was
    ([[data-model#checksums]]) -- there is nothing to leave behind, and nothing to undo. Nothing is
    kept between runs either: a paused run re-hashes from the top, which is *wasteful rather than
    wrong* ([[appendices.task-queue#job-responsibility]]) and is what
    :attr:`~rehuco_core.tasks.TaskJob.resumes_where_it_stopped` reports so a dock can say so before
    someone pauses one. The sweep that genuinely resumes is #242's, and it resumes from the records it
    has already written rather than from a cursor of its own.

    :param rehu_path: the resource's ``.rehu`` file, or ``None`` for a job about to be handed a saved
        state -- which is the only way one is legitimately built without a path, and why the registry
        can use the class itself as a factory.
    :param coordinator: the rename barrier to read through (#241); the process-wide one unless a test
        says otherwise.
    :param algorithm: what new hashes are recorded under.
    :param only: the record-relative names to work on, or ``None`` for the whole resource.
    :param excluded_patterns: the filename globs the content walk leaves out (#226), resolved by the
        caller -- core never reads a setting.
    :param label: how the job is named to a reader, or ``None`` for one derived from the path.
    """

    kind: str = ""
    """The stable saved name; set by each subclass, empty on this base, which is never registered."""

    verb: str = ""
    """What this job does, for the label and the log -- ``"Generate"`` or ``"Verify"``."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        rehu_path: Path | None = None,
        *,
        coordinator: RenameCoordinator | None = None,
        algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
        only: Collection[str] | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__location = self.__coordinator.track(rehu_path) if rehu_path is not None else None
        self.algorithm = algorithm
        self.only: tuple[str, ...] | None = None if only is None else tuple(only)
        self.excluded_patterns = excluded_patterns
        self.label = label if label is not None else self.__derived_label()
        self.__report: ChecksumReport | None = None

    # region What the queue reads

    # a property over TaskJobBase's plain attribute, which is what the base documents as *overridden by
    # a job that is about one resource*: this one has to be re-read live, because the location moves
    # under a running job. The protocol (TaskJob.source) declares a property; only the base's
    # convenience default is an attribute, so the narrowing is a type-checker artifact rather than a
    # contract this breaks
    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """This job's resource, **as it is now** -- read from the tracked location, so a rename that
        landed mid-run answers the new path ([[appendices.task-queue#job-responsibility]], #241)."""
        return self.__location.path if self.__location is not None else None

    @property
    def report(self) -> ChecksumReport | None:
        """What the last completed run established, or ``None`` before one has finished.

        Held for the surface that enqueued the job, which is the only thing holding a reference to it:
        the engine carries progress and an outcome, deliberately not a payload
        ([[appendices.task-queue#job-responsibility]]), so a caller that wants the findings reads them
        from the job it built. Written on the worker thread and read once the job has finished, which
        is the same discipline :meth:`~rehuco_core.tasks.PersistableTaskJob.capture_state` is under.
        """
        return self.__report

    def validate(self) -> str | None:
        """Say whether this run can still start -- a stat, not a walk.

        Checked before *every* start ([[appendices.task-queue#lifetime]]), so a resource deleted while
        the job sat in the queue fails with a sentence rather than an exception out of the run, and
        Retry is the natural recovery once the mount is back.

        :returns: ``None`` when the resource is there, else what is wrong with it.
        """
        path = self.source
        if path is None:
            return "This task has no resource."
        if not path.exists():
            return f"The resource no longer exists: {path}"
        return None

    def reset(self) -> None:
        """Drop the last run's findings along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__report = None

    # endregion

    # region Running

    def run(self, control: JobControl) -> None:
        """Hash what this job is about, reporting bytes as they go.

        Progress is #203's own ``(done, total)`` handed straight to
        :meth:`~rehuco_core.tasks.JobControl.report` -- **bytes, not files**
        ([[data-model#checksums]]) -- and :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint` is passed
        as the run's checkpoint, so a pause or a cancel unwinds out of the read loop with the record
        unwritten.

        The summary is logged rather than returned: the engine carries an outcome and a progress
        number and nothing else, and the records land under the scope open when the job was enqueued
        ([[appendices.task-queue#scopes]]) -- which is the resource's own log.

        :param control: the engine's face to this job.
        :raises FileNotFoundError: the record is missing and this run may not create one.
        :raises ContentUnreachableError: the resource's directory would not list (#245) -- the failure
            row then says the mount is away, which is a different thing to retry than a missing record.
        :raises ChecksumRecordError: a record this build cannot read at all.
        :raises OSError: the record could not be written.
        """
        report = self.perform(control)
        self.__report = report
        LOG.info("%s: %s", self.label, checksum_report_summary(report))

    def perform(self, control: JobControl) -> ChecksumReport:
        """Make the run this job is for.

        The one thing a subclass adds, and the reason there are two of them: everything around it --
        the location, the selection, the stop protocol, the log line -- is :meth:`run`'s.

        :param control: the engine's face to this job.
        :returns: what the run established.
        :raises NotImplementedError: always; this base is not a job on its own.
        """
        raise NotImplementedError

    def resource_path(self) -> Path:
        """The resource this run works over, refusing a job that has none.

        :returns: the ``.rehu`` path, as of now.
        :raises ValueError: the job was built without a path and never given a state.
        """
        path = self.source
        if path is None:
            raise ValueError("A checksum job has no resource to work on.")
        return path

    @property
    def coordinator(self) -> RenameCoordinator:
        """The rename barrier this job's reads go through (#241)."""
        return self.__coordinator

    # endregion

    # region Being written down

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        JSON primitives only ([[appendices.task-queue#lifetime]]): the path as text, the algorithm, the
        selection as a list, and the exclusion set the enqueuer resolved.

        :returns: the state.
        """
        path = self.source
        return {
            STATE_PATH_KEY: str(path) if path is not None else "",
            STATE_ALGORITHM_KEY: self.algorithm,
            STATE_ONLY_KEY: None if self.only is None else list(self.only),
            STATE_EXCLUDED_PATTERNS_KEY: list(self.excluded_patterns),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Read defensively, because the file is editable and a build that cannot make sense of an item
        should drop that item rather than come up broken: a missing path, an algorithm this build does
        not ship, or a selection that is not a list of names raises, and the registry logs and drops
        the item ([[appendices.task-queue#lifetime]]).

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a runnable job.
        """
        path = state.get(STATE_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved checksum task names no resource.")
        algorithm = state.get(STATE_ALGORITHM_KEY, DEFAULT_CHECKSUM_ALGORITHM)
        if algorithm not in CHECKSUM_ALGORITHMS:
            raise ValueError(f"A saved checksum task names an unknown algorithm: {algorithm!r}")
        only = state.get(STATE_ONLY_KEY)
        if only is not None and not (isinstance(only, list) and all(isinstance(name, str) for name in only)):
            raise ValueError("A saved checksum task's selection is not a list of names.")
        excluded = state.get(STATE_EXCLUDED_PATTERNS_KEY)
        self.__location = self.__coordinator.track(Path(path))
        self.algorithm = algorithm
        self.only = None if only is None else tuple(only)
        if isinstance(excluded, list) and all(isinstance(pattern, str) for pattern in excluded):
            self.excluded_patterns = tuple(excluded)
        self.label = self.__derived_label()

    # endregion

    def __derived_label(self) -> str:
        """This job's own name for itself, e.g. ``"Verify checksums - Sculpting Series"``.

        A fallback rather than the usual answer: a restored item's saved label is used in preference
        ([[appendices.task-queue#lifetime]]), so a row comes back reading exactly as it was written,
        and an enqueuer with a better name for the resource passes one in.
        """
        path = self.source
        if path is None:
            return f"{self.verb} checksums"
        return f"{self.verb} checksums - {resource_name(path)}"


class GenerateChecksumsJob(ChecksumJob):
    """(Re-)baseline a resource's ``.checksum`` record, on the queue (#204).

    With no selection this writes the content files as they are; with one it re-baselines exactly the
    named entries and carries every other byte-for-byte -- which is how a change a verify reported is
    accepted, without re-reading the terabyte that was fine ([[data-model#checksums]]).
    """

    kind = CHECKSUM_GENERATE_KIND
    verb = "Generate"

    def perform(self, control: JobControl) -> ChecksumReport:
        """See :meth:`ChecksumJob.perform` -- :func:`~rehuco_core.generate_checksums`.

        ``create_if_missing`` is on: creating the record is what a first generate is *for*.

        :param control: the engine's face to this job.
        :returns: what the run established.
        """
        return generate_checksums(
            self.resource_path(),
            coordinator=self.coordinator,
            algorithm=self.algorithm,
            only=self.only,
            excluded_patterns=self.excluded_patterns,
            progress=control.report,
            checkpoint=self.checkpoint,
        )


class VerifyChecksumsJob(ChecksumJob):
    """Check a resource's content against its ``.checksum`` record, on the queue (#204).

    ``create_if_missing`` is **off**, so a resource with no record fails with a sentence naming the
    record rather than quietly adopting every file: a surface offers Generate for that case (#204), and
    the sweep that means *adopt everything* is #242's, which turns it on deliberately.
    """

    kind = CHECKSUM_VERIFY_KIND
    verb = "Verify"

    def perform(self, control: JobControl) -> ChecksumReport:
        """See :meth:`ChecksumJob.perform` -- :func:`~rehuco_core.verify_checksums`.

        :param control: the engine's face to this job.
        :returns: what the run established.
        """
        return verify_checksums(
            self.resource_path(),
            coordinator=self.coordinator,
            algorithm=self.algorithm,
            only=self.only,
            excluded_patterns=self.excluded_patterns,
            progress=control.report,
            checkpoint=self.checkpoint,
        )

    def validate(self) -> str | None:
        """Refuse a verify with no record to verify against, before anything is read.

        The record's absence is the one thing this run cannot recover from, and saying so as a
        validation failure -- one sentence, retryable -- beats a ``FileNotFoundError`` naming a file
        the reader never asked about.

        :returns: ``None`` when the run can start, else what is wrong.
        """
        reason = super().validate()
        if reason is not None:
            return reason
        record = checksum_record_path(self.resource_path())
        if not record.exists():
            return f"This resource has no checksum record yet: {record}"
        return None


def checksum_report_summary(report: ChecksumReport) -> str:
    """One line saying what a run established, for a log record and a banner alike.

    Counts rather than names: a tutorial of two hundred videos reports two hundred statuses, and the
    question a verify raises is *how many of what*. Which files those were is the record's answer, and
    the dock that shows it is #244's.

    :param report: what the run established.
    :returns: the summary, e.g. ``"210 matched, 2 mismatched, 1 missing"``, or a plain statement when
        the run established nothing.
    """
    counts: dict[str, int] = {}
    for status in report.statuses.values():
        counts[status] = counts.get(status, 0) + 1
    parts = [f"{count} {status}" for status, count in sorted(counts.items())]
    if report.skipped:
        parts.append(f"{len(report.skipped)} skipped")
    if report.unreadable:
        parts.append(f"{len(report.unreadable)} unreadable")
    if report.unnamed_malformed:
        parts.append(f"{report.unnamed_malformed} unnamed malformed")
    if report.unreadable_directories:
        # the one part that is not a count of files: a branch that would not list has no files to
        # count, which is exactly why it has to be said out loud (#245)
        count = len(report.unreadable_directories)
        parts.append(f"{count} unreadable director{'y' if count == 1 else 'ies'}")
    return ", ".join(parts) if parts else "nothing to check"


# registered at import, by the module that owns the classes ([[appendices.task-queue#lifetime]]) --
# which is what keeps rehuco_core.tasks free of a central list naming every client
DEFAULT_TASK_JOB_REGISTRY.register(CHECKSUM_GENERATE_KIND, GenerateChecksumsJob)
DEFAULT_TASK_JOB_REGISTRY.register(CHECKSUM_VERIFY_KIND, VerifyChecksumsJob)
