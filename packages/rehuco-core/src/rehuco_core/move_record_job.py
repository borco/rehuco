"""Moving a record to another place, as a task-queue job: a verified copy across volumes, a verified rename on one
([[mounts-and-storage#safe-move-rename]], #339).

**Which of the two is decided up front** by the caller (:func:`~rehuco_core.same_volume`): one local volume or one
share is a rename, anything else a copy. A rename the operating system refuses as crossing devices
(:func:`~rehuco_core.is_cross_device`) becomes the copy, so two roots on one share or one disk move at once and nothing
is lost by guessing wrong.

**A copy runs in five phases, each kept**, so a quit or a pause comes back to the phase it left:

1. *source* -- the record must cover every content file (:func:`~rehuco_core.check_move_source`), and is verified when
   the settings ask for it or when it has entries to add;
2. *move* -- the files are copied, resumable per file (:class:`~rehuco_core.VerifiedCopy`);
3. *target* -- the copy is checked against the record, always: the hard rule;
4. *finish* -- on the job's own thread, every file no checksum covers is compared with its copy and copied again where
   it changed; then, inside the rename barrier and on the host's thread, the original is checked to be as it was
   compared -- one listing -- and stops being a record: its ``.rehu`` and ``.checksum`` go, a video playing from it
   lets go first, and everyone holding its paths follows it to the copy;
5. *cleanup* -- back on the job's thread, the rest of the original is removed.

A rename runs *source* (when its setting asks), the rename itself, then *target* (the same setting).

**A cancel takes the copy back** while the original is whole -- phases 2 to 4 -- whether the job is running or not:
the queue never runs a paused job it cancels or removes, so it tells the job (:meth:`MoveRecordJob.abandon`), which
removes its copy from a thread of its own. **So does a move that is refused**: a copy that did not match its record,
an original that changed under it, a link found in the record -- nothing unverified is left at the destination. A
copy stopped by anything else (a share that went away, a pause, a quit) is kept, to resume from.

**Once the original stopped being a record the cleanup always runs**: the copy verified, so a cancel no longer takes
anything back -- one given up on in its cleanup phase finishes removing the original instead.

**Job state names each end by its root** -- the root's id and the path under it -- so a queued move survives a restart
and a remapped drive. A record under no root is named by its absolute path, since it has no root to be named by.

**The host** (:class:`RecordMoveHost`) is what the app lends a job: where this machine finds a root, whether a save of
the record is still on its way, and the thread a rename runs on. The app installs one at startup
(:data:`DEFAULT_RECORD_MOVE_HOST`); without one a step runs where the job does.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol, cast
from uuid import UUID

from .checksum_algorithms import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM
from .checksum_reporting import checksum_report_is_clean, checksum_report_summary
from .checksum_trust import DEFAULT_CHECKSUM_TRUST, ChecksumTrust
from .constants import EXCLUDED_FILE_PATTERNS
from .record_file_lock import RecordFileLock, RecordLockedError
from .rehu_checksums import verify_checksums
from .rehu_rename import is_cross_device, remove_empty_parents
from .relocation import Relocation
from .rename_coordination import (
    DEFAULT_RENAME_COORDINATOR,
    RenameCoordinator,
    RenameYieldTimeout,
    ResourceLocation,
)
from .resource_scoping import is_directory_scoped, resource_name
from .tasks import (
    DEFAULT_TASK_JOB_REGISTRY,
    PROGRESS_UNIT_BYTES,
    JobControl,
    JobOutcome,
    JobWaiting,
    TaskJobBase,
)
from .verified_copy import (
    CopyJournal,
    SourceChangedError,
    SourceListing,
    VerifiedCopy,
    VerifiedCopyError,
    check_move_source,
    remove_leftovers,
)

LOG: Final = logging.getLogger(__name__)

RECORD_MOVE_KIND: Final = "record-move"
"""What a saved queue spells this job as ([[appendices.task-queue#lifetime]]): a promise once written."""

SAVE_PENDING_RETRY: Final = 1.0
"""How long a move waits before looking again for a save of its record to land, in seconds."""

LOCK_HELD_RETRY: Final = 5.0
"""How long a move waits before looking again at a record another process holds the lock of, in seconds."""

READERS_BUSY_RETRY: Final = 2.0
"""How long a move waits before asking again the readers that did not let go of its record in time, in seconds."""

CLEANUP_FILES_KEY: Final = "files"
CLEANUP_FOLDERS_KEY: Final = "folders"
CLEANUP_LEFT_KEY: Final = "left"
CLEANUP_ROOT_KEY: Final = "root"
"""The keys a :class:`MoveCleanup` writes itself down under."""

STATE_SOURCE_ROOT_KEY: Final = "source_root"
STATE_SOURCE_KEY: Final = "source"
STATE_DESTINATION_ROOT_KEY: Final = "destination_root"
STATE_INTO_KEY: Final = "into"
STATE_NAME_KEY: Final = "name"
STATE_MODE_KEY: Final = "mode"
STATE_PHASE_KEY: Final = "phase"
STATE_JOURNAL_KEY: Final = "journal"
STATE_VERIFIED_KEY: Final = "verified"
STATE_CLEANUP_KEY: Final = "cleanup"
STATE_CHECK_SOURCE_KEY: Final = "check_source"
STATE_CHECK_RENAMED_KEY: Final = "check_renamed"
STATE_CREATE_IF_MISSING_KEY: Final = "create_if_missing"
STATE_REMOVE_EMPTY_FOLDERS_KEY: Final = "remove_empty_folders"
STATE_ALGORITHM_KEY: Final = "algorithm"
STATE_EXCLUDED_PATTERNS_KEY: Final = "excluded_patterns"
"""The keys this job writes itself down under; read back by it and by nothing else.

The source is its root's id and the path under it, or with no root the absolute path; the destination is always a root
and a path under it. The settings are captured, so a restored job is the job that was queued."""


class MoveMode(StrEnum):
    """How a record gets to its new place."""

    RENAME = "rename"
    """One volume: renamed, verified before and after when the setting for the volume says so."""

    COPY = "copy"
    """Another volume: copied, the copy verified, the original removed only then."""


class MovePhase(StrEnum):
    """Where a move is; kept, so a stopped move comes back to it."""

    SOURCE = "source"
    """The record is checked, and verified when it must be."""

    MOVE = "move"
    """The files are copied, or the record renamed."""

    TARGET = "target"
    """The record is checked where it now is."""

    FINISH = "finish"
    """A copy's original is brought level with it, then stops being a record."""

    CLEANUP = "cleanup"
    """What is left of a copy's original is removed."""

    DONE = "done"
    """Nothing is left to do."""


@dataclass(frozen=True, slots=True)
class MoveCleanup:
    """What is left of an original once it stopped being a record, kept so a quit before it is all removed still
    removes it.

    :param files: the original's files.
    :param folders: its folders, a parent before its children.
    :param left: the folder its own entry was in.
    :param root: the folder of the root it was under, or ``None`` for none.
    """

    files: tuple[str, ...]
    folders: tuple[str, ...]
    left: str
    root: str | None

    def to_state(self) -> dict[str, Any]:
        """This cleanup as JSON primitives.

        :returns: the state.
        """
        return {
            CLEANUP_FILES_KEY: list(self.files),
            CLEANUP_FOLDERS_KEY: list(self.folders),
            CLEANUP_LEFT_KEY: self.left,
            CLEANUP_ROOT_KEY: self.root,
        }

    @classmethod
    def from_state(cls, state: Any) -> MoveCleanup | None:
        """A cleanup from what :meth:`to_state` wrote.

        :param state: the saved value; ``None`` for a move with nothing to clean up.
        :returns: the cleanup, or ``None``.
        :raises ValueError: the value is not the shape written.
        """
        if state is None:
            return None
        if not isinstance(state, dict):
            raise ValueError("A saved move's cleanup is not an object.")
        files, folders = state.get(CLEANUP_FILES_KEY), state.get(CLEANUP_FOLDERS_KEY)
        left, root = state.get(CLEANUP_LEFT_KEY), state.get(CLEANUP_ROOT_KEY)
        if not (isinstance(files, list) and isinstance(folders, list) and isinstance(left, str)):
            raise ValueError("A saved move's cleanup names no files, folders or folder left.")
        if not all(isinstance(path, str) for path in [*files, *folders]) or not isinstance(root, str | None):
            raise ValueError("A saved move's cleanup names something that is not a path.")
        return cls(tuple(files), tuple(folders), left, root)


class RecordMoveHost(Protocol):
    """What the app lends a move: this machine's roots, its saves, and the thread a rename runs on."""

    def root_folder(self, root_id: UUID) -> Path | None:
        """Where this machine finds a root.

        :param root_id: the root.
        :returns: its folder, or ``None`` when this machine does not map it.
        """

    def save_pending(self, rehu_path: Path) -> bool:  # pyright: ignore[reportReturnType]
        """Whether a save of a record has not landed yet -- a move removing the original waits for it. Asked inside a
        step :meth:`run_step` runs, on the host's thread.

        :param rehu_path: the record's ``.rehu`` file.
        :returns: whether one is queued or running.
        """

    def run_step(self, step: Callable[[], object], checkpoint: Callable[[], None]) -> None:
        """Run ``step`` where a rename runs, and return once it has.

        :param step: what to run; what it raises leaves through here.
        :param checkpoint: called while waiting for ``step`` to start; what it raises abandons ``step``, which then
            never runs.
        """


class RecordMoveHosting:
    """The process-wide :class:`RecordMoveHost`: the one the app installed, or a stand-in answering from this thread.

    Process-wide for the reason :data:`~rehuco_core.DEFAULT_RENAME_COORDINATOR` is: a move restored from a saved queue
    is built with no window to be handed anything.
    """

    def __init__(self) -> None:
        self.__host: RecordMoveHost | None = None

    def install(self, host: RecordMoveHost | None) -> None:
        """Lend moves the app's host, or take it back.

        :param host: the host; ``None`` to go back to the stand-in.
        """
        self.__host = host

    def root_folder(self, root_id: UUID) -> Path | None:
        """See :meth:`RecordMoveHost.root_folder`; with no host installed, no root is mapped.

        :param root_id: the root.
        :returns: its folder, or ``None``.
        """
        return None if self.__host is None else self.__host.root_folder(root_id)

    def save_pending(self, rehu_path: Path) -> bool:
        """See :meth:`RecordMoveHost.save_pending`; with no host installed, none is.

        :param rehu_path: the record's ``.rehu`` file.
        :returns: whether one is queued or running.
        """
        return self.__host is not None and self.__host.save_pending(rehu_path)

    def run_step(self, step: Callable[[], object], checkpoint: Callable[[], None]) -> None:
        """See :meth:`RecordMoveHost.run_step`; with no host installed, ``step`` runs here.

        :param step: what to run.
        :param checkpoint: called first.
        """
        if self.__host is None:
            checkpoint()
            step()
            return
        self.__host.run_step(step, checkpoint)


DEFAULT_RECORD_MOVE_HOST: Final = RecordMoveHosting()
"""The host every move asks unless a test hands it another."""


# a move's members are what it was asked and where it has got; grouping them would put a second shape between the
# enqueuer and the run
# pylint: disable-next=too-many-instance-attributes
class MoveRecordJob(TaskJobBase):
    """One record moved to a place under a root, queued rather than run inline (#339).

    Safely interruptible and resumable: until the *finish* phase's step on the host's thread the original is
    untouched, a stop keeps what was copied, and a cancel removes it again -- running or not.

    :param rehu_path: the record's ``.rehu`` file, or ``None`` for a job about to be handed a saved state.
    :param source_root: the root the record is under, or ``None`` for a record under no root.
    :param destination_root: the root it moves to.
    :param into: the folder its own entry lands in, under the destination root.
    :param new_name: its name there.
    :param mode: a rename or a copy.
    :param check_source: whether a copy verifies the original first (the setting; a copy whose record lacks entries
        verifies it anyway).
    :param check_renamed: whether a rename verifies before and after.
    :param create_if_missing: whether a missing record or missing entries may be made by the source verify.
    :param remove_empty_folders: whether the folders the record left are removed while empty, up to its root.
    :param algorithm: what an entry the source verify adds is recorded under.
    :param excluded_patterns: the globs deciding which files are content.
    :param coordinator: the rename barrier.
    :param trust: where this machine has verified which record.
    :param host: what the app lends this move.
    :param label: the row's name; derived from the record when ``None``.
    """

    kind = RECORD_MOVE_KIND
    progress_unit = PROGRESS_UNIT_BYTES
    resumes_where_it_stopped = True

    def __init__(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        rehu_path: Path | None = None,
        *,
        source_root: UUID | None = None,
        destination_root: UUID | None = None,
        into: PurePosixPath = PurePosixPath(),
        new_name: str = "",
        mode: MoveMode = MoveMode.COPY,
        check_source: bool = True,
        check_renamed: bool = False,
        create_if_missing: bool = False,
        remove_empty_folders: bool = False,
        algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        coordinator: RenameCoordinator | None = None,
        trust: ChecksumTrust | None = None,
        host: RecordMoveHost | None = None,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__trust: Final = trust if trust is not None else DEFAULT_CHECKSUM_TRUST
        self.__host: Final[RecordMoveHost] = host if host is not None else DEFAULT_RECORD_MOVE_HOST
        self.__location: ResourceLocation | None = None if rehu_path is None else self.__coordinator.track(rehu_path)
        self.__unresolved: PurePosixPath | None = None
        self.source_root = source_root
        self.destination_root = destination_root
        self.into = into
        self.new_name = new_name
        self.mode = mode
        self.check_source = check_source
        self.check_renamed = check_renamed
        self.create_if_missing = create_if_missing
        self.remove_empty_folders = remove_empty_folders
        self.algorithm = algorithm
        self.excluded_patterns = excluded_patterns
        self.phase = MovePhase.SOURCE
        self.journal = CopyJournal()
        self.verified: tuple[str, ...] = ()
        self.cleanup: MoveCleanup | None = None
        self.__outcome: JobOutcome | None = None
        self.__state_lock: Final = threading.Lock()
        self.__cancel_asked = False
        self.__working: Final = threading.Lock()
        """Held by a run, and by an idle cancel's undo, so the two never work on the copy at once."""
        self.label = label if label is not None else self.__derived_label()

    # region What the queue reads

    # a property over TaskJobBase's plain attribute, as ChecksumJob's is: re-read live, since a rename moves it
    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The record, **as it is now** -- followed through any rename, and to its new place once moved."""
        return None if self.__location is None else self.__location.path

    @property
    def outcome(self) -> JobOutcome | None:
        """Where the record went, and what of the original could not be removed; ``None`` before a run finished."""
        return self.__outcome

    @property
    def destination(self) -> Path | None:
        """The folder the record's own entry lands in, as this machine finds it; ``None`` when its root is
        unmapped."""
        if self.destination_root is None:
            return None
        root = self.__host.root_folder(self.destination_root)
        return None if root is None else root.joinpath(*self.into.parts)

    def validate(self) -> str | None:
        """Say whether this move can still start: a stat of the record and a look at the roots.

        :returns: ``None`` when it can, else why not.
        """
        path = self.source
        if path is None:
            if self.__unresolved is not None:
                return "The record's root is not mapped on this machine."
            return "This task has no record."
        if self.phase is not MovePhase.DONE and not path.exists():
            return f"The record no longer exists: {path}"
        if self.destination is None:
            return "The root this record moves to is not mapped on this machine."
        return None

    def reset(self) -> None:
        """Start a retried move from its first phase, keeping what a copy wrote, which the copy itself re-checks; one
        whose original already stopped being a record goes on from there."""
        super().reset()
        with self.__state_lock:
            self.__cancel_asked = False
        self.__outcome = None
        if self.phase not in (MovePhase.CLEANUP, MovePhase.DONE):
            self.phase = MovePhase.SOURCE

    def cancel(self) -> None:
        """Record the cancel; the run it stops takes the copy back on its way out."""
        super().cancel()
        with self.__state_lock:
            self.__cancel_asked = True

    def abandon(self) -> None:
        """Take the copy back -- or, past that point, finish removing the original -- on a thread of its own: the
        queue cancelled or removed this job while it was not running, and will never run it again
        (:class:`~rehuco_core.tasks.AbandonableTaskJob`)."""
        threading.Thread(target=self.__give_up, name="move-undo", daemon=True).start()

    def __give_up(self) -> None:
        """What a job given up on while idle still owes: its copy taken back while the original is whole, the
        original's leftovers removed once it is not."""
        if self.phase is not MovePhase.CLEANUP:
            self.__undo_copy()
            return
        with self.__working:
            self.__clean_up()
            self.phase = MovePhase.DONE

    def resume(self) -> bool:
        """Drop the pending request, a cancel included.

        :returns: see :meth:`~rehuco_core.tasks.TaskJobBase.resume`.
        """
        with self.__state_lock:
            self.__cancel_asked = False
        return super().resume()

    # endregion

    # region Running

    def run(self, control: JobControl) -> None:
        """Move the record, phase by phase, from the phase it was left in.

        :param control: the engine's face to this job.
        :raises JobWaiting: a save of the record has not landed, another process holds its lock, or a reader did not
            let go of it in time.
        :raises VerifiedCopyError: the record cannot be checked or holds a link, the original did not verify, or the
            copy did not; a copy's files are removed on the way out.
        :raises JobCancelled: cancelled; a copy's files are removed on the way out.
        :raises OSError: a file could not be read, written, renamed or removed.
        """
        refused = False
        try:
            with self.__working:
                while self.phase is not MovePhase.DONE:
                    self.__run_phase(control)
        except VerifiedCopyError:
            # the copy was refused, or the record cannot be moved at all: nothing unverified stays at the destination
            refused = True
            raise
        finally:
            with self.__state_lock:
                cancelled = self.__cancel_asked
            # however the run ended: a cancel that arrived while it was already unwinding for a pause is still a cancel
            if cancelled or refused:
                self.__undo_copy()

    def __run_phase(self, control: JobControl) -> None:
        """Run the phase this move is in, and step to the next.

        :param control: the engine's face to this job.
        """
        match self.phase:
            case MovePhase.SOURCE:
                self.__check_source(control)
                self.phase = MovePhase.MOVE
            case MovePhase.MOVE:
                self.__move(control)
            case MovePhase.TARGET:
                self.__check_target(control)
            case MovePhase.FINISH:
                self.__finish()
            case MovePhase.CLEANUP:
                self.__clean_up()
                self.phase = MovePhase.DONE
            case _:  # pragma: no cover  (run's loop never enters with DONE)
                pass

    def __check_source(self, control: JobControl) -> None:
        """Make sure a check at the target will mean something, and verify the original when that is asked for.

        :param control: the engine's face to this job.
        :raises VerifiedCopyError: no record or missing entries, with creating them off; or the original did not verify.
        """
        verifies = self.check_source if self.mode is MoveMode.COPY else self.check_renamed
        if self.mode is MoveMode.RENAME and not verifies:
            return
        path = self.__path()
        incomplete = check_move_source(
            path, excluded_patterns=self.excluded_patterns, create_if_missing=self.create_if_missing
        )
        if not (verifies or incomplete):
            return
        report = verify_checksums(
            path,
            coordinator=self.__coordinator,
            algorithm=self.algorithm,
            create_if_missing=self.create_if_missing,
            excluded_patterns=self.excluded_patterns,
            trust=self.__trust,
            progress=control.report,
            checkpoint=self.checkpoint,
        )
        LOG.info("%s: the original: %s", self.label, checksum_report_summary(report))
        if not checksum_report_is_clean(report):
            raise VerifiedCopyError(
                f"The original did not verify ({checksum_report_summary(report)}), so it was not moved."
            )

    def __move(self, control: JobControl) -> None:
        """Copy the files, or rename the record; a rename refused as crossing devices turns into a copy, which starts
        from its own source check.

        :param control: the engine's face to this job.
        """
        destination = self.__destination()
        if self.mode is MoveMode.COPY:
            self.__copy(destination).copy(self.journal, progress=control.report, checkpoint=self.checkpoint)
            self.phase = MovePhase.TARGET
            return
        path = self.__path()
        left = self.__left_folder(path)
        root = self.__source_root_folder()
        try:
            self.__host.run_step(
                lambda: self.__coordinator.rename(path, self.new_name, into=destination), self.checkpoint
            )
        except RenameYieldTimeout as error:
            raise JobWaiting(str(error), READERS_BUSY_RETRY) from error
        except OSError as error:
            if not is_cross_device(error):
                raise
            LOG.info("%s: %s is on another device; copying instead.", self.label, destination)
            self.mode = MoveMode.COPY
            self.phase = MovePhase.SOURCE
            return
        self.__remove_left(left, root)
        self.__outcome = JobOutcome(f"Moved to {destination}")
        self.phase = MovePhase.TARGET if self.check_renamed else MovePhase.DONE

    def __check_target(self, control: JobControl) -> None:
        """Check the record where it now is: a copy always, a rename when its setting says.

        :param control: the engine's face to this job.
        :raises VerifiedCopyError: the copy did not match its record, or the renamed record did not verify.
        """
        if self.mode is MoveMode.COPY:
            report = self.__copy(self.__destination()).verify_target(
                trust=self.__trust, algorithm=self.algorithm, progress=control.report, checkpoint=self.checkpoint
            )
            self.verified = tuple(sorted(report.statuses))
            LOG.info("%s: the copy: %s", self.label, checksum_report_summary(report))
            self.phase = MovePhase.FINISH
            return
        report = verify_checksums(
            self.__path(),
            coordinator=self.__coordinator,
            algorithm=self.algorithm,
            excluded_patterns=self.excluded_patterns,
            trust=self.__trust,
            progress=control.report,
            checkpoint=self.checkpoint,
        )
        LOG.info("%s: after the rename: %s", self.label, checksum_report_summary(report))
        self.phase = MovePhase.DONE
        if not checksum_report_is_clean(report):
            raise VerifiedCopyError(
                f"The record was moved, but did not verify there ({checksum_report_summary(report)})."
            )

    def __finish(self) -> None:
        """Bring the copy level with the original, here; then, on the host's thread, make the original stop being a
        record -- once no save of it is on its way and no one else holds its lock, both asked there, where a save is
        queued, so none can be queued between the asking and the removing.

        An original that changed between the two is brought level again, as often as it takes.

        :raises JobWaiting: a save has not landed, another process holds the record's lock, or a reader did not let
            go in time.
        """
        copy = self.__copy(self.__destination())
        while self.phase is MovePhase.FINISH:
            reconciled = copy.reconcile(self.journal, self.verified)
            path = reconciled.record
            cleanup = MoveCleanup(
                tuple(reconciled.files),
                reconciled.folders,
                str(self.__left_folder(path)),
                None if (root := self.__source_root_folder()) is None else str(root),
            )

            def detach(listing: SourceListing = reconciled, after: MoveCleanup = cleanup) -> Relocation:
                """Make the original stop being a record; from here on a cancel leaves the copy alone."""
                relocation = copy.detach_source(listing)
                self.cleanup = after
                self.phase = MovePhase.CLEANUP
                return relocation

            def finish(record: Path = path, step: Callable[[], Relocation] = detach) -> None:
                """Wait for a save, a lock or a reader; else detach the original behind the rename barrier."""
                if self.__host.save_pending(record):
                    raise JobWaiting("A save of this record has not landed yet.", SAVE_PENDING_RETRY)
                try:
                    RecordFileLock(record).refuse_if_held()
                    self.__coordinator.run(record, step)
                except RecordLockedError as error:
                    raise JobWaiting(str(error), LOCK_HELD_RETRY) from error
                except RenameYieldTimeout as error:
                    raise JobWaiting(str(error), READERS_BUSY_RETRY) from error

            try:
                self.__host.run_step(finish, self.checkpoint)
            except SourceChangedError:
                LOG.info("%s: the original changed while being moved; comparing it again.", self.label)
                continue
            self.__trust.forget(path)

    def __clean_up(self) -> None:
        """Remove what is left of the original, and the folders it left empty; say what would not go."""
        cleanup = cast(MoveCleanup, self.cleanup)
        destination = self.__destination()
        left = remove_leftovers(cleanup.files, cleanup.folders)
        self.__remove_left(Path(cleanup.left), None if cleanup.root is None else Path(cleanup.root))
        self.cleanup = None
        if left:
            self.__outcome = JobOutcome(
                f"Moved to {destination}; could not remove from the original: {'; '.join(left)}", clean=False
            )
        else:
            self.__outcome = JobOutcome(f"Moved to {destination}")

    def __undo_copy(self) -> None:
        """Remove what a cancelled or refused copy wrote, while the original is still whole; log what would not go.

        Runs at the end of a cancelled or refused run, or on a thread of its own for a job given up on while idle.
        """
        with self.__working:
            if self.mode is not MoveMode.COPY or self.phase not in (
                MovePhase.MOVE,
                MovePhase.TARGET,
                MovePhase.FINISH,
            ):
                return
            path, destination = self.source, self.destination
            if path is None or destination is None:
                LOG.warning(
                    "%s: a root is not mapped here, so the cancelled move's copy was left in place.", self.label
                )
                return
            for line in self.__copy(destination).remove_copy(self.journal):
                LOG.warning("Could not remove %s from a cancelled move's copy.", line)
            self.journal = CopyJournal()

    def __remove_left(self, folder: Path, root: Path | None) -> None:
        """Remove the folders the record left while empty, up to its root, when that is asked for.

        :param folder: the folder the record's own entry was in.
        :param root: the source root's folder; ``None`` for a record under no root, which is left as it is.
        """
        if not self.remove_empty_folders or root is None:
            return
        for removed in remove_empty_parents(folder, root):
            LOG.info("Removed %s, left empty by the move.", removed)

    def __copy(self, destination: Path) -> VerifiedCopy:
        """The copy of this record into ``destination``.

        :param destination: the folder its own entry lands in.
        :returns: the copy, built afresh.
        """
        return VerifiedCopy(
            self.__path(),
            destination,
            self.new_name,
            coordinator=self.__coordinator,
            excluded_patterns=self.excluded_patterns,
        )

    def __path(self) -> Path:
        """The record now.

        :returns: its ``.rehu`` file.
        :raises ValueError: the job has none.
        """
        path = self.source
        if path is None:
            raise ValueError("A move has no record to move.")
        return path

    def __destination(self) -> Path:
        """The folder the record lands in.

        :returns: the folder.
        :raises ValueError: its root is not mapped here.
        """
        destination = self.destination
        if destination is None:
            raise ValueError("The root this record moves to is not mapped on this machine.")
        return destination

    def __source_root_folder(self) -> Path | None:
        """The source root's folder, or ``None`` for a record under no root, or one this machine does not map."""
        return None if self.source_root is None else self.__host.root_folder(self.source_root)

    @staticmethod
    def __left_folder(path: Path) -> Path:
        """The folder a record's own entry is in: the one holding its folder, or holding its files."""
        return path.parent.parent if is_directory_scoped(path) else path.parent

    # endregion

    # region Being written down

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this move needs to be itself again: each end by its root, the phase, what was copied.

        :returns: the state, JSON primitives only.
        """
        return {
            **self.__captured_source(),
            STATE_DESTINATION_ROOT_KEY: None if self.destination_root is None else str(self.destination_root),
            STATE_INTO_KEY: self.into.as_posix(),
            STATE_NAME_KEY: self.new_name,
            STATE_MODE_KEY: self.mode.value,
            STATE_PHASE_KEY: self.phase.value,
            STATE_JOURNAL_KEY: self.journal.to_state(),
            STATE_VERIFIED_KEY: list(self.verified),
            STATE_CLEANUP_KEY: None if self.cleanup is None else self.cleanup.to_state(),
            STATE_CHECK_SOURCE_KEY: self.check_source,
            STATE_CHECK_RENAMED_KEY: self.check_renamed,
            STATE_CREATE_IF_MISSING_KEY: self.create_if_missing,
            STATE_REMOVE_EMPTY_FOLDERS_KEY: self.remove_empty_folders,
            STATE_ALGORITHM_KEY: self.algorithm,
            STATE_EXCLUDED_PATTERNS_KEY: list(self.excluded_patterns),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the move that captured ``state``.

        A source under a root this machine does not map now stays unresolved, and :meth:`validate` says so, rather
        than the item being dropped: mapping the root and retrying brings it back.

        :param state: whatever :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a move.
        """
        destination_root = self.__uuid(state.get(STATE_DESTINATION_ROOT_KEY), "destination root")
        if destination_root is None:
            raise ValueError("A saved move names no destination root.")
        name = state.get(STATE_NAME_KEY)
        into = state.get(STATE_INTO_KEY)
        if not isinstance(name, str) or not name or not isinstance(into, str):
            raise ValueError("A saved move names no place to move to.")
        algorithm = state.get(STATE_ALGORITHM_KEY, DEFAULT_CHECKSUM_ALGORITHM)
        if algorithm not in CHECKSUM_ALGORITHMS:
            raise ValueError(f"A saved move names an unknown algorithm: {algorithm!r}")
        verified = state.get(STATE_VERIFIED_KEY, [])
        if not (isinstance(verified, list) and all(isinstance(entry, str) for entry in verified)):
            raise ValueError("A saved move's verified files are not a list of names.")
        excluded = state.get(STATE_EXCLUDED_PATTERNS_KEY)
        cleanup = MoveCleanup.from_state(state.get(STATE_CLEANUP_KEY))
        if (cleanup is None) is (state.get(STATE_PHASE_KEY) == MovePhase.CLEANUP.value):
            raise ValueError("A saved move's cleanup does not go with its phase.")
        self.__restore_source(state)
        self.cleanup = cleanup
        self.destination_root = destination_root
        self.into = PurePosixPath(into)
        self.new_name = name
        self.mode = MoveMode(state.get(STATE_MODE_KEY, MoveMode.COPY.value))
        self.phase = MovePhase(state.get(STATE_PHASE_KEY, MovePhase.SOURCE.value))
        self.journal = CopyJournal.from_state(state.get(STATE_JOURNAL_KEY))
        self.verified = tuple(verified)
        self.check_source = bool(state.get(STATE_CHECK_SOURCE_KEY, True))
        self.check_renamed = bool(state.get(STATE_CHECK_RENAMED_KEY, False))
        self.create_if_missing = bool(state.get(STATE_CREATE_IF_MISSING_KEY, False))
        self.remove_empty_folders = bool(state.get(STATE_REMOVE_EMPTY_FOLDERS_KEY, False))
        self.algorithm = algorithm
        if isinstance(excluded, list) and all(isinstance(pattern, str) for pattern in excluded):
            self.excluded_patterns = tuple(excluded)
        self.label = self.__derived_label()

    def __captured_source(self) -> dict[str, Any]:
        """The source end: its root and the path under it when it has a mapped root holding it, else the path.

        :returns: the state's source keys.
        """
        path = self.source
        if self.source_root is not None and path is None and self.__unresolved is not None:
            return {STATE_SOURCE_ROOT_KEY: str(self.source_root), STATE_SOURCE_KEY: self.__unresolved.as_posix()}
        root = self.__source_root_folder()
        if path is not None and root is not None and path.is_relative_to(root):
            relative = PurePosixPath(*path.relative_to(root).parts)
            return {STATE_SOURCE_ROOT_KEY: str(self.source_root), STATE_SOURCE_KEY: relative.as_posix()}
        return {STATE_SOURCE_ROOT_KEY: None, STATE_SOURCE_KEY: "" if path is None else str(path)}

    def __restore_source(self, state: dict[str, Any]) -> None:
        """Track the source a state names, resolving its root through the host.

        :param state: the saved state.
        :raises ValueError: the state names no source.
        """
        source = state.get(STATE_SOURCE_KEY)
        if not isinstance(source, str) or not source:
            raise ValueError("A saved move names no record.")
        self.source_root = self.__uuid(state.get(STATE_SOURCE_ROOT_KEY), "source root")
        self.__unresolved = None
        if self.source_root is None:
            self.__location = self.__coordinator.track(Path(source))
            return
        root = self.__host.root_folder(self.source_root)
        if root is None:
            self.__location = None
            self.__unresolved = PurePosixPath(source)
            return
        self.__location = self.__coordinator.track(root.joinpath(*PurePosixPath(source).parts))

    @staticmethod
    def __uuid(value: Any, what: str) -> UUID | None:
        """A root's id as saved.

        :param value: the saved value.
        :param what: what it is, for the error.
        :returns: the id, or ``None`` when none was saved.
        :raises ValueError: something other than an id was saved.
        """
        if value is None:
            return None
        try:
            return UUID(str(value))
        except ValueError as error:
            raise ValueError(f"A saved move's {what} is not an id: {value!r}") from error

    # endregion

    def __derived_label(self) -> str:
        """This move's own name for itself, e.g. ``"Move - Sculpting Series"``."""
        path = self.source
        return "Move" if path is None else f"Move - {resource_name(path)}"


DEFAULT_TASK_JOB_REGISTRY.register(RECORD_MOVE_KIND, MoveRecordJob)
