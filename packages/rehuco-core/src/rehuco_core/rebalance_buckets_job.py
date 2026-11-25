"""Bringing a root's prefix buckets in line with the limits, as a task-queue job
([[mounts-and-storage#bucket-rebalance]], #681).

A record that arrives in a bucketed folder splits it when it takes it over the limit; nothing looks at the folders no
record arrives in, so a lowered split limit leaves them crowded, and nothing but this ever joins buckets back. The job
finds the root's bucketed folders by the records the cache holds (:func:`~rehuco_core.bucketed_folders`) and walks each
from the top: a folder whose whole subtree is within the join limit is joined (:class:`~rehuco_core.BucketJoiner`), and
any other is split where it must be (:class:`~rehuco_core.BucketSplitter`), then its buckets in turn.

**Before them come the split folders no layout buckets any more**, its ``{buckets}`` rule removed: the disk says which
folders are split (:func:`~rehuco_core.split_folders`), the cache and the layouts which of them are still governed
(:class:`~rehuco_core.BucketRules`). One that is not is joined whole, whatever it holds, since nothing may be put there
until it is. One nothing is known of is joined at or below the join limit only, so a library never scanned is not
flattened and an emptied folder still loses its marker.

**The tree is the cursor.** Every step is one rename through the rename barrier, so a stop leaves every record whole and
in one place, and a run begun again goes on from the disk alone.

**The limits are the ones it was started with**, whatever the settings say meanwhile, after a restart too.

**It never moves files beside a library scan**, with which it shares a chain
(:data:`~rehuco_core.tasks.LIBRARY_CHAIN`). A record's move runs on another, so before every step the job asks whether
one has read its buckets under this root and not ended, or is about to remove what is left of an original here
(:meth:`~rehuco_core.RecordMoveHost.blocking_move`), and waits for it: it would move a half-copied record, the folder a
waiting rename is to land in, or the leftovers away from their removal. The asking and the step are one
(:data:`~rehuco_core.record_move_host.BUCKETS_GUARD`).
"""

import logging
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Final, override
from uuid import UUID

from borco_core import Presence, device_of, presence_of

from .bucket_joiner import BucketJoiner, BucketJunk, JoinResult
from .bucketed_folders import Bucketing, BucketRules, bucketed_folders
from .constants import EXCLUDED_FILE_PATTERNS
from .prefix_buckets import (
    DEFAULT_JOIN_LIMIT,
    DEFAULT_SPLIT_LIMIT,
    BucketListing,
    BucketMover,
    BucketSplitter,
    clamped_limits,
    is_never_split,
    is_split,
    split_folders,
)
from .record_bucket_mover import RecordBucketMover
from .record_file_lock import RecordLockedError
from .record_move_host import BUCKETS_GUARD, DEFAULT_RECORD_MOVE_HOST, RecordMoveHost
from .rehudb import CatalogRecord
from .rehudb_jobs import STATE_ROOT_PATH_KEY, CatalogRootJob
from .rehuroot_file import RehurootFile, RehurootFileError
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator, RenameYieldTimeout
from .save_record_job import OFFLINE_RETRY_SECONDS
from .tasks import (
    DEFAULT_TASK_JOB_REGISTRY,
    LIBRARY_CHAIN,
    PROGRESS_UNIT_RESOURCES,
    JobControl,
    JobOutcome,
    JobPaused,
    JobWaiting,
)
from .tc_backups_jobs import DEFAULT_DELETER_PROVIDER

LOG: Final = logging.getLogger(__name__)

BUCKET_REBALANCE_KIND: Final = "bucket-rebalance"
"""What a saved queue spells this job as ([[appendices.task-queue#lifetime]]): a promise once written."""

REBALANCE_LOCK_RETRY: Final = 5.0
"""How long a rebalance waits before looking again at a record another process holds the lock of, in seconds."""

REBALANCE_READERS_RETRY: Final = 2.0
"""How long a rebalance waits before asking again the readers that did not let go of a record in time, in seconds."""

REBALANCE_MOVE_RETRY: Final = 5.0
"""How long a rebalance waits before looking again at a move of its root's records, in seconds."""

NOTHING_TO_REBALANCE: Final = "Nothing to rebalance"
"""The outcome of a run that moved nothing."""

STILL_SPLIT_REASONS: Final = {
    Bucketing.UNGOVERNED: "no layout buckets it any more, but a bucket in it is marked never to be split",
    Bucketing.UNKNOWN: "it is not known whether a layout still buckets it: check the root's layouts, and scan it",
}
"""Why a folder not joined is still split, by what is known of it, when the joiner had nothing to say."""

