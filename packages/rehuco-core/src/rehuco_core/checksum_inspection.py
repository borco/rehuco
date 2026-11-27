"""Check a resource's ``.checksum`` record without writing anything ([[data-model#checksums]], #715).

:func:`~rehuco_core.verify_checksums` is a run that *maintains* the record: it dates every entry, adopts the files
the record does not list, prunes and hands over claims, seeds a record from a legacy manifest, tells the trust store
and writes the record back. A command line asking *does this disk still match?* wants none of that -- a share the app
is also using must see nothing of the run, and a read-only disk must be checkable -- so this is the other
operation: it reads the record, reads the files it lists, and answers in the same :class:`~rehuco_core.ChecksumReport`
a verify does, so the words a summary uses are one set (:func:`~rehuco_core.checksum_report_summary`).

**The recorded algorithm decides the verdict**, and hashing goes through
:func:`~rehuco_core.content_digest.digest_content`, so a file's hash here is the one a verify computes. What differs
is what is *done* with the answer: nothing is recorded, no manifest is looked for, and an entry the coverage rule
would prune or hand to another record is checked like any other, since a read that edits nothing has no business
deciding whose claim it is.

**A file with no checksum** is a content file the record does not list, or lists with no hash (which reads as not
listed, #467). :func:`~rehuco_core.enumerate_content_files` answers which files are content, so the app and a command
line agree on what counts.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from .checksum_record import (
    CHECKSUM_FILES_KEY,
    ChecksumStatus,
    checksum_entry_name,
    checksum_record_path,
    load_checksum_record,
    parse_checksum_entry,
)
from .constants import EXCLUDED_FILE_PATTERNS
from .content_digest import digest_content
from .rehu_checksums import ChecksumCheckpoint, ChecksumProgress, ChecksumReport
from .rehu_content_files import enumerate_content_files
from .rename_coordination import RenameCoordinator

CLEAN_FILE_STATUSES: Final = frozenset({"matched", "present"})
"""The verdicts of one file that are not a finding about it."""


@dataclass(frozen=True, slots=True)
class ChecksumInspection:
    """What one read-only check established.

    :param report: the verdicts, in a verify's own shape: per name ``matched``, ``mismatched`` or ``missing`` (or
        ``present``, in a check that hashed nothing), ``malformed`` for an entry with a readable name this build cannot
        read, and the names it could not read.
    :param without_checksum: the content files the record does not cover, sorted; empty unless asked for.
    """

    report: ChecksumReport
    without_checksum: tuple[str, ...] = ()

    @property
    def findings(self) -> tuple[str, ...]:
        """The names with something to say: a verdict that is not a clean one, or a file that could not be read.

        :returns: the names, in the order the record lists them.
        """
        found = [name for name, status in self.report.statuses.items() if status not in CLEAN_FILE_STATUSES]
        found.extend(name for name in self.report.unreadable if name not in found)
        return tuple(found)


# one run is built, asked once and dropped: the state it keeps is the answer growing, and it has the one question
class ChecksumInspectionRun:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """One read-only check over one resource's record (#715).

    Built per call by :func:`inspect_checksums` and thrown away.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: the junk globs the content walk leaves out.
    :param hash_files: whether to read the files, or only check they exist.
    :param list_without_checksum: whether to name the content files the record does not cover.
    :param progress: told how far the run has got, in bytes.
    :param on_file: told the name of each file as its check starts.
    :param checkpoint: the run's place to stop, never caught here.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        rehu_path: Path,
        *,
        excluded_patterns: tuple[str, ...],
        hash_files: bool,
        list_without_checksum: bool,
        progress: ChecksumProgress | None,
        on_file: Callable[[str], None] | None,
        checkpoint: ChecksumCheckpoint | None,
    ) -> None:
        self.__rehu_path: Final = rehu_path
        self.__excluded_patterns: Final = excluded_patterns
        self.__hash_files: Final = hash_files
        self.__list_without_checksum: Final = list_without_checksum
        self.__progress: Final = progress
        self.__on_file: Final = on_file
        self.__checkpoint: Final = checkpoint
        self.__coordinator: Final = RenameCoordinator()
        self.__statuses: Final[dict[str, ChecksumStatus]] = {}
        self.__unreadable: Final[list[str]] = []
        self.__unnamed_malformed = 0
        self.__done = 0
        self.__total = 0

    def inspect(self) -> ChecksumInspection:
        """Read the record, check what it lists, and say what is not covered when asked.

        :returns: what the run established.
        :raises FileNotFoundError: the resource has no record.
        :raises ChecksumRecordError: a record this build cannot read at all.
        :raises ContentUnreachableError: the resource's directory would not list, with ``list_without_checksum``.
        :raises OSError: the record could not be read.
        """
        record = load_checksum_record(checksum_record_path(self.__rehu_path))
        listed = self.__parsed(record[CHECKSUM_FILES_KEY])
        self.__plan(listed)
        for name, algorithm, expected in listed:
            self.__check(name, algorithm, expected)
        without: tuple[str, ...] = ()
        unreadable_directories: tuple[str, ...] = ()
        if self.__list_without_checksum:
            enumeration = enumerate_content_files(self.__rehu_path, self.__excluded_patterns)
            enumeration.require_reachable()
            # an entry this build cannot read still covers its file: it is a claim, reported as one
            names = {*self.__statuses, *self.__unreadable}
            found = (path.relative_to(enumeration.directory).as_posix() for path in enumeration.files)
            without = tuple(sorted(name for name in found if name not in names))
            unreadable_directories = tuple(
                branch.relative_to(enumeration.directory).as_posix() for branch in enumeration.unreadable
            )
        report = ChecksumReport(
            statuses=dict(self.__statuses),
            unreadable=tuple(self.__unreadable),
            unnamed_malformed=self.__unnamed_malformed,
            unreadable_directories=unreadable_directories,
        )
        return ChecksumInspection(report, without)

    def __parsed(self, raw_entries: list[object]) -> list[tuple[str, str, str]]:
        """The entries that claim a hash, the first of each name.

        An entry this build cannot read is reported ``malformed`` on the way, and one with no hash is left out: it
        reads as not listed (#467).

        :param raw_entries: the record's entries as loaded.
        :returns: each one's name, algorithm and hash, in the record's order.
        """
        claims: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for raw in raw_entries:
            entry = parse_checksum_entry(raw)
            name = checksum_entry_name(raw)
            if name is None:
                self.__unnamed_malformed += 1
            elif name not in seen:
                seen.add(name)
                if entry is None:
                    self.__statuses[name] = "malformed"
                elif entry.algorithm is not None and entry.digest is not None:
                    claims.append((name, entry.algorithm, entry.digest))
        return claims

    def __plan(self, claims: list[tuple[str, str, str]]) -> None:
        """Add up what the run is about to read, and say so.

        :param claims: the entries to check.
        """
        if not self.__hash_files or self.__progress is None:
            return
        for name, _, _ in claims:
            try:
                self.__total += self.__path(name).stat().st_size
            except OSError:
                continue
        self.__progress(0, self.__total)

    def __path(self, name: str) -> Path:
        """Where a listed file is.

        :param name: its record-relative name.
        :returns: its path, beside the ``.rehu``.
        """
        return self.__rehu_path.parent / PurePosixPath(name)

    def __check(self, name: str, algorithm: str, expected: str) -> None:
        """Check one listed file, and record the answer in the run, never in the record.

        :param name: the file's record-relative name.
        :param algorithm: what the record's hash is under.
        :param expected: the record's hash.
        """
        if self.__on_file is not None:
            self.__on_file(name)
        path = self.__path(name)
        try:
            if not self.__hash_files:
                os.stat(path)
                self.__statuses[name] = "present"
                return
            digest = digest_content(
                self.__coordinator.track(path),
                (algorithm,),
                self.__coordinator,
                on_chunk=self.__count,
                checkpoint=self.__checkpoint,
            )[0]
        except FileNotFoundError:
            self.__statuses[name] = "missing"
        except OSError:
            self.__unreadable.append(name)
        else:
            self.__statuses[name] = "matched" if digest.lower() == expected.lower() else "mismatched"

    def __count(self, size: int) -> None:
        """Count one chunk read, and say how far the run has got.

        :param size: the chunk's bytes.
        """
        self.__done += size
        if self.__progress is not None:
            self.__progress(self.__done, self.__total)


