"""Generate and verify a resource's checksums, over its ``.checksum`` record
([[data-model#checksums]], #203).

**Generate and verify take the same selection** -- they are two halves of one workflow, and a selection
meaning different things in each would be a trap. ``only`` narrows both to one file, a set, or the whole
record; ``stale_after`` skips entries verified recently, and ``None`` verifies everything, which is how
*force* is expressed -- there is no separate force flag to drift out of step. The real workflow this
serves: verify, inspect what came back ``mismatched``, decide whether the change was genuine (an archive
legitimately repacked; or corruption with no backup, where keeping a checksum that can only ever fail
helps nobody), then re-baseline just those files with a targeted generate -- without re-reading the
terabyte that was fine.

**Core ships these as plain callables** ([[data-model#checksums]]): progress and a checkpoint are
parameters, the checkpoint is called between chunks and never caught, so a job's pause and cancel travel
out untouched and this module never learns a queue exists
([[appendices.task-queue#job-responsibility]]). Progress counts **bytes, not files** -- a tutorial is
three eight-gigabyte videos, and a bar that moves three times in twenty minutes says nothing.

**A cancelled run reports nothing it did not establish.** A verdict exists only once a file's whole
digest has been computed and compared, and the record is written **once, at the end**, through the
atomic writer -- so a stop between chunks leaves the previous record intact, and can never manufacture
a mismatch.

Which files are content is :func:`~rehuco_core.enumerate_content_files`'s answer (#226), shared with the
size scan; reads go through :func:`~rehuco_core.read_content_chunks` (#241), so a rename can land
mid-verify and the run follows the resource. The record's *format* -- entries, statuses, load and save --
is :mod:`rehuco_core.checksum_record`'s.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final

from .checksum_algorithms import CHECKSUM_ALGORITHMS, DEFAULT_CHECKSUM_ALGORITHM, ChecksumDigest
from .checksum_record import (
    CHECKSUM_FILES_KEY,
    CHECKSUM_NAME_KEY,
    CHECKSUM_STATUS_KEY,
    CHECKSUM_VERIFIED_KEY,
    ChecksumEntry,
    ChecksumStatus,
    checksum_entry_name,
    checksum_record_path,
    load_checksum_record,
    new_checksum_record,
    parse_checksum_entry,
    save_checksum_record,
    verified_stamp,
)
from .constants import EXCLUDED_FILE_PATTERNS
from .content_reading import read_content_chunks
from .rehu_content_files import enumerate_content_files
from .rename_coordination import RenameCoordinator, ResourceLocation

ChecksumProgress = Callable[[int, int | None], None]
"""How a run says how far it has got: bytes hashed so far, against the bytes it expects to read in all --
or ``None`` when a size could not be read up front, an honest *indeterminate* rather than a denominator
that lies. The same ``(done, total)`` shape :meth:`~rehuco_core.tasks.JobControl.report` takes, so a job
passes its control's method straight through (#204)."""

ChecksumCheckpoint = Callable[[], None]
"""A run's place to stop: called before each file and between chunks, **never caught here**
([[appendices.task-queue#job-responsibility]]) -- whatever it raises travels out with the record
unwritten, which is the whole cancellation contract. :meth:`~rehuco_core.tasks.TaskJobBase.checkpoint`
is exactly this shape."""


@dataclass(frozen=True, slots=True)
class ChecksumReport:
    """What one generate or verify established ([[data-model#checksums]], #203).

    The *run's* answers, which are not always the record's: an adopted file is reported ``unexpected``
    -- that is what the run found -- while the record now holds it ``matched`` under a fresh hash, so
    the state does not rest. Nothing skipped or untouched appears in :attr:`statuses`.

    :param statuses: per file name, what this run established -- hashed-and-compared verdicts,
        ``missing``, ``unexpected``, and ``malformed`` for an entry with a readable name this build
        cannot read.
    :param skipped: the names left alone because they were verified within ``stale_after`` -- what a
        sweep (#242) counts to say how much recent work it saved.
    :param unreadable: the names whose file exists but could not be read (a permission refusal, a mount
        that went away mid-run) -- deliberately **not** ``missing`` and not recorded: an I/O failure is
        not a verdict about the bytes, so the entry is carried untouched and reported here instead.
    :param unnamed_malformed: how many entries could not even be named -- reportable only as a count,
        since a name is exactly what they lack.
    """

    statuses: dict[str, ChecksumStatus] = field(default_factory=dict)
    skipped: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    unnamed_malformed: int = 0


