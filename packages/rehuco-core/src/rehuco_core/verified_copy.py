"""A record copied to another folder and proven there, and the move made from it (#339,
[[mounts-and-storage#safe-move-rename]]).

**One verified copy, three uses.** A move to another disk or share is a verified copy, then the source removed only once
the copy verified; a borrow and a return reuse the copy as it is. So this module holds the pieces and no sequence of its
own: :class:`~rehuco_core.MoveRecordJob` runs them in order, and checks between them.

- :func:`check_move_source` -- the source's record exists and covers every content file, so a check of the copy against
  it means something;
- :meth:`VerifiedCopy.copy` -- every file the record carries, written to the target, **resumable per file**: a content
  file already there whose hash matches the record is not copied again, a partial one is copied whole (byte-level
  resume is #632's);
- :meth:`VerifiedCopy.verify_target` -- the copy checked against the record, **always**: the hard rule;
- :meth:`VerifiedCopy.reconcile` -- every file no checksum covers compared with its copy, byte for byte, and copied
  again where it changed: slow work, done off the GUI thread;
- :meth:`VerifiedCopy.detach_source` -- inside the rename barrier, and so on the GUI thread: the source checked to be
  as it was reconciled, by one listing, and its ``.rehu`` and ``.checksum`` removed, so it stops being a record;
- :func:`remove_leftovers` -- the rest of the source removed, off the GUI thread again;
- :meth:`VerifiedCopy.remove_copy` -- what a cancelled copy wrote, taken away again.

What one copy wrote is kept in a :class:`CopyJournal` its job saves, so a copy stopped by a quit picks up where it was,
and a cancel removes exactly what it wrote and nothing that was there before. The journal names each entry relative to
the folder the record lands in, so it still holds after the destination root is mapped somewhere else.

**The source is followed through a rename.** The record and every file it carries are held as tracked locations
(:class:`~rehuco_core.ResourceLocation`), so a rename of the record while its copy runs moves the copy's reads with it.
"""

import filecmp
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .checksum_record import (
    CHECKSUM_FILES_KEY,
    checksum_record_path,
    load_checksum_record,
    parse_checksum_entry,
    rename_checksum_entries,
    update_checksum_record,
)
from .checksum_trust import ChecksumTrust
from .constants import CHECKSUM_RECORD_SUFFIX, EXCLUDED_FILE_PATTERNS, REHU_SUFFIX
from .content_digest import digest_content
from .content_reading import read_content_chunks
from .record_file_lock import is_lock_name
from .rehu_checksums import ChecksumCheckpoint, ChecksumProgress, ChecksumReport, verify_checksums
from .rehu_content_files import MAX_NAMED_UNREADABLE, enumerate_content_files
from .rehu_rename import RehuRenamer
from .relocation import Relocation
from .rename_coordination import RenameCoordinator, ResourceLocation
from .resource_scoping import is_directory_scoped

LOG: Final = logging.getLogger(__name__)

LAST_COPIED: Final = {CHECKSUM_RECORD_SUFFIX: 2, REHU_SUFFIX: 3}
"""The files a copy writes last, by suffix, after the content (0) and every other file (1): the ``.rehu`` is the very
last, so the copy is a record only once whole."""

Signature = tuple[int, int]
"""What a file's listing says of it: its size and its modification time, in nanoseconds."""

JOURNAL_WRITTEN_KEY: Final = "written"
JOURNAL_MADE_KEY: Final = "made"
"""The keys a :class:`CopyJournal` writes itself down under."""


class VerifiedCopyError(OSError):
    """A verified copy refused to start, or its copy did not prove out -- the source untouched either way.

    An ``OSError``, like a rename's own failures, so a caller that reports every move failure alike catches it; its
    message is the sentence a reader acts on.
    """


class LinkInRecordError(VerifiedCopyError):
    """The record holds a symbolic link or a junction, which a copy neither follows nor carries: it is not moved.

    :param link: the link found.
    """

    def __init__(self, link: str) -> None:
        super().__init__(f"{link} is a link, and a record holding one is not moved to another disk or share.")