STATE_REBALANCE_PATTERNS_KEY: Final = "excluded_patterns"
STATE_REBALANCE_SPLIT_KEY: Final = "split_limit"
STATE_REBALANCE_JOIN_KEY: Final = "join_limit"
"""The keys this job writes its junk globs and its limits under."""


class GuardedMover:
    """A :class:`~rehuco_core.BucketMover` that makes each move one step with the question whether it may, and counts
    it, for the row's progress.

    :param mover: what moves.
    :param step: entered around each move; what entering it raises stops the rebalance there.
    :param moved: told after each move.
    """

    def __init__(
        self, mover: BucketMover, step: Callable[[], AbstractContextManager[object]], moved: Callable[[], None]
    ) -> None:
        self.__mover: Final = mover
        self.__step: Final = step
        self.__moved: Final = moved

    def move_record(self, record: Path, into: Path) -> None:
        """See :meth:`~rehuco_core.BucketMover.move_record`.

        :param record: its ``.rehu``.
        :param into: the folder it lands in.
        """
        with self.__step():
            self.__mover.move_record(record, into)
        self.__moved()

    def move_folder(self, folder: Path, into: Path, name: str) -> None:
        """See :meth:`~rehuco_core.BucketMover.move_folder`.

        :param folder: the folder.
        :param into: the folder it lands in.
        :param name: its name there.
        """
        with self.__step():
            self.__mover.move_folder(folder, into, name)
        self.__moved()