class ChecksumRun:  # pylint: disable=too-many-instance-attributes
    """One generate or verify over one resource's record ([[data-model#checksums]], #203).

    Built per call by :func:`generate_checksums` / :func:`verify_checksums` and thrown away; the state
    it keeps is the run's own bookkeeping (the clock read once, bytes done, the report growing), never
    anything a second run could inherit.

    :param rehu_path: the resource's ``.rehu`` file.
    :param coordinator: the rename barrier to read through, or ``None`` for a private one -- through
        which no rename will ever arrive, so a caller outside any queue reads plainly (#241).
    :param algorithm: what new hashes are recorded under -- a fresh baseline's, and the one a verify
        adopts an unrecorded file with.
    :param only: the file names (record-relative, POSIX-separated) to work on, or ``None`` for the
        whole record. A name matching neither an entry nor a file on disk is reported ``missing``.
    :param stale_after: skip entries verified more recently than this; ``None`` checks everything,
        which is how *force* is expressed.
    :param create_if_missing: whether a resource with no ``.checksum`` yet starts from an empty record
        rather than raising.
    :param migrate_to: re-record matched entries under this algorithm (*Update checksums on verify*),
        or ``None`` to leave every entry on its own; verify-only, see :meth:`verify`.
    :param excluded_patterns: filename globs the content walk leaves out, passed straight through to
        :func:`~rehuco_core.enumerate_content_files` (#226).
    :param progress: told how far the run has got, in bytes; ``None`` for nobody.
    :param checkpoint: the run's place to stop; ``None`` for a run that cannot be stopped.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        rehu_path: Path,
        *,
        coordinator: RenameCoordinator | None,
        algorithm: str,
        only: Collection[str] | None,
        stale_after: timedelta | None,
        create_if_missing: bool,
        migrate_to: str | None,
        excluded_patterns: tuple[str, ...],
        progress: ChecksumProgress | None,
        checkpoint: ChecksumCheckpoint | None,
    ) -> None:
        for name in (algorithm, *(() if migrate_to is None else (migrate_to,))):
            if name not in CHECKSUM_ALGORITHMS:
                raise ValueError(f"Unknown checksum algorithm: {name!r}")
        self.__coordinator: Final = coordinator if coordinator is not None else RenameCoordinator()
        self.__rehu_location: Final = self.__coordinator.track(rehu_path)
        self.__algorithm: Final = algorithm
        self.__only: Final[frozenset[str] | None] = None if only is None else frozenset(only)
        self.__stale_after: Final = stale_after
        self.__create_if_missing: Final = create_if_missing
        self.__migrate_to: Final = migrate_to
        self.__excluded_patterns: Final = excluded_patterns
        self.__progress: Final = progress
        self.__checkpoint: Final = checkpoint
        self.__now: Final = datetime.now(UTC)
        self.__stamp: Final = verified_stamp(self.__now)
        self.__record: Final[dict[str, Any]] = self.__load()
        self.__entries: Final[list[Any]] = self.__record[CHECKSUM_FILES_KEY]
        self.__content: Final = self.__content_locations()
        self.__done = 0
        self.__total: int | None = 0
        self.__statuses: Final[dict[str, ChecksumStatus]] = {}
        self.__skipped: Final[list[str]] = []
        self.__unreadable: Final[list[str]] = []
        self.__unnamed_malformed = 0

    # region The two operations

    def verify(self) -> ChecksumReport:
        """Check what the record lists, and adopt what it does not.

        Every selected, non-fresh entry with a hash is read whole and compared under **its own recorded
        algorithm** -- the recorded algorithm decides the verdict, whatever is configured today. With
        ``migrate_to`` set, an entry recorded under another algorithm is read **once**, feeding two
        digests at the same time; if the old one matches, the old key is dropped and the new replaces
        it, and if it fails the entry is ``mismatched``, still under its old key, with the new hash
        **discarded** -- a new hash is only ever kept for a matched file, because blessing bad bytes
        under a new name would launder corruption into a record that then looks clean forever.

        A selected content file with no recorded hash is **adopted** -- hashed, dated, recorded
        ``matched`` -- and reported ``unexpected``, so that is a report state rather than a resting one.
        The exclusion set never touches a verdict: entries are checked whatever it says, and it only
        decides which unlisted files exist to be adopted ([[data-model#checksums]]).

        :returns: what the run established.
        :raises FileNotFoundError: no record and ``create_if_missing`` is off.
        :raises ChecksumRecordError: a record file this build cannot read at all.
        :raises OSError: the record could not be re-written at the end.
        """
        recorded: set[str] = set()
        for raw in self.__entries:
            name = checksum_entry_name(raw)
            if name is not None:
                recorded.add(name)
        adoptees = [name for name in self.__content if name not in recorded and self.__selected(name)]
        self.__plan(self.__verify_reads() + [self.__content[name] for name in adoptees])
        rewritten = [self.__verify_entry(raw) for raw in self.__entries]
        rewritten.extend(entry for entry in map(self.__adopt, adoptees) if entry is not None)
        self.__save(rewritten)
        return self.__report()

    def generate(self) -> ChecksumReport:
        """(Re-)baseline the record under the configured algorithm.

        With no selection, the record becomes exactly the content files on disk, each hashed fresh --
        entries for files that no longer exist are dropped, because a baseline describes what *is*.
        With ``only``, **exactly the named entries are re-baselined and no others are touched**: their
        hash is rewritten under the configured algorithm whatever they carried before -- including a
        hash this build could not read, which is how a broken entry gets fixed -- and every other
        entry is carried through byte-for-byte, mismatches and all.

        :returns: what the run established -- ``matched`` per file baselined, ``missing`` for a named
            file that is not there to hash.
        :raises FileNotFoundError: no record and ``create_if_missing`` is off.
        :raises ChecksumRecordError: a record file this build cannot read at all.
        :raises OSError: the record could not be written at the end.
        """
        if self.__only is None:
            self.__save(self.__generate_baseline())
        else:
            self.__save(self.__generate_targeted(self.__only))
        return self.__report()

    # endregion

    # region Setup

    def __load(self) -> dict[str, Any]:
        """Read the record whole, or start a fresh one where ``create_if_missing`` allows.

        :returns: the record object, entries included.
        :raises FileNotFoundError: no record and creating one was not asked for.
        """
        try:
            return load_checksum_record(checksum_record_path(self.__rehu_location.path))
        except FileNotFoundError:
            if self.__create_if_missing:
                return new_checksum_record()
            raise

    def __content_locations(self) -> dict[str, ResourceLocation]:
        """Enumerate the resource's content, each file tracked across renames.

        The shared answer (#226): the same enumeration the size scan reads, so a file counted there and
        skipped here is impossible by construction. Names are relative to the ``.rehu``,
        POSIX-separated -- the record's own spelling.

        :returns: name to tracked location, in enumeration order.
        """
        rehu_path = self.__rehu_location.path
        return {
            path.relative_to(rehu_path.parent).as_posix(): self.__coordinator.track(path)
            for path in enumerate_content_files(rehu_path, self.__excluded_patterns)
        }

    def __locate(self, name: str) -> ResourceLocation:
        """Where a record-listed name points, content or not.

        A verify checks what the record lists whatever the exclusion set says
        ([[data-model#checksums]]), so a name outside the content enumeration is still resolved --
        against the ``.rehu``'s *current* directory, and tracked from here on like any other read.

        :param name: a validated record-relative name (:func:`~rehuco_core.checksum_entry_name`).
        :returns: the tracked location.
        """
        location = self.__content.get(name)
        if location is not None:
            return location
        return self.__coordinator.track(self.__rehu_location.path.parent / PurePosixPath(name))

    # endregion

    # region Verify

    def __verify_reads(self) -> list[ResourceLocation]:
        """The locations :meth:`verify` will read, for the progress denominator.

        :returns: one location per selected, non-fresh, readable entry -- hashed or awaiting adoption.
        """
        reads = []
        seen: set[str] = set()
        for raw in self.__entries:
            entry = parse_checksum_entry(raw)
            if entry is None or entry.name in seen:
                continue
            if self.__selected(entry.name) and not self.__fresh(entry):
                seen.add(entry.name)
                reads.append(self.__locate(entry.name))
        return reads

    def __verify_entry(self, raw: Any) -> Any:
        """Check one record entry, answering what replaces it -- the raw object itself when untouched.

        :param raw: the entry as loaded.
        :returns: the rewritten entry, or ``raw`` carried through byte-for-byte.
        """
        entry = parse_checksum_entry(raw)
        if entry is None:
            name = checksum_entry_name(raw)
            if name is None:
                self.__unnamed_malformed += 1
            else:
                self.__statuses[name] = "malformed"
            return raw
        if not self.__selected(entry.name):
            return raw
        if self.__fresh(entry):
            self.__skipped.append(entry.name)
            return raw
        if entry.algorithm is None or entry.digest is None:
            return self.__adopt_listed(raw, entry)
        return self.__check_entry(raw, entry, entry.algorithm, entry.digest)

    def __check_entry(self, raw: Any, entry: ChecksumEntry, algorithm: str, digest: str) -> Any:
        """Hash one recorded file and record the verdict -- the migrate-while-verifying core.

        One read feeds every digest at once ([[data-model#checksums]], #203): the entry's own and,
        when migrating from another algorithm, the target's -- so migration costs zero extra reads,
        and the recorded algorithm still decides the verdict.

        :param raw: the entry as loaded.
        :param entry: its parsed view.
        :param algorithm: the entry's recorded algorithm -- what decides the verdict.
        :param digest: the recorded hash, as spelled on disk.
        :returns: the entry rewritten with a fresh date and verdict, or ``raw`` when the file exists
            and cannot be read -- an I/O failure is not a verdict.
        """
        # `migrate_to` is, from here on, the algorithm to move to or None -- an entry already recorded
        # under it has nowhere to move
        migrate_to = self.__migrate_to if self.__migrate_to != algorithm else None
        algorithms = (algorithm,) if migrate_to is None else (algorithm, migrate_to)
        try:
            digests = self.__digest(self.__locate(entry.name), algorithms)
        except FileNotFoundError:
            self.__statuses[entry.name] = "missing"
            return self.__rewritten(raw, entry, algorithm, digest, "missing")
        except OSError:
            self.__unreadable.append(entry.name)
            return raw
        if digests[0].lower() != digest.lower():
            self.__statuses[entry.name] = "mismatched"
            return self.__rewritten(raw, entry, algorithm, digest, "mismatched")
        self.__statuses[entry.name] = "matched"
        if migrate_to is not None:
            return self.__rewritten(raw, entry, migrate_to, digests[1], "matched")
        return self.__rewritten(raw, entry, algorithm, digest, "matched")

    def __adopt_listed(self, raw: Any, entry: ChecksumEntry) -> Any:
        """Adopt an entry that is listed but has never been hashed -- a resting ``unexpected``.

        Its being listed outranks today's exclusion set: whoever recorded the name meant the file, so
        it is hashed even when the enumeration no longer covers it.

        :param raw: the entry as loaded.
        :param entry: its parsed view, known to carry no hash.
        :returns: the entry rewritten as freshly ``matched``, as ``missing`` when the file is gone, or
            ``raw`` when it cannot be read.
        """
        try:
            digest = self.__digest(self.__locate(entry.name), (self.__algorithm,))[0]
        except FileNotFoundError:
            self.__statuses[entry.name] = "missing"
            return self.__rewritten(raw, entry, None, None, "missing")
        except OSError:
            self.__unreadable.append(entry.name)
            return raw
        self.__statuses[entry.name] = "matched"
        return self.__rewritten(raw, entry, self.__algorithm, digest, "matched")

    def __adopt(self, name: str) -> Any | None:
        """Adopt one content file the record does not list -- hash it, date it, record it ``matched``.

        Reported ``unexpected``, because that is what the run *found*; recorded ``matched``, so
        ``unexpected`` never rests ([[data-model#checksums]], #203).

        :param name: the content file's name.
        :returns: the fresh entry; a hash-less resting ``unexpected`` when the file cannot be read; or
            ``None`` when it vanished between the enumeration and the read, in which case it is not
            reported either -- there is nothing there to be unexpected.
        """
        self.__statuses[name] = "unexpected"
        try:
            digest = self.__digest(self.__content[name], (self.__algorithm,))[0]
        except FileNotFoundError:
            del self.__statuses[name]
            return None
        except OSError:
            return {CHECKSUM_NAME_KEY: name, CHECKSUM_STATUS_KEY: "unexpected"}
        return self.__fresh_entry(name, digest)

    # endregion

    # region Generate

    def __generate_baseline(self) -> list[Any]:
        """A full baseline: one fresh entry per content file, in enumeration order.

        :returns: the new record's entries; a fresh (``stale_after``) entry is carried instead of
            re-hashed, and a file that cannot be read keeps its old entry, if any, untouched.
        """
        carried: dict[str, Any] = {}
        for raw in self.__entries:
            name = checksum_entry_name(raw)
            if name is not None and name not in carried:
                carried[name] = raw
        self.__plan(
            [
                location
                for name, location in self.__content.items()
                if self.__selected(name) and not self.__fresh(parse_checksum_entry(carried.get(name)))
            ]
        )
        rewritten: list[Any] = []
        for name, location in self.__content.items():
            existing = carried.get(name)
            if self.__fresh(parse_checksum_entry(existing)):
                self.__skipped.append(name)
                rewritten.append(existing)
                continue
            entry = self.__baseline_file(name, location, existing)
            if entry is not None:
                rewritten.append(entry)
        return rewritten

    def __generate_targeted(self, only: frozenset[str]) -> list[Any]:
        """Re-baseline exactly the named entries; carry every other byte-for-byte.

        A named file ends holding **exactly one entry**: the first entry of its name takes the fresh
        baseline (or the freshness skip) and any further entry of that name is dropped, because a
        duplicate -- which only ever arrives by hand-editing -- would otherwise carry a stale hash the
        rebaseline just declared wrong, and fail every verify after it. The full baseline already
        deduplicates the same way; only *unnamed* entries are outside a targeted call's writ.

        :param only: the names to re-baseline.
        :returns: the record's entries, with the named ones rewritten and names the record never held
            appended -- or reported ``missing`` when there is no file to hash.
        """
        touched: set[str] = set()
        fresh = {
            name
            for raw in self.__entries
            if (name := checksum_entry_name(raw)) is not None and self.__fresh(parse_checksum_entry(raw))
        }
        self.__plan([self.__locate(name) for name in sorted(only - fresh)])
        rewritten: list[Any] = []
        for raw in self.__entries:
            name = checksum_entry_name(raw)
            if name is None or name not in only:
                rewritten.append(raw)
                continue
            if name in touched:
                continue
            touched.add(name)
            if self.__fresh(parse_checksum_entry(raw)):
                self.__skipped.append(name)
                rewritten.append(raw)
                continue
            # never ``None``: handed its own entry to fall back on, this answers a fresh baseline or
            # that same entry -- an existing entry is exactly what a targeted call cannot drop
            rewritten.append(self.__baseline_file(name, self.__locate(name), raw))
        for name in sorted(only - touched):
            entry = self.__baseline_file(name, self.__locate(name), None)
            if entry is not None:
                rewritten.append(entry)
        return rewritten

    def __baseline_file(self, name: str, location: ResourceLocation, existing: Any) -> Any | None:
        """Hash one file fresh, however its old entry spelled it.

        :param name: the file's name.
        :param location: where it is.
        :param existing: its old entry, carried when the file exists but cannot be read, or ``None``.
        :returns: the fresh ``matched`` entry; ``existing`` (which may be ``None``) when the file is
            unreadable or gone -- a missing file is reported, never given an entry it cannot honor.
        """
        try:
            digest = self.__digest(location, (self.__algorithm,))[0]
        except FileNotFoundError:
            self.__statuses[name] = "missing"
            return existing
        except OSError:
            self.__unreadable.append(name)
            return existing
        self.__statuses[name] = "matched"
        return self.__fresh_entry(name, digest)

    # endregion

    # region Shared plumbing

    def __selected(self, name: str) -> bool:
        """Whether ``only`` lets this name through -- everything, when there is no selection."""
        return self.__only is None or name in self.__only

    def __fresh(self, entry: ChecksumEntry | None) -> bool:
        """Whether ``stale_after`` says this entry was verified recently enough to leave alone.

        ``None`` -- no window -- means nothing is fresh: *force*, spelled as the absence of a skip
        rather than as a second flag ([[data-model#checksums]], #203).
        """
        if self.__stale_after is None or entry is None or entry.verified is None:
            return False
        return self.__now - entry.verified < self.__stale_after

    def __plan(self, reads: list[ResourceLocation]) -> None:
        """Add up what the run is about to read, and say so.

        :param reads: the locations the run will hash. A size that cannot be read counts zero -- that
            file's read will fail in a way already accounted for -- and the caller is told immediately,
            so a bar has its denominator before the first slow read.
        """
        total = 0
        for location in reads:
            try:
                total += location.path.stat().st_size
            except OSError:
                continue
        self.__total = total
        if self.__progress is not None:
            self.__progress(self.__done, self.__total)

    def __digest(self, location: ResourceLocation, algorithms: tuple[str, ...]) -> list[str]:
        """Read one file whole, feeding every named digest from the same pass.

        The single-read guarantee the migration rests on ([[data-model#checksums]], #203): however many
        algorithms are asked for, the bytes move once. The checkpoint runs before the first chunk and
        after every one, and whatever it raises leaves through here uncaught with the record unwritten.

        :param location: the file, tracked across renames.
        :param algorithms: the algorithm names to feed; all known, by the constructor's validation.
        :returns: the hex digests, in ``algorithms``' order.
        :raises OSError: the file could not be opened or read.
        """
        digests: list[ChecksumDigest] = [CHECKSUM_ALGORITHMS[name].new_digest() for name in algorithms]
        if self.__checkpoint is not None:
            self.__checkpoint()
        chunks = read_content_chunks(location, self.__coordinator)
        try:
            for chunk in chunks:
                for digest in digests:
                    digest.update(chunk)
                self.__done += len(chunk)
                if self.__progress is not None:
                    self.__progress(self.__done, self.__total)
                if self.__checkpoint is not None:
                    self.__checkpoint()
        finally:
            chunks.close()
        return [digest.hexdigest() for digest in digests]

    def __fresh_entry(self, name: str, digest: str) -> dict[str, Any]:
        """A brand-new ``matched`` entry under the configured algorithm, dated now."""
        return {
            CHECKSUM_NAME_KEY: name,
            self.__algorithm: digest,
            CHECKSUM_VERIFIED_KEY: self.__stamp,
            CHECKSUM_STATUS_KEY: "matched",
        }

    def __rewritten(
        self, raw: Any, entry: ChecksumEntry, algorithm: str | None, digest: str | None, status: ChecksumStatus
    ) -> dict[str, Any]:
        """One entry re-recorded with a fresh date and verdict, extras carried.

        :param raw: the entry as loaded; keys this method does not spell -- annotations from another
            build -- are appended unchanged, all but the *old* hash key, which ``algorithm`` replaces.
        :param entry: the parsed view, for the name and the old algorithm.
        :param algorithm: the key the hash is recorded under now, or ``None`` for no hash at all.
        :param digest: the hash to record, exactly as it should be spelled.
        :param status: the verdict.
        :returns: the rewritten entry.
        """
        updated: dict[str, Any] = {CHECKSUM_NAME_KEY: entry.name}
        if algorithm is not None and digest is not None:
            updated[algorithm] = digest
        updated[CHECKSUM_VERIFIED_KEY] = self.__stamp
        updated[CHECKSUM_STATUS_KEY] = status
        for key, value in raw.items():
            if key not in updated and key != entry.algorithm:
                updated[key] = value
        return updated

    def __save(self, rewritten: list[Any]) -> None:
        """Write the record back -- once, atomically, and only when something changed.

        Any name asked for that the run never met is reported ``missing`` first, so a typo in a
        targeted call answers plainly instead of silently doing nothing.

        :param rewritten: the record's entries as this run leaves them.
        """
        if self.__only is not None:
            for name in self.__only:
                if name not in self.__statuses and name not in self.__skipped and name not in self.__unreadable:
                    self.__statuses[name] = "missing"
        if rewritten != self.__entries:
            self.__record[CHECKSUM_FILES_KEY] = rewritten
            save_checksum_record(checksum_record_path(self.__rehu_location.path), self.__record)

    def __report(self) -> ChecksumReport:
        """The run's answers, frozen for the caller."""
        return ChecksumReport(
            statuses=dict(self.__statuses),
            skipped=tuple(self.__skipped),
            unreadable=tuple(self.__unreadable),
            unnamed_malformed=self.__unnamed_malformed,
        )

    # endregion


def generate_checksums(  # pylint: disable=too-many-arguments
    rehu_path: Path,
    *,
    coordinator: RenameCoordinator | None = None,
    algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
    only: Collection[str] | None = None,
    stale_after: timedelta | None = None,
    create_if_missing: bool = True,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    progress: ChecksumProgress | None = None,
    checkpoint: ChecksumCheckpoint | None = None,
) -> ChecksumReport:
    """(Re-)baseline ``rehu_path``'s ``.checksum`` record ([[data-model#checksums]], #203).

    See :meth:`ChecksumRun.generate` for the contract: a full call writes the content files as they
    are; a targeted call re-baselines exactly the named entries -- accepting a genuine change after a
    verify reported it -- and carries every other byte-for-byte.

    :param rehu_path: the resource's ``.rehu`` file.
    :param coordinator: the rename barrier to read through (#241), or ``None`` for a private one.
    :param algorithm: what the hashes are recorded under; :data:`~rehuco_core.DEFAULT_CHECKSUM_ALGORITHM`
        unless a setting (#242) says otherwise.
    :param only: the names to re-baseline, or ``None`` for a full baseline.
    :param stale_after: skip entries verified more recently; ``None`` re-hashes everything.
    :param create_if_missing: whether a resource with no record yet starts from an empty one -- on by
        default here, because creating the record is what a first generate is *for*.
    :param excluded_patterns: filename globs the content walk leaves out (#226).
    :param progress: told how far the run has got, in bytes.
    :param checkpoint: the run's place to stop, called between chunks and never caught.
    :returns: what the run established.
    :raises FileNotFoundError: no record and ``create_if_missing`` is off.
    :raises ChecksumRecordError: a record file this build cannot read at all.
    :raises ValueError: an algorithm this build does not ship.
    :raises OSError: the record could not be written.
    """
    return ChecksumRun(
        rehu_path,
        coordinator=coordinator,
        algorithm=algorithm,
        only=only,
        stale_after=stale_after,
        create_if_missing=create_if_missing,
        migrate_to=None,
        excluded_patterns=excluded_patterns,
        progress=progress,
        checkpoint=checkpoint,
    ).generate()


def verify_checksums(  # pylint: disable=too-many-arguments
    rehu_path: Path,
    *,
    coordinator: RenameCoordinator | None = None,
    algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
    only: Collection[str] | None = None,
    stale_after: timedelta | None = None,
    create_if_missing: bool = False,
    migrate_to: str | None = None,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    progress: ChecksumProgress | None = None,
    checkpoint: ChecksumCheckpoint | None = None,
) -> ChecksumReport:
    """Verify ``rehu_path``'s content against its ``.checksum`` record ([[data-model#checksums]], #203).

    See :meth:`ChecksumRun.verify` for the contract: recorded entries are checked under their own
    algorithms, unlisted content is adopted and reported ``unexpected``, and ``migrate_to`` moves
    matched entries onto a new algorithm from the same single read.

    :param rehu_path: the resource's ``.rehu`` file.
    :param coordinator: the rename barrier to read through (#241), or ``None`` for a private one.
    :param algorithm: what an adopted file's hash is recorded under.
    :param only: the names to check, or ``None`` for the whole record.
    :param stale_after: skip entries verified more recently -- how a sweep (#242) saves the re-read;
        ``None`` verifies everything, which is how *force* is expressed.
    :param create_if_missing: whether a resource with no record yet starts from an empty one -- off by
        default here, because verifying against a record that does not exist is usually a mistake worth
        hearing about; a sweep that means *adopt everything* switches it on.
    :param migrate_to: re-record matched entries under this algorithm, from the same read; a failed
        entry stays ``mismatched`` under its old key with the new hash discarded.
    :param excluded_patterns: filename globs deciding only which unlisted files exist to adopt (#226);
        never a verdict.
    :param progress: told how far the run has got, in bytes.
    :param checkpoint: the run's place to stop, called between chunks and never caught.
    :returns: what the run established.
    :raises FileNotFoundError: no record and ``create_if_missing`` is off.
    :raises ChecksumRecordError: a record file this build cannot read at all.
    :raises ValueError: an algorithm this build does not ship.
    :raises OSError: the record could not be re-written.
    """
    return ChecksumRun(
        rehu_path,
        coordinator=coordinator,
        algorithm=algorithm,
        only=only,
        stale_after=stale_after,
        create_if_missing=create_if_missing,
        migrate_to=migrate_to,
        excluded_patterns=excluded_patterns,
        progress=progress,
        checkpoint=checkpoint,
    ).verify()