def inspect_checksums(  # pylint: disable=too-many-arguments
    rehu_path: Path,
    *,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    hash_files: bool = True,
    list_without_checksum: bool = False,
    progress: ChecksumProgress | None = None,
    on_file: Callable[[str], None] | None = None,
    checkpoint: ChecksumCheckpoint | None = None,
) -> ChecksumInspection:
    """Check ``rehu_path``'s content against its ``.checksum`` record, writing nothing (#715).

    See :class:`ChecksumInspectionRun`.

    :param rehu_path: the resource's ``.rehu`` file; the record is its same-stem ``.checksum``, whether or not the
        ``.rehu`` itself is there.
    :param excluded_patterns: the junk globs the content walk leaves out -- consulted only to say which files have no
        checksum.
    :param hash_files: ``False`` checks only that each listed file exists.
    :param list_without_checksum: whether to name the content files the record does not cover.
    :param progress: told how far the run has got, in bytes; never told when nothing is hashed.
    :param on_file: told the name of each file as its check starts.
    :param checkpoint: the run's place to stop, called between chunks and never caught.
    :returns: what the run established.
    :raises FileNotFoundError: the resource has no record.
    :raises ChecksumRecordError: a record this build cannot read at all.
    :raises ContentUnreachableError: the resource's directory would not list, with ``list_without_checksum``.
    :raises OSError: the record could not be read.
    """
    return ChecksumInspectionRun(
        rehu_path,
        excluded_patterns=excluded_patterns,
        hash_files=hash_files,
        list_without_checksum=list_without_checksum,
        progress=progress,
        on_file=on_file,
        checkpoint=checkpoint,
    ).inspect()