class SourceChangedError(VerifiedCopyError):
    """The source is not as it was reconciled -- a file changed, came or went since -- so it must be reconciled again
    before it is detached. Nothing was removed."""


def name_list(names: Iterable[str]) -> str:
    """Up to :data:`~rehuco_core.rehu_content_files.MAX_NAMED_UNREADABLE` names, and a count of the rest.

    :param names: the names, in the order to show them.
    :returns: for example ``a.zip, b.zip, c.zip (and 2 more)``.
    """
    names = list(names)
    named = ", ".join(names[:MAX_NAMED_UNREADABLE])
    remaining = len(names) - MAX_NAMED_UNREADABLE
    return named if remaining <= 0 else f"{named} (and {remaining} more)"


def recorded_digests(rehu_path: Path) -> dict[str, tuple[str, str]]:
    """What ``rehu_path``'s checksum record holds a hash for.

    :param rehu_path: the resource's ``.rehu`` file.
    :returns: each recorded name with its algorithm and digest; an entry this build cannot read, or one with no hash,
        is left out.
    :raises FileNotFoundError: there is no record.
    :raises ChecksumRecordError: the record cannot be read as one.
    :raises OSError: the record file could not be read.
    """
    record = load_checksum_record(checksum_record_path(rehu_path))
    digests: dict[str, tuple[str, str]] = {}
    for raw in record[CHECKSUM_FILES_KEY]:
        entry = parse_checksum_entry(raw)
        if entry is not None and entry.algorithm is not None and entry.digest is not None:
            digests[entry.name] = (entry.algorithm, entry.digest)
    return digests


def check_move_source(
    rehu_path: Path, *, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS, create_if_missing: bool = False
) -> bool:
    """Say whether the record at ``rehu_path`` can be moved and proven, before anything is read or written (#339).

    A check after a copy or a rename can only prove the files match what the record claims, so the record has to claim
    every content file the move carries. A record that is missing, or misses files, is refused -- unless *Create
    missing checksum on verify* is on, in which case the source verify the caller runs next writes what is missing,
    from the source's own bytes.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: the globs deciding which files are content (:func:`~rehuco_core.enumerate_content_files`).
    :param create_if_missing: whether a missing record, or missing entries, may be made by the source verify.
    :returns: whether that verify has something to add -- ``True`` when the record is missing or misses a file, so the
        caller runs it even when the user's settings would skip it.
    :raises VerifiedCopyError: no record, or files the record does not cover, with creating them off.
    :raises ContentUnreachableError: part of the resource could not be listed.
    :raises ChecksumRecordError: the record cannot be read as one.
    :raises OSError: the record file could not be read.
    """
    try:
        recorded = recorded_digests(rehu_path)
    except FileNotFoundError:
        if create_if_missing:
            return True
        raise VerifiedCopyError(
            f'"{rehu_path.name}" has no checksum record to verify it against: generate its checksums first, or turn on '
            "Create missing checksum on verify."
        ) from None
    enumeration = enumerate_content_files(rehu_path, excluded_patterns)
    enumeration.require_complete()
    uncovered = [
        name
        for name in (path.relative_to(rehu_path.parent).as_posix() for path in enumeration.files)
        if name not in recorded
    ]
    if uncovered and not create_if_missing:
        raise VerifiedCopyError(
            f"The checksum record does not cover {name_list(uncovered)}, so the move could not be verified: verify "
            "the record's checksums first, or turn on Create missing checksum on verify."
        )
    return bool(uncovered)


