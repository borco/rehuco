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

**The sweep is the third job here** (#242), and it is not one of the two: it is about a folder rather
than a resource, so it shares the coordinator idiom and nothing else. What it does share with a verify
it gets by *calling* one, once per resource the catalog walk found.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from .checksum_algorithms import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM
from .checksum_record import ChecksumRecordError, checksum_record_path
from .checksum_seeding import legacy_manifest_for
from .constants import EXCLUDED_FILE_PATTERNS
from .rehu_catalog import enumerate_catalog_resources
from .rehu_checksums import ChecksumReport, generate_checksums, verify_checksums
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .resource_scoping import resource_name
from .tasks import (
    DEFAULT_TASK_JOB_REGISTRY,
    PROGRESS_UNIT_BYTES,
    PROGRESS_UNIT_RESOURCES,
    JobControl,
    TaskJobBase,
)

LOG: Final = logging.getLogger(__name__)

CHECKSUM_GENERATE_KIND: Final = "checksum-generate"
CHECKSUM_VERIFY_KIND: Final = "checksum-verify"
CHECKSUM_SWEEP_KIND: Final = "checksum-sweep"
"""What a saved queue spells these jobs as ([[appendices.task-queue#lifetime]]).

Names rather than class paths, and a promise once written into a user's queue file: renaming one
strands every saved job that carries it."""

STATE_PATH_KEY: Final = "path"
STATE_ALGORITHM_KEY: Final = "algorithm"
STATE_ONLY_KEY: Final = "only"
STATE_EXCLUDED_PATTERNS_KEY: Final = "excluded_patterns"
STATE_CREATE_IF_MISSING_KEY: Final = "create_if_missing"
STATE_MIGRATE_TO_KEY: Final = "migrate_to"
STATE_STALE_DAYS_KEY: Final = "stale_days"
"""The keys one of these jobs writes itself down under.

Read back by the class that wrote them and by nothing else ([[appendices.task-queue#lifetime]]) -- the
registry, the queue and the file all treat the state as opaque.

The exclusion set is captured with the rest rather than re-resolved from the settings on restore: a
restored job is meant to be *the job that was queued*, and the list decides which unlisted files a run
adopts, which is part of what was asked for. The two verify choices (#242) are captured for the same
reason, and read back with today's behaviour as their default, so a queue saved by a build that had
neither key restores exactly the run it described."""


# a job's members *are* its run's parameters, and #203's callables take that many; collapsing them into
# a settings object would put a second shape between the enqueuer and the call
# pylint: disable-next=too-many-instance-attributes
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
    :param create_if_missing: whether a run may create the record it works over, or ``None`` for this
        job's own answer (#242's *Create missing checksum on verify*, resolved by the caller).
    :param stale_after: skip entries verified more recently than this, or ``None`` to check everything
        -- which is how #203 spells *force*, and what every run of this job was before #244 gave the
        document's main action a *Verify Old* that names the window it would use. Meaningless to a
        generate, which re-baselines exactly what it was asked for.
    :param migrate_to: what a verify re-keys matched entries to, or ``None`` to migrate nothing (#242's
        *Update checksums on verify*, resolved by the caller). Meaningless to a generate, which
        re-baselines under ``algorithm`` whatever an entry carried.
    :param label: how the job is named to a reader, or ``None`` for one derived from the path.
    """

    kind: str = ""
    """The stable saved name; set by each subclass, empty on this base, which is never registered."""

    progress_unit = PROGRESS_UNIT_BYTES
    """A run counts bytes, because #203's callables do (#248).

    **Not files.** A tutorial is three eight-gigabyte videos, and a count that moved three times in
    twenty minutes would say nothing -- which is the same reasoning
    :mod:`~rehuco_core.rehu_checksums` gives for counting them that way in the first place."""

    verb: str = ""
    """What this job does, for the label and the log -- ``"Generate"`` or ``"Verify"``."""

    creates_by_default: bool = False
    """Whether this job creates a missing record when nobody says otherwise.

    A generate's whole purpose, and deliberately not a verify's ([[data-model#checksums]]): adopting
    every content file is a decision, so a verify only does it when the setting says to (#242)."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        rehu_path: Path | None = None,
        *,
        coordinator: RenameCoordinator | None = None,
        algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
        only: Collection[str] | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        create_if_missing: bool | None = None,
        stale_after: timedelta | None = None,
        migrate_to: str | None = None,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__location = self.__coordinator.track(rehu_path) if rehu_path is not None else None
        self.algorithm = algorithm
        self.only: tuple[str, ...] | None = None if only is None else tuple(only)
        self.excluded_patterns = excluded_patterns
        self.create_if_missing = self.creates_by_default if create_if_missing is None else create_if_missing
        self.stale_after = stale_after
        self.migrate_to = migrate_to
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
        self.__log_seed(report)
        LOG.info("%s: %s", self.label, checksum_report_summary(report))

    @staticmethod
    def __log_seed(report: ChecksumReport) -> None:
        """Say line by line what a legacy manifest did not contribute (#243).

        The summary carries the counts; this is where a reader finds out *which* line and *why*, on the
        resource's own log ([[appendices.logging#scopes]]). It runs once in a resource's life, so the
        detail costs nothing on any later verify.

        :param report: what the run established.
        """
        seed = report.seed
        if seed is None:
            return
        for manifest in seed.ignored:
            LOG.info("%s was not read: %s is the manifest this record was seeded from.", manifest, seed.manifest.name)
        for drop in seed.dropped:
            LOG.warning("%s: dropped %r -- %s.", seed.manifest, drop.line, drop.reason)

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
            STATE_CREATE_IF_MISSING_KEY: self.create_if_missing,
            STATE_STALE_DAYS_KEY: None if self.stale_after is None else self.stale_after.days,
            STATE_MIGRATE_TO_KEY: self.migrate_to,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Read defensively, because the file is editable and a build that cannot make sense of an item
        should drop that item rather than come up broken: a missing path, an algorithm this build does
        not ship (as the run's own or as its migration target), or a selection that is not a list of
        names raises, and the registry logs and drops the item ([[appendices.task-queue#lifetime]]).

        The two verify choices (#242) default to this job's own behaviour when the state does not carry
        them, so an item written by a build that predates them restores as the run it was.

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
        migrate_to = state.get(STATE_MIGRATE_TO_KEY)
        if migrate_to is not None and migrate_to not in CHECKSUM_ALGORITHMS:
            raise ValueError(f"A saved checksum task migrates to an unknown algorithm: {migrate_to!r}")
        excluded = state.get(STATE_EXCLUDED_PATTERNS_KEY)
        create_if_missing = state.get(STATE_CREATE_IF_MISSING_KEY, self.creates_by_default)
        stale_days = state.get(STATE_STALE_DAYS_KEY)
        if stale_days is not None and not isinstance(stale_days, int):
            raise ValueError("A saved checksum task's staleness window is not a number of days.")
        self.__location = self.__coordinator.track(Path(path))
        self.algorithm = algorithm
        self.only = None if only is None else tuple(only)
        self.migrate_to = migrate_to
        self.create_if_missing = bool(create_if_missing)
        self.stale_after = None if stale_days is None else timedelta(days=stale_days)
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
    creates_by_default = True

    def perform(self, control: JobControl) -> ChecksumReport:
        """See :meth:`ChecksumJob.perform` -- :func:`~rehuco_core.generate_checksums`.

        ``create_if_missing`` is on by default: creating the record is what a first generate is *for*.
        ``migrate_to`` has no meaning here and is not passed -- a generate re-baselines under
        :attr:`~ChecksumJob.algorithm` whatever an entry carried before, which is migration's whole
        effect and more.

        :param control: the engine's face to this job.
        :returns: what the run established.
        """
        # ``stale_after`` is deliberately not passed: a generate is asked for on purpose, over a
        # selection, and skipping part of it because those entries were verified recently would make a
        # deliberate re-baseline quietly partial (#244)
        return generate_checksums(
            self.resource_path(),
            coordinator=self.coordinator,
            algorithm=self.algorithm,
            only=self.only,
            create_if_missing=self.create_if_missing,
            excluded_patterns=self.excluded_patterns,
            progress=control.report,
            checkpoint=self.checkpoint,
        )


class VerifyChecksumsJob(ChecksumJob):
    """Check a resource's content against its ``.checksum`` record, on the queue (#204).

    ``create_if_missing`` is **off** unless the caller says otherwise, so a resource with no record
    fails with a sentence naming the record rather than quietly adopting every file: a surface offers
    Generate for that case (#204). Adopting everything is what *Create missing checksum on verify*
    (#242) turns on, deliberately, and it is the mode the sweep runs in when it is set.
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
            stale_after=self.stale_after,
            create_if_missing=self.create_if_missing,
            migrate_to=self.migrate_to,
            excluded_patterns=self.excluded_patterns,
            progress=control.report,
            checkpoint=self.checkpoint,
        )

    def validate(self) -> str | None:
        """Refuse a verify with no record to verify against, before anything is read.

        The record's absence is the one thing this run cannot recover from, and saying so as a
        validation failure -- one sentence, retryable -- beats a ``FileNotFoundError`` naming a file
        the reader never asked about. Unless this run may create the record (#242), in which case a
        missing one is the ordinary starting state rather than a refusal.

        **A legacy manifest counts as a record to verify against** (#243), because the run will seed
        one from it: refusing here would send the reader at a Generate, which is precisely the throwing
        away of the old claim that seeding exists to prevent. One directory listing rather than a
        ``stat``, and only on the path where there is no ``.checksum``.

        :returns: ``None`` when the run can start, else what is wrong.
        """
        reason = super().validate()
        if reason is not None:
            return reason
        if self.create_if_missing:
            return None
        path = self.resource_path()
        record = checksum_record_path(path)
        if not record.exists() and legacy_manifest_for(path) is None:
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
    if report.seed is not None:
        # named rather than counted, because a seed happens once in a resource's life and which file
        # it came from is the thing a reader wants back later (#243)
        parts.append(f"seeded {len(report.seed.entries)} from {report.seed.manifest.name}")
        if report.seed.dropped:
            count = len(report.seed.dropped)
            parts.append(f"{count} seed line{'' if count == 1 else 's'} dropped")
        if report.seed.ignored:
            count = len(report.seed.ignored)
            parts.append(f"{count} manifest{'' if count == 1 else 's'} ignored")
    if report.unreadable_directories:
        # the one part that is not a count of files: a branch that would not list has no files to
        # count, which is exactly why it has to be said out loud (#245)
        count = len(report.unreadable_directories)
        parts.append(f"{count} unreadable director{'y' if count == 1 else 'ies'}")
    return ", ".join(parts) if parts else "nothing to check"


@dataclass
class SweepTally:
    """What a sweep established over a whole catalog (#242).

    Not a :class:`~rehuco_core.ChecksumReport`: a report's keys are names *relative to one record*, so
    two resources both holding ``video.mp4`` would collide in a merged one, and a catalog's answer is a
    count rather than a list anyway -- which file was which is each record's own answer, and the dock
    that reads one is #244's.
    """

    resources: int = 0
    """How many records the walk found."""

    verified: int = 0
    """How many of them were actually checked."""

    without_record: int = 0
    """How many had no ``.checksum`` yet and this run was not allowed to create one -- an expected
    outcome rather than a fault, and the count that makes *Create missing checksum on verify*
    discoverable."""

    failed: int = 0
    """How many could not be checked at all: an unreachable branch, a refused read, a record this build
    cannot make sense of. One bad resource costs itself, never the sweep."""

    statuses: dict[str, int] = field(default_factory=dict)
    """Every verdict the sweep collected, summed across resources."""

    unreadable_branches: int = 0
    """How many directories under the root would not list, from the catalog walk itself -- distinct
    from a resource that failed, since these are branches whose resources were never even named."""


def sweep_summary(tally: SweepTally) -> str:
    """One line saying what a sweep established, in :func:`checksum_report_summary`'s voice.

    :param tally: what the sweep established.
    :returns: the summary, e.g. ``"412 resources, 9850 matched, 2 mismatched, 12 without a record"``.
    """
    parts = [f"{tally.resources} resource{'' if tally.resources == 1 else 's'}"]
    parts.extend(f"{count} {status}" for status, count in sorted(tally.statuses.items()))
    if tally.without_record:
        parts.append(f"{tally.without_record} without a record")
    if tally.failed:
        parts.append(f"{tally.failed} failed")
    if tally.unreadable_branches:
        count = tally.unreadable_branches
        parts.append(f"{count} unreadable director{'y' if count == 1 else 'ies'}")
    return ", ".join(parts)


# the same reason as :class:`ChecksumJob`'s: these are the verify's parameters, one per member
# pylint: disable-next=too-many-instance-attributes
class SweepChecksumsJob(TaskJobBase):
    """Verify every resource under a folder, skipping what was checked recently (#242).

    **The records it writes are its cursor.** Nothing is kept in this object between runs: a paused or
    interrupted sweep re-enters :meth:`run`, walks the folder again, and every resource the previous
    pass finished is skipped file by file because their recorded dates are now inside the window. That
    is the resumability [[appendices.task-queue#cursor]] asks for, obtained from the job's own output
    rather than from a continuation -- and it is *better* than a saved list of paths, which would send a
    resumed sweep at resources that have since moved.

    **Re-walking costs a listing per directory**, metadata only, against the hours of hashing it saves.
    The granularity is the resource, not the file: a verify writes its record once, at the end, so a
    sweep stopped inside an eight-terabyte folder reads that one folder again.

    **One bad resource costs itself.** A branch that will not list, a refused read or a record this
    build cannot parse is counted and logged, and the sweep carries on -- a catalog-wide run that died
    on its first offline mount would be useless. The one refusal is the root itself: a folder that will
    not list means the run has nothing to say at all.

    :param root: the folder to sweep, or ``None`` for a job about to be handed a saved state.
    :param coordinator: the rename barrier to read through (#241); the process-wide one unless a test
        says otherwise.
    :param algorithm: what new hashes are recorded under.
    :param stale_after: how long a recorded verification stays fresh, or ``None`` to re-read
        everything -- which is how #203 spells *force*.
    :param create_if_missing: whether a resource with no record is baselined rather than reported.
    :param migrate_to: what matched entries recorded under another algorithm are re-keyed to, or
        ``None`` to migrate nothing.
    :param excluded_patterns: the filename globs each resource's content walk leaves out (#226),
        resolved by the caller -- core never reads a setting.
    :param label: how the job is named to a reader, or ``None`` for one derived from the folder.
    """

    kind = CHECKSUM_SWEEP_KIND

    progress_unit = PROGRESS_UNIT_RESOURCES
    """A sweep counts resources, where the verifies it calls count bytes (#248).

    The difference is the whole reason a job declares this rather than a surface guessing: a catalog's
    byte total is not knowable without ``stat``-ing everything under it first, so this run reports the
    one figure it has exactly and for free (:meth:`run`)."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        root: Path | None = None,
        *,
        coordinator: RenameCoordinator | None = None,
        algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
        stale_after: timedelta | None = None,
        create_if_missing: bool = False,
        migrate_to: str | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__location = self.__coordinator.track(root) if root is not None else None
        self.algorithm = algorithm
        self.stale_after = stale_after
        self.create_if_missing = create_if_missing
        self.migrate_to = migrate_to
        self.excluded_patterns = excluded_patterns
        self.label = label if label is not None else self.__derived_label()
        self.__tally: SweepTally | None = None

    # region What the queue reads

    # a property over TaskJobBase's plain attribute, for the reason ChecksumJob gives: the folder can
    # be renamed under a running sweep, and the row must keep naming it
    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The folder this sweep is over, **as it is now** (#241)."""
        return self.__location.path if self.__location is not None else None

    @property
    def resumes_where_it_stopped(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Whether pausing this sweep keeps the work it has done.

        A property rather than a class attribute, because the honest answer depends on the window: with
        one, a resumed sweep skips every resource the last pass finished and keeps all of it; with the
        window at zero nothing is ever fresh, so it genuinely starts over. This bit exists so a surface
        can say what pausing costs ([[appendices.task-queue#job-responsibility]]), and one that lied at
        exactly the setting where pausing is expensive would be worse than none.
        """
        return self.stale_after is not None and self.stale_after > timedelta(0)

    @property
    def tally(self) -> SweepTally | None:
        """What the last completed sweep established, or ``None`` before one has finished."""
        return self.__tally

    def validate(self) -> str | None:
        """Say whether this sweep can still start -- a stat, not a walk.

        :returns: ``None`` when the folder is there, else what is wrong with it.
        """
        root = self.source
        if root is None:
            return "This task has no folder to sweep."
        if not root.is_dir():
            return f"The folder to sweep is not there: {root}"
        return None

    def reset(self) -> None:
        """Drop the last sweep's tally along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__tally = None

    # endregion

    # region Running

    def run(self, control: JobControl) -> None:
        """Walk the folder and verify what it holds, reporting resources as they are finished.

        **Progress counts resources, not bytes.** A catalog's byte total is not knowable without
        ``stat``-ing every file under it first, and the walk that would answer it is the expensive part
        of a sweep over an SMB mount; the resource count is exact and free, and the walk runs before the
        first read so the denominator is there from the start. The numbers themselves stay unit-free
        ([[appendices.task-queue#observation]]); :attr:`progress_unit` is what says which of the two a
        row is looking at (#248). Each resource's own byte progress is not forwarded, since a bar that
        reset per resource would say less than one that advanced once per resource.

        :param control: the engine's face to this job.
        :raises ContentUnreachableError: the folder itself would not list (#245).
        """
        enumeration = enumerate_catalog_resources(self.root_path(), checkpoint=self.checkpoint)
        enumeration.require_reachable()
        tally = SweepTally(resources=len(enumeration.resources), unreadable_branches=len(enumeration.unreadable))
        self.__tally = tally
        control.report(0, tally.resources)
        for done, rehu_path in enumerate(enumeration.resources, start=1):
            self.checkpoint()
            self.__verify_one(rehu_path, tally)
            control.report(done, tally.resources)
        LOG.info("%s: %s", self.label, sweep_summary(tally))

    def __verify_one(self, rehu_path: Path, tally: SweepTally) -> None:
        """Verify one resource, counting whatever came of it.

        The two ``except`` clauses are a real distinction rather than defensiveness, and they only work
        because #245 made :class:`~rehuco_core.ContentUnreachableError` deliberately **not** a
        :class:`FileNotFoundError`: the first is *this resource has no record*, which is expected and
        countable, and the second is *this resource could not be read*, which is a fault. A
        :class:`~rehuco_core.tasks.JobPaused` or :class:`~rehuco_core.tasks.JobCancelled` is a plain
        :class:`Exception` and passes through both untouched, which is what keeps the sweep stoppable.

        :param rehu_path: the resource to verify.
        :param tally: the sweep's running answer, added to in place.
        """
        try:
            report = verify_checksums(
                rehu_path,
                coordinator=self.coordinator,
                algorithm=self.algorithm,
                stale_after=self.stale_after,
                create_if_missing=self.create_if_missing,
                migrate_to=self.migrate_to,
                excluded_patterns=self.excluded_patterns,
                checkpoint=self.checkpoint,
            )
        except FileNotFoundError:
            tally.without_record += 1
            LOG.info("%s has no checksum record yet; it was not verified.", rehu_path)
            return
        except (OSError, ChecksumRecordError) as error:
            tally.failed += 1
            LOG.warning("%s could not be verified: %s", rehu_path, error)
            return
        tally.verified += 1
        for status in report.statuses.values():
            tally.statuses[status] = tally.statuses.get(status, 0) + 1

    def root_path(self) -> Path:
        """The folder this sweep works over, refusing a job that has none.

        :returns: the folder, as of now.
        :raises ValueError: the job was built without a folder and never given a state.
        """
        root = self.source
        if root is None:
            raise ValueError("A checksum sweep has no folder to work on.")
        return root

    @property
    def coordinator(self) -> RenameCoordinator:
        """The rename barrier this sweep's reads go through (#241)."""
        return self.__coordinator

    # endregion

    # region Being written down

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this sweep needs to be itself again in a later run.

        JSON primitives only ([[appendices.task-queue#lifetime]]), which is why the window is written
        as whole days rather than as a :class:`~datetime.timedelta`.

        :returns: the state.
        """
        root = self.source
        return {
            STATE_PATH_KEY: str(root) if root is not None else "",
            STATE_ALGORITHM_KEY: self.algorithm,
            STATE_STALE_DAYS_KEY: None if self.stale_after is None else self.stale_after.days,
            STATE_CREATE_IF_MISSING_KEY: self.create_if_missing,
            STATE_MIGRATE_TO_KEY: self.migrate_to,
            STATE_EXCLUDED_PATTERNS_KEY: list(self.excluded_patterns),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the sweep that captured ``state``.

        Read defensively, the way :meth:`ChecksumJob.restore_state` is: a missing folder, an algorithm
        or a migration target this build does not ship, or a window that is not a number raises, and the
        registry logs and drops the item ([[appendices.task-queue#lifetime]]).

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a runnable sweep.
        """
        path = state.get(STATE_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved checksum sweep names no folder.")
        algorithm = state.get(STATE_ALGORITHM_KEY, DEFAULT_CHECKSUM_ALGORITHM)
        if algorithm not in CHECKSUM_ALGORITHMS:
            raise ValueError(f"A saved checksum sweep names an unknown algorithm: {algorithm!r}")
        migrate_to = state.get(STATE_MIGRATE_TO_KEY)
        if migrate_to is not None and migrate_to not in CHECKSUM_ALGORITHMS:
            raise ValueError(f"A saved checksum sweep migrates to an unknown algorithm: {migrate_to!r}")
        stale_days = state.get(STATE_STALE_DAYS_KEY)
        if stale_days is not None and not isinstance(stale_days, int):
            raise ValueError("A saved checksum sweep's staleness window is not a number of days.")
        excluded = state.get(STATE_EXCLUDED_PATTERNS_KEY)
        self.__location = self.__coordinator.track(Path(path))
        self.algorithm = algorithm
        self.migrate_to = migrate_to
        self.stale_after = None if stale_days is None else timedelta(days=stale_days)
        self.create_if_missing = bool(state.get(STATE_CREATE_IF_MISSING_KEY, False))
        if isinstance(excluded, list) and all(isinstance(pattern, str) for pattern in excluded):
            self.excluded_patterns = tuple(excluded)
        self.label = self.__derived_label()

    # endregion

    def __derived_label(self) -> str:
        """This sweep's own name for itself, e.g. ``"Sweep checksums - library"``.

        A fallback rather than the usual answer: a restored item's saved label is used in preference
        ([[appendices.task-queue#lifetime]]).
        """
        root = self.source
        if root is None:
            return "Sweep checksums"
        return f"Sweep checksums - {root.name or root}"


# registered at import, by the module that owns the classes ([[appendices.task-queue#lifetime]]) --
# which is what keeps rehuco_core.tasks free of a central list naming every client
DEFAULT_TASK_JOB_REGISTRY.register(CHECKSUM_GENERATE_KIND, GenerateChecksumsJob)
DEFAULT_TASK_JOB_REGISTRY.register(CHECKSUM_VERIFY_KIND, VerifyChecksumsJob)
DEFAULT_TASK_JOB_REGISTRY.register(CHECKSUM_SWEEP_KIND, SweepChecksumsJob)