class RebalanceBucketsJob(CatalogRootJob):  # pylint: disable=too-many-instance-attributes
    """Splits and joins one root's bucketed folders by the limits it is given (#681).

    A `~rehuco_core.PersistableTaskJob` and a `~rehuco_core.ReportingTaskJob` by shape.

    :param cache_path: the catalog's ``.rehudb``, or ``None`` for a job about to be handed a saved state.
    :param root_id: the root's id in the ``.rehuco``.
    :param root: the root's folder, which the row and its log are about; where the files are is asked of ``host`` as
        the job runs.
    :param root_label: the root's label, for the job's own name.
    :param split_limit: how many entries a folder holds before it is split, clamped as the limits are used
        (:func:`~rehuco_core.clamped_limits`).
    :param join_limit: how few entries a split folder's whole subtree holds to be joined, clamped likewise.
    :param excluded_patterns: the globs naming the junk files a join deletes.
    :param coordinator: the rename barrier.
    :param host: what the app lends this job.
    :param label: how the job is named to a reader, or ``None`` for a derived one.
    """

    kind = BUCKET_REBALANCE_KIND
    verb = "Balance buckets"
    chain = LIBRARY_CHAIN
    progress_unit = PROGRESS_UNIT_RESOURCES
    resumes_where_it_stopped = True

    def __init__(  # pylint: disable=too-many-arguments
        self,
        cache_path: Path | None = None,
        root_id: UUID | None = None,
        root: Path | None = None,
        *,
        root_label: str = "",
        split_limit: int = DEFAULT_SPLIT_LIMIT,
        join_limit: int = DEFAULT_JOIN_LIMIT,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        coordinator: RenameCoordinator | None = None,
        host: RecordMoveHost | None = None,
        label: str | None = None,
    ) -> None:
        # before the label, which names them
        self.limits = clamped_limits(split_limit, join_limit)
        super().__init__(cache_path, root_id, root_label=root_label, label=label)
        self.source = root
        self.excluded_patterns = excluded_patterns
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__host: Final[RecordMoveHost] = host if host is not None else DEFAULT_RECORD_MOVE_HOST
        self.__moved = 0
        self.__joined = 0
        self.__left: tuple[str, ...] = ()
        self.__outcome: JobOutcome | None = None

    @property
    def outcome(self) -> JobOutcome | None:
        """What the runs moved and joined, and the folders left split; ``None`` before a run finished."""
        return self.__outcome

    @override
    def validate(self) -> str | None:
        """See :meth:`CatalogRootJob.validate` -- also requires a folder."""
        return super().validate() or (None if self.source is not None else "This task names no root's folder.")

    @override
    def capture_state(self) -> dict[str, Any]:
        """See :meth:`CatalogRootJob.capture_state` -- adds the root's folder, the junk globs and the limits."""
        state = super().capture_state()
        state[STATE_ROOT_PATH_KEY] = str(self.source) if self.source is not None else ""
        state[STATE_REBALANCE_PATTERNS_KEY] = list(self.excluded_patterns)
        state[STATE_REBALANCE_SPLIT_KEY], state[STATE_REBALANCE_JOIN_KEY] = self.limits
        return state

    @override
    def restore_state(self, state: dict[str, Any]) -> None:
        """See :meth:`CatalogRootJob.restore_state` -- adds the root's folder, the junk globs and the limits.

        :param state: whatever :meth:`capture_state` wrote.
        :raises ValueError: the state names no folder, no globs or no limits, or fails the shared checks.
        """
        path = state.get(STATE_ROOT_PATH_KEY)
        patterns = state.get(STATE_REBALANCE_PATTERNS_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved rebalance names no folder.")
        if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
            raise ValueError("A saved rebalance's junk patterns are not a list of names.")
        self.limits = clamped_limits(
            self.__saved_limit(state, STATE_REBALANCE_SPLIT_KEY), self.__saved_limit(state, STATE_REBALANCE_JOIN_KEY)
        )
        super().restore_state(state)
        self.source = Path(path)
        self.excluded_patterns = tuple(patterns)

    @staticmethod
    def __saved_limit(state: dict[str, Any], key: str) -> int:
        """One limit of a saved state.

        :param state: the state.
        :param key: the limit's key.
        :returns: the limit.
        :raises ValueError: it is no number.
        """
        limit = state.get(key)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("A saved rebalance's limits are not numbers.")
        return limit

    @override
    def derived_label(self) -> str:
        """See :meth:`CatalogRootJob.derived_label` -- names the limits, so that two jobs of one root with other limits
        read as two (``"Balance buckets (200/100) - Library"``).

        :returns: the label.
        """
        split, join = self.limits
        verb = f"{self.verb} ({split}/{join})"
        return f"{verb} - {self.root_label}" if self.root_label else verb

    @override
    def reset(self) -> None:
        """Forget what the last runs counted along with the stop request."""
        super().reset()
        self.__moved = 0
        self.__joined = 0
        self.__left = ()
        self.__outcome = None

    @override
    def run(self, control: JobControl) -> None:
        """Join the split folders no layout buckets any more, then walk the root's bucketed folders.

        :param control: the engine's face to this job.
        :raises JobPaused: asked to, or stopped by what only the user can fix -- the reason as its message.
        :raises JobWaiting: the root does not answer, a move into it is under way, a record is locked by a write
            elsewhere, or a reader did not let go in time.
        :raises OSError: with the root answering, a folder could not be read, moved or removed.
        """

        def moved() -> None:
            """Count one move."""
            self.__moved += 1
            control.report(self.__moved)

        control.report(self.__moved)
        root = self.__root_folder()
        mover = GuardedMover(RecordBucketMover(self.__coordinator, self.__host, self.checkpoint), self.__step, moved)
        try:
            self.__left = ()
            self.__join_ungoverned(root, mover)
            records, laid_out, _scanned = self.__records_and_layouts()
            for folder in bucketed_folders(records, laid_out, self.__host.location_rules()):
                self.__rebalance(root.joinpath(*folder.parts), root, mover)
        except RecordLockedError as error:
            raise JobWaiting(str(error), REBALANCE_LOCK_RETRY) from error
        except RenameYieldTimeout as error:
            raise JobWaiting(str(error), REBALANCE_READERS_RETRY) from error
        except OSError as error:
            self.__require_answer(root, error)
            raise
        self.__outcome = self.__found()
        LOG.info("%s: %s", self.label, self.__outcome.summary)

    def __join_ungoverned(self, root: Path, mover: BucketMover) -> None:
        """Join the split folders no layout buckets any more, the deepest first, and those nothing is known of that
        hold no more than the join limit.

        :param root: the root's folder.
        :param mover: what moves.
        """
        found = {
            folder: PurePosixPath(*folder.parts[len(root.parts) :]) for folder in split_folders(root, self.checkpoint)
        }
        records, laid_out, scanned = self.__records_and_layouts()
        rules = BucketRules(
            records, laid_out, self.__host.location_rules(), split=tuple(found.values()), scanned=scanned
        )
        joiners = {
            Bucketing.UNGOVERNED: self.__joiner(None, mover),
            Bucketing.UNKNOWN: self.__joiner(self.limits[1], mover),
        }
        for folder, relative in found.items():
            bucketing = rules.of(relative)
            if bucketing is Bucketing.GOVERNED:
                continue
            joiner = joiners[bucketing]
            told = len(joiner.left)
            result = joiner.join(folder, 0)
            self.__joined += result is JoinResult.JOINED
            # nothing may be put there while it is split, so what keeps it so is always said
            if result is JoinResult.NONE and len(joiner.left) == told and is_split(folder):
                self.__left += (f"{folder}: {STILL_SPLIT_REASONS[bucketing]}",)
        for joiner in joiners.values():
            self.__left += joiner.left

    def __joiner(self, limit: int | None, mover: BucketMover) -> BucketJoiner:
        """A joiner for this job's root.

        :param limit: how few entries a folder it joins holds; ``None`` for whatever it holds.
        :param mover: what moves.
        :returns: the joiner.
        """
        return BucketJoiner(
            limit,
            mover,
            junk=BucketJunk(self.excluded_patterns, DEFAULT_DELETER_PROVIDER.resolve()),
            checkpoint=self.checkpoint,
            exclusively=self.__step,
        )

    def __rebalance(self, layout_folder: Path, root: Path, mover: BucketMover) -> None:
        """Rebalance one bucketed folder and everything beneath it.

        :param layout_folder: the folder of the level before ``{buckets}``.
        :param root: the root's folder.
        :param mover: what moves.
        """
        if not layout_folder.is_dir():
            self.__require_answer(root)
            LOG.info("%s: %s is no longer there.", self.label, layout_folder)
            return
        split_limit, join_limit = self.limits
        splitter = BucketSplitter(split_limit, mover, self.checkpoint)
        joiner = self.__joiner(join_limit, mover)

        def walk(folder: Path, depth: int) -> None:
            """Join a folder, or split it and go on to its buckets."""
            self.checkpoint()
            with self.__step():
                pinned = is_never_split(folder)
            if pinned:
                return
            result = joiner.join(folder, depth)
            if result is not JoinResult.NONE:
                self.__joined += result is JoinResult.JOINED
                return
            splitter.settle_folder(folder, depth)
            for bucket in BucketListing.of(folder, depth).buckets.values():
                walk(bucket, depth + 1)

        walk(layout_folder, 0)
        self.__left += (*joiner.left, *splitter.left)

    def __records_and_layouts(self) -> tuple[list[CatalogRecord], RehurootFile, bool]:
        """The root's records as the cache has them now, and its layouts.

        :returns: the records, the root's file, and whether a scan has read the root.
        :raises JobPaused: the catalog no longer lists the root, or the root's file cannot be read.
        """
        root_id = self.required_root_id()
        with self.cache() as cache:
            row = next((row for row in cache.roots() if row.root_id == root_id), None)
            records = [row.record for row in cache.root_rows(root_id)]
        if row is None or row.root_file is None:
            raise JobPaused(f"The root {self.root_label} is no longer in the catalog: add it again, then resume.")
        try:
            laid_out = RehurootFile.load(row.root_file)
        except RehurootFileError as error:
            raise JobPaused(f"The root's file cannot be read: {error}") from error
        except OSError as error:
            self.__require_answer(row.root_file.parent, error)
            raise JobPaused(f"The root's file cannot be read: {error}") from error
        return records, laid_out, row.scanned_at is not None

    @contextmanager
    def __step(self) -> Generator[None]:
        """One step, with the question whether a move of this root's records lets it be taken.

        :yields: nothing; the block takes the step.
        :raises JobWaiting: a move is under way.
        """
        with BUCKETS_GUARD:
            move = self.__host.blocking_move(self.required_root_id())
            if move is not None:
                raise JobWaiting(f"Waiting for a move in this root to end: {move}", REBALANCE_MOVE_RETRY)
            yield

    def __root_folder(self) -> Path:
        """Where this machine finds the root, answering.

        :returns: the folder.
        :raises JobPaused: this machine maps no folder to the root.
        :raises JobWaiting: the root does not answer.
        """
        root = self.__host.root_folder(self.required_root_id())
        if root is None:
            raise JobPaused("This machine maps no folder to the root: map it in the Roots view, then resume.")
        self.__require_answer(root)
        return root

    @staticmethod
    def __require_answer(folder: Path, error: OSError | None = None) -> None:
        """Wait when a folder's share or drive does not answer.

        :param folder: the folder.
        :param error: what failed on it, ``None`` when nothing did.
        :raises JobWaiting: it does not answer.
        """
        if presence_of(folder) is Presence.OFFLINE:
            device = device_of(folder)
            reason = f"Waiting for the root: {device.host or device.root} does not answer."
            raise JobWaiting(reason, OFFLINE_RETRY_SECONDS) from error

    def __found(self) -> JobOutcome:
        """What the runs did, in one line.

        :returns: the outcome, not clean when a folder was left split, or an entry where it is.
        """
        if not (self.__moved or self.__joined or self.__left):
            return JobOutcome(NOTHING_TO_REBALANCE)
        moves = "move" if self.__moved == 1 else "moves"
        folders = "folder" if self.__joined == 1 else "folders"
        summary = f"{self.__moved} {moves}, {self.__joined} {folders} joined"
        if not self.__left:
            return JobOutcome(summary)
        return JobOutcome(f"{summary}; left: {'; '.join(self.__left)}", clean=False)


DEFAULT_TASK_JOB_REGISTRY.register(BUCKET_REBALANCE_KIND, RebalanceBucketsJob)