@dataclass
class CopyJournal:
    """What one verified copy wrote, kept by its job so a stopped copy resumes and a cancelled one can be undone.

    Each entry is spelled relative to the folder the record lands in, POSIX-separated -- ``..`` for a parent the copy
    had to make -- so the journal holds wherever that folder is mapped (:class:`VerifiedCopy` spells and reads them).

    :param written: every target file the copy wrote, whole or in part.
    :param made: every target folder the copy made, the topmost first.
    """

    written: list[str] = field(default_factory=list)
    made: list[str] = field(default_factory=list)

    def wrote(self, entry: str) -> None:
        """Note a file the copy is about to write.

        :param entry: the target file, as the journal spells it.
        """
        if entry not in self.written:
            self.written.append(entry)

    def to_state(self) -> dict[str, Any]:
        """This journal as JSON primitives.

        :returns: the state.
        """
        return {JOURNAL_WRITTEN_KEY: list(self.written), JOURNAL_MADE_KEY: list(self.made)}

    @classmethod
    def from_state(cls, state: Any) -> CopyJournal:
        """A journal from what :meth:`to_state` wrote.

        :param state: the saved value; anything but the shape written reads as an empty journal.
        :returns: the journal.
        :raises ValueError: a list holds something other than text.
        """
        if not isinstance(state, dict):
            return cls()
        written = state.get(JOURNAL_WRITTEN_KEY, [])
        made = state.get(JOURNAL_MADE_KEY, [])
        if not (isinstance(written, list) and isinstance(made, list)):
            raise ValueError("A saved copy journal is not two lists.")
        if not all(isinstance(path, str) for path in [*written, *made]):
            raise ValueError("A saved copy journal names something that is not a path.")
        return cls(list(written), list(made))


@dataclass(frozen=True, slots=True)
class CarriedFile:
    """One file a record carries, where it is and where its copy goes.

    :param location: the file, followed through any rename of its record.
    :param target: where its copy goes.
    :param content: the record-relative name it is checked under, or ``None`` for one no checksum covers -- the
        ``.rehu``, its ``.checksum``, a screenshot.
    """

    location: ResourceLocation
    target: Path
    content: str | None

    @property
    def source(self) -> Path:
        """The file, where it is now."""
        return self.location.path


@dataclass(frozen=True, slots=True)
class CarriedSet:
    """Everything a record carries: its files, and for a folder record the folders inside it.

    :param pairs: the record's own rename plan (:meth:`~rehuco_core.RehuRenamer.plan`), as it was listed: its folder,
        or its file set.
    :param folders: where the copy of each folder of a folder record goes, the record's own first, a parent before
        its children.
    :param files: each file, in the order a copy writes them -- content first, the ``.rehu`` last.
    """

    pairs: tuple[tuple[Path, Path], ...]
    folders: tuple[Path, ...]
    files: tuple[CarriedFile, ...]


@dataclass(frozen=True, slots=True)
class SourceListing:
    """A record's files and folders as one listing found them -- plain paths, which no rename rewrites.

    :param record: the record's ``.rehu`` file.
    :param files: every file the record carries, with what the listing said of it.
    :param folders: a folder record's folders, its own first, a parent before its children; none for a file record.
    :param pairs: the record's own entry and where its copy is: its folder, or each of its files.
    """

    record: Path
    files: dict[str, Signature]
    folders: tuple[str, ...]
    pairs: tuple[tuple[Path, Path], ...]


def remove_leftovers(files: Iterable[str], folders: Iterable[str]) -> list[str]:
    """Remove what is left of a source whose record was detached: its files, then its folders, the deepest first.

    A file already gone is no failure; a folder that still holds something -- a file that came since, a stale lock --
    stays, and is reported.

    :param files: the source's files (:attr:`SourceListing.files`).
    :param folders: its folders, a parent before its children (:attr:`SourceListing.folders`).
    :returns: what could not be removed, as a sentence per item -- empty when the source is gone.
    """
    left: list[str] = []
    for path in files:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as error:
            left.append(f"{path} ({error.strerror or error})")
    for path in reversed(list(folders)):
        try:
            Path(path).rmdir()
        except FileNotFoundError:
            continue
        except OSError as error:
            left.append(f"{path} ({error.strerror or error})")
    for line in left:
        LOG.warning("Could not remove %s from the original after its copy verified.", line)
    return left


class VerifiedCopy:
    """One record copied into another folder under a name, and proven there ([[mounts-and-storage#safe-move-rename]]).

    Built per run and thrown away: what a run must keep between runs is in the :class:`CopyJournal` the caller hands
    each step. Reads go through the rename barrier, and the record is followed through a rename, so one that lands
    while the copy runs costs it a chunk and nothing else.

    :param source: the record's ``.rehu`` file, as it is now.
    :param into: the folder the record's own entry -- its folder, or its file set -- lands in.
    :param new_name: the record's name there: its folder's, or its files' stem.
    :param coordinator: the rename barrier the reads go through.
    :param excluded_patterns: the globs deciding which files are content.
    """

    def __init__(
        self,
        source: Path,
        into: Path,
        new_name: str,
        *,
        coordinator: RenameCoordinator,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    ) -> None:
        self.__location: Final = coordinator.track(source)
        self.__into: Final = into
        self.__new_name: Final = new_name
        self.__coordinator: Final = coordinator
        self.__excluded_patterns: Final = excluded_patterns

    @property
    def source(self) -> Path:
        """The record's ``.rehu`` file, where it is now."""
        return self.__location.path

    @property
    def target(self) -> Path:
        """Where the record's ``.rehu`` lands: inside the new folder for a folder record, renamed for a file one."""
        source = self.source
        if is_directory_scoped(source):
            return self.__into / self.__new_name / source.name
        return self.__into / (self.__new_name + source.suffix)

    def listing(self) -> SourceListing:
        """List the record's files and folders, with each file's size and date -- one listing per folder, and nothing
        read.

        :returns: the listing.
        :raises ValueError: the name is not a plain name, or a folder would land inside itself.
        :raises FileNotFoundError: the ``.rehu`` is not on disk.
        :raises LinkInRecordError: the record holds a symbolic link or a junction.
        :raises OSError: a folder of the record would not list.
        """
        source = self.source
        pairs = tuple(RehuRenamer(source, self.__new_name, into=self.__into).plan())
        files: dict[str, Signature] = {}
        if not is_directory_scoped(source):
            for path, _ in pairs:
                if path.is_symlink():
                    raise LinkInRecordError(str(path))
                stat = path.stat()
                files[str(path)] = (stat.st_size, stat.st_mtime_ns)
            return SourceListing(source, files, (), pairs)
        (top, _), *_ = pairs
        folders = [str(top)]
        pending = [str(top)]
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in sorted(entries, key=lambda entry: entry.name):
                    if entry.is_symlink() or entry.is_junction():
                        raise LinkInRecordError(entry.path)
                    if entry.is_dir():
                        folders.append(entry.path)
                        pending.append(entry.path)
                    elif not is_lock_name(entry.name):
                        stat = entry.stat()
                        files[entry.path] = (stat.st_size, stat.st_mtime_ns)
        return SourceListing(source, files, tuple(folders), pairs)

    def carried(self, listing: SourceListing | None = None) -> CarriedSet:
        """Say what the record carries, each file followed through a rename from here on.

        :param listing: the listing to say it from; taken now when ``None``.
        :returns: the set.
        :raises ValueError: see :meth:`listing`.
        :raises FileNotFoundError: see :meth:`listing`.
        :raises OSError: see :meth:`listing`.
        """
        listing = self.listing() if listing is None else listing
        source = listing.record
        content = {
            str(path): path.relative_to(source.parent).as_posix()
            for path in enumerate_content_files(source, self.__excluded_patterns).files
        }
        if is_directory_scoped(source):
            (top, copy), *_ = listing.pairs
            targets = {path: copy.joinpath(*Path(path).relative_to(top).parts) for path in listing.files}
            folders = tuple(copy.joinpath(*Path(path).relative_to(top).parts) for path in listing.folders)
        else:
            targets = {str(path): target for path, target in listing.pairs}
            folders = ()
        files = [
            CarriedFile(self.__coordinator.track(Path(path)), targets[path], content.get(path))
            for path in listing.files
        ]
        return CarriedSet(listing.pairs, folders, tuple(sorted(files, key=self.__copy_order)))

    def copy(
        self,
        journal: CopyJournal,
        *,
        progress: ChecksumProgress | None = None,
        checkpoint: ChecksumCheckpoint | None = None,
    ) -> None:
        """Write every carried file to the target, skipping a content file already there whose hash matches the record.

        :param journal: what this copy has written so far, added to as it writes -- read back by a resumed copy and by
            :meth:`remove_copy`.
        :param progress: told how far the copy has got, in bytes.
        :param checkpoint: the caller's place to stop, called between chunks and never caught.
        :raises FileExistsError: the target's place holds something this copy did not write.
        :raises OSError: a file could not be read or written.
        """
        listing = self.listing()
        carried = self.carried(listing)
        self.__check_place_is_ours(carried, journal)
        recorded = self.__recorded()
        total = sum(size for size, _ in listing.files.values())
        done = [0]

        def count(size: int) -> None:
            """Count bytes copied or found already copied, and say so."""
            done[0] += size
            if progress is not None:
                progress(done[0], total)

        count(0)
        self.__make_folders(carried, journal)
        for carried_file in carried.files:
            if self.__is_own_record(carried_file):
                self.__copy_record(carried, carried_file, journal)
                count(carried_file.source.stat().st_size)
            elif self.__already_there(carried_file, recorded, checkpoint):
                count(carried_file.source.stat().st_size)
            else:
                self.copy_file(carried_file, journal, on_chunk=count, checkpoint=checkpoint)

    def verify_target(
        self,
        *,
        trust: ChecksumTrust | None,
        algorithm: str,
        progress: ChecksumProgress | None = None,
        checkpoint: ChecksumCheckpoint | None = None,
    ) -> ChecksumReport:
        """Check the copy against the record it carried, and refuse it unless every entry matched.

        Not a verify that adopts: a file at the target the record does not list is a failure here, not an addition,
        and a missing record is one too. A clean check registers the target as verified on this machine, which a
        copy otherwise is not (#357).

        :param trust: where this machine has verified which record.
        :param algorithm: what an adopted file would be recorded under -- none is adopted, but the run asks.
        :param progress: told how far the check has got, in bytes.
        :param checkpoint: the caller's place to stop, never caught.
        :returns: what the check established.
        :raises VerifiedCopyError: an entry did not match, was missing or unreadable, or a file was not listed.
        :raises OSError: the target could not be read.
        """
        report = verify_checksums(
            self.target,
            coordinator=self.__coordinator,
            algorithm=algorithm,
            create_if_missing=False,
            seed_legacy=False,
            excluded_patterns=self.__excluded_patterns,
            trust=trust,
            progress=progress,
            checkpoint=checkpoint,
        )
        failed = sorted(name for name, status in report.statuses.items() if status != "matched")
        failed.extend(report.unreadable)
        failed.extend(report.unreadable_directories)
        if failed or report.unnamed_malformed:
            raise VerifiedCopyError(
                f"The copy at {self.target.parent} did not match its checksum record ({name_list(failed)}); "
                "the original was kept."
            )
        return report

    def reconcile(self, journal: CopyJournal, verified: Iterable[str]) -> SourceListing:
        """Bring the copy level with the source as it is now, once the copy verified -- the slow half of the move's
        last step, done off the GUI thread.

        The record is listed again. A file that is not content and differs from its copy, or is new, is copied again
        and compared, byte for byte; a content file the check did not cover stops the move with nothing removed. The
        record's own ``.checksum`` is not compared: the check has just stamped the copy's.

        :param journal: what the copy wrote; a file copied again here joins it.
        :param verified: the names the target check matched, as the copy's record spells them.
        :returns: the listing the copy now matches -- taken before anything was compared, so a file changing meanwhile
            shows against it (:meth:`detach_source`).
        :raises VerifiedCopyError: a content file appeared that the check did not cover, or a file still differs from
            its copy after being copied again.
        :raises OSError: the source could not be listed, or a file not copied.
        """
        listing = self.listing()
        carried = self.carried(listing)
        checked = set(verified)
        late = [
            item.content
            for item in carried.files
            if item.content is not None and item.target.relative_to(self.target.parent).as_posix() not in checked
        ]
        if late:
            raise VerifiedCopyError(
                f"{name_list(late)} appeared in the original while it was being moved; the original was kept."
            )
        self.__make_folders(carried, journal)
        for item in carried.files:
            if item.content is None and not self.__is_own_record(item) and not self.__same(item):
                self.copy_file(item, journal)
                if not self.__same(item):
                    raise VerifiedCopyError(f'"{item.source.name}" changed while being moved; the original was kept.')
        return listing

    def detach_source(self, reconciled: SourceListing) -> Relocation:
        """Make the source stop being a record, now that its copy is level with it -- the quick half of the move's last
        step, run inside the rename barrier.

        The source is listed once more, and must be exactly as it was reconciled: the same files, each of the same
        size and date. Then its ``.rehu`` goes, and its ``.checksum``; the rest is :func:`remove_leftovers`'.

        :param reconciled: what :meth:`reconcile` answered.
        :returns: what moved, for the barrier to tell everyone holding a path.
        :raises SourceChangedError: the source is not as it was reconciled; nothing was removed.
        :raises OSError: the source could not be listed, or its ``.rehu`` not removed -- it is then still whole.
        """
        now = self.listing()
        if (now.record, now.files, now.folders) != (reconciled.record, reconciled.files, reconciled.folders):
            raise SourceChangedError("The record changed while being moved.")
        reconciled.record.unlink()
        try:
            checksum_record_path(reconciled.record).unlink(missing_ok=True)
        except OSError:
            LOG.warning("Could not remove the checksum record of %s yet.", reconciled.record, exc_info=True)
        return Relocation(reconciled.pairs)

    def remove_copy(self, journal: CopyJournal) -> list[str]:
        """Take away what a copy wrote and made -- a cancelled copy's undo, the source untouched.

        :param journal: what the copy wrote and made.
        :returns: what could not be removed, as a sentence per item.
        """
        left: list[str] = []
        for written in reversed(journal.written):
            path = self.__place(written)
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                left.append(f"{path} ({error.strerror or error})")
        for made in reversed(journal.made):
            path = self.__place(made)
            try:
                path.rmdir()
            except FileNotFoundError:
                continue
            except OSError as error:
                left.append(f"{path} ({error.strerror or error})")
        return left

    def copy_file(
        self,
        item: CarriedFile,
        journal: CopyJournal,
        *,
        on_chunk: Callable[[int], None] | None = None,
        checkpoint: ChecksumCheckpoint | None = None,
    ) -> None:
        """Copy one file whole, keeping its modification time, its bytes flushed to the target's disk.

        :param item: the file.
        :param journal: noted before the first byte is written.
        :param on_chunk: told how many bytes each chunk held.
        :param checkpoint: called before the first chunk and after each, never caught.
        :raises OSError: the file could not be read or written.
        """
        if checkpoint is not None:
            checkpoint()
        journal.wrote(self.__entry(item.target))
        chunks = read_content_chunks(item.location, self.__coordinator)
        try:
            with item.target.open("wb") as target:
                for chunk in chunks:
                    target.write(chunk)
                    if on_chunk is not None:
                        on_chunk(len(chunk))
                    if checkpoint is not None:
                        checkpoint()
                target.flush()
                os.fsync(target.fileno())
        finally:
            chunks.close()
        stat = item.source.stat()
        os.utime(item.target, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    def __is_own_record(self, item: CarriedFile) -> bool:
        """Whether ``item`` is the record's own ``.checksum`` -- not a nested record's.

        :param item: a carried file.
        :returns: whether it is the checksum record beside the record's ``.rehu``.
        """
        return str(item.source) == str(checksum_record_path(self.source))

    def __copy_record(self, carried: CarriedSet, item: CarriedFile, journal: CopyJournal) -> None:
        """Write the record's ``.checksum`` at the target, a file record's entries renamed with its files.

        :param carried: the record's set, whose pairs say what each file is called at the target.
        :param item: the ``.checksum``.
        :param journal: noted before the record is written.
        :raises ChecksumRecordError: the record cannot be read as one.
        :raises OSError: it could not be read or written.
        """
        names = {} if is_directory_scoped(self.source) else {s.name: d.name for s, d in carried.pairs}
        record = load_checksum_record(item.source)
        journal.wrote(self.__entry(item.target))
        update_checksum_record(item.target, lambda _: rename_checksum_entries(record, names) or record)

    def __recorded(self) -> dict[str, tuple[str, str]]:
        """The source record's hashes, or none when it has no record yet -- nothing is then skipped."""
        try:
            return recorded_digests(self.source)
        except FileNotFoundError:
            return {}

    def __already_there(
        self, item: CarriedFile, recorded: dict[str, tuple[str, str]], checkpoint: ChecksumCheckpoint | None
    ) -> bool:
        """Whether a content file's copy is already at the target, whole: its hash is the one the record holds.

        :param item: the file.
        :param recorded: the record's hashes.
        :param checkpoint: called between chunks of the hash.
        :returns: ``False`` for a file that is not content, not recorded, or not at the target.
        """
        entry = None if item.content is None else recorded.get(item.content)
        if entry is None or not item.target.is_file():
            return False
        algorithm, digest = entry
        location = self.__coordinator.track(item.target)
        return digest_content(location, (algorithm,), self.__coordinator, checkpoint=checkpoint)[0] == digest

    def __check_place_is_ours(self, carried: CarriedSet, journal: CopyJournal) -> None:
        """Refuse a target place that holds anything a run of this copy did not put there.

        :param carried: the record's set.
        :param journal: what this copy wrote and made.
        :raises FileExistsError: the record's own entry is at the target, and this copy never wrote or made it.
        """
        ours = set(journal.written) | set(journal.made)
        for _, target in carried.pairs:
            if target.exists() and self.__entry(target) not in ours:
                raise FileExistsError(f'"{target.name}" already exists in {target.parent}.')

    def __make_folders(self, carried: CarriedSet, journal: CopyJournal) -> None:
        """Make the target's folders: the missing parents of the record's own entry, and a folder record's own tree.

        :param carried: the record's set.
        :param journal: each folder made joins it, the topmost first.
        :raises OSError: a folder could not be made.
        """
        (_, own), *_ = carried.pairs
        missing: list[Path] = []
        folder = own.parent
        while not folder.exists() and folder != folder.parent:
            missing.append(folder)
            folder = folder.parent
        for path in [*reversed(missing), *carried.folders]:
            if not path.exists():
                path.mkdir()
                journal.made.append(self.__entry(path))

    def __entry(self, path: Path) -> str:
        """A target path as the journal spells it: relative to the folder the record lands in.

        :param path: a file or folder the copy wrote or made.
        :returns: the entry.
        """
        return Path(os.path.relpath(path, self.__into)).as_posix()

    def __place(self, entry: str) -> Path:
        """Where a journal entry is, under the folder the record lands in as it is mapped now.

        :param entry: the entry, as :meth:`__entry` spelled it.
        :returns: the path.
        """
        return Path(os.path.normpath(self.__into / entry))

    @staticmethod
    def __same(item: CarriedFile) -> bool:
        """Whether a file that is not content has a copy with the same bytes.

        :param item: the file.
        :returns: ``False`` too when the copy is not there.
        """
        return item.target.is_file() and filecmp.cmp(item.source, item.target, shallow=False)

    @staticmethod
    def __copy_order(item: CarriedFile) -> tuple[int, str]:
        """Content first, then other files, then the ``.checksum``, then the ``.rehu``: the copy is a record only once
        whole."""
        if item.content is not None:
            return 0, str(item.source)
        return LAST_COPIED.get(item.source.suffix.lower(), 1), str(item.source)
