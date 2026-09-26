"""One directory of a resource's folder as table rows ([[plugins#files-subdock]], #266).

**The rows come from a listing *and* from the ``.checksum`` record**, merged here, the same way
:mod:`~rehuco_agent.documents.checksum_rows` merges that record with a content walk. The difference is
the question: that surface answers *what does the record say about this resource*, over every content
file at any depth; this one answers *what is in this folder*, one level, including everything the record
has nothing to say about -- the record itself, its screenshots, another resource's files, the junk a
share leaves behind.

**What each file is comes from core** (:mod:`rehuco_core.rehu_file_kinds`), which applies the content
walk's own rules a directory at a time. Nothing here re-decides what a screenshot or a backup is; this
module turns those names into a row, a glyph and an enabled state.

**The checksum column reports what this record claims, and nothing else.** A file another record covers
gets no verdict at all, because this record makes no claim about it -- reading the neighbour's record to
answer for it would make a glyph mean *somebody verified this*, which is not what the column is for. And
the fresh/stale split is :func:`~rehuco_core.is_checksum_fresh`'s, so a green glyph means exactly *Verify
Old would skip this file* rather than an opinion formed here (#266).

**Reading it touches the filesystem**, on a catalog that lives on an SMB mount
([[packaging-deployment#ts230-as-nas]]), so it never happens on the GUI thread: :class:`FilesRowsLoader`
runs a :class:`FilesRowsReader` on the global pool and delivers the answer back through a queued signal --
one ``scandir`` and one small JSON read, neither of which is slow and either of which blocks for the
share timeout when the mount is away.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, override

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
)
from rehuco_core import (
    CHECKSUM_FILES_KEY,
    DEFAULT_CHECKSUM_TRUST,
    MATCHED_STATUS,
    TRUST_NOT_TRACKED,
    ChecksumEntry,
    ChecksumRecordError,
    DirectoryClassifier,
    DirectoryEntry,
    FileKind,
    FileType,
    ScreenshotNamePattern,
    checksum_record_path,
    is_checksum_fresh,
    load_checksum_record,
    natural_sort_key,
    parse_checksum_entry,
)

from ..fields.widgets import SizeMeasurementEdit

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method; the persistent form arrives from a view holding onto an index."""

PARENT_ROW_NAME: Final = ".."
"""What the row leading out of a subdirectory is called.

The shell's own spelling, and deliberately not a *Go up* button only: a reader who has walked into a
subdirectory looks for it in the listing, and the toolbar's up action is the same act reachable from
somewhere else."""

NAME_COLUMN: Final = 0
CHECKSUM_COLUMN: Final = 1
KIND_COLUMN: Final = 2
SIZE_COLUMN: Final = 3
MODIFIED_COLUMN: Final = 4
COLUMN_COUNT: Final = 5
COLUMN_TITLES: Final = ("Name", "", "Kind", "Size", "Modified")
"""The five columns the table draws.

The checksum column's title is **empty** on purpose: it holds one 16px glyph, and a word above it would
set the column's width to the word rather than to the glyph. What each glyph means is on its tooltip,
which is what an icon-only column owes a reader who has not learnt them yet -- the same arrangement the
task queue's State column makes (#248)."""

DATE_FORMAT: Final = "%Y-%m-%d %H:%M"
"""How a modification time is drawn: **local time**, to the minute -- the same spelling the checksum
table's *Checked* column uses, since the two sit side by side in one document's docks."""


class FileChecksumState(StrEnum):
    """What this resource's record says about one file, as the column draws it (#266).

    Resolved during the read so nothing downstream reasons about recorded statuses: the record's
    vocabulary is [[data-model#checksums]]', and a surface that re-read it would be a second place for
    *what counts as verified* to be decided.
    """

    NONE = "none"
    """Nothing to say: the record itself, a sidecar, a directory, or content another record covers.
    Drawn as an **empty cell** -- there is no claim here, which is different from a claim of ignorance."""

    MISSING = "missing"
    """Content this record holds no hash for -- whether because the resource has no ``.checksum`` at all
    or because that record skips this file. Deliberately one state rather than two: both are *nothing is
    recorded about these bytes*, and the remedy for both is the same generate."""

    OK = "ok"
    """Hashed, matched, and checked recently enough that a *Verify Old* would skip it."""

    BAD = "bad"
    """Hashed recently and **did not** match."""

    OLD_OK = "old_ok"
    """Matched when it was last checked, but that was long enough ago that a check would run again."""

    OLD_BAD = "old_bad"
    """Did not match when it was last checked, and is equally due a re-check. The pair with
    :data:`OLD_OK` is what makes the column say *a fresh check would tell you something* rather than
    conflating never-checked with checked-long-ago."""

    UNEXPECTED = "unexpected"
    """The record's entry for this file rests at [[data-model#checksums]]'s ``unexpected`` -- a report
    state rather than a resting one, ordinarily rewritten to ``matched`` the moment a sweep adopts the
    file. An entry actually resting here was written by something other than this build's own runs, and
    is rare enough to be worth telling apart from a genuine mismatch (#303). Carries no ``verified``
    stamp worth aging, so there is no ``old_`` pair."""

    MALFORMED = "malformed"
    """The entry's hash sits under a key this build cannot read (#303). Distinct from
    ``unexpected``/``mismatched``: this build has made **no claim at all** about the bytes and never
    re-hashes them -- drawing it as a mismatch would assert a check that never happened, and drawing it
    as :data:`MISSING` would invite a generate that overwrites a neighbour's entry. Never actually
    written by this build ([[data-model#checksums]]), so an entry resting here came from elsewhere.
    Carries no ``verified`` stamp either, so there is no ``old_`` pair."""


UNEXPECTED_STATUS: Final = "unexpected"
MALFORMED_STATUS: Final = "malformed"
"""The two raw record statuses :func:`checksum_state_for` resolves before falling back to the
matched/fresh split -- mirroring :mod:`~rehuco_agent.documents.checksum_rows`'s own
:data:`~rehuco_agent.documents.checksum_rows.MISSING_STATUS`."""

CHECKSUM_STATE_ICONS: Final[dict[FileChecksumState, str]] = {
    FileChecksumState.MISSING: ":/icons/checksum_missing.svg",
    FileChecksumState.OK: ":/icons/checksum_ok.svg",
    FileChecksumState.BAD: ":/icons/checksum_bad.svg",
    FileChecksumState.OLD_OK: ":/icons/checksum_old_ok.svg",
    FileChecksumState.OLD_BAD: ":/icons/checksum_old_bad.svg",
    FileChecksumState.UNEXPECTED: ":/icons/checksum_unexpected.svg",
    FileChecksumState.MALFORMED: ":/icons/checksum_malformed.svg",
}
""":data:`FileChecksumState.NONE` is absent rather than mapped to a blank glyph -- an empty cell is the
absence of a drawing, not a drawing of nothing.

Shared by the file browser and the checksum dock (#303): one entry resolves to one state
(:func:`checksum_state_for`), so a file's verdict reads the same glyph wherever it is drawn."""

CHECKSUM_STATE_TOOLTIPS: Final[dict[FileChecksumState, str]] = {
    FileChecksumState.MISSING: "No checksum recorded for this file.",
    FileChecksumState.OK: "Checksum matched, checked recently.",
    FileChecksumState.BAD: "Checksum did not match when it was last checked.",
    FileChecksumState.OLD_OK: "Checksum matched, but the check is old.",
    FileChecksumState.OLD_BAD: "Checksum did not match, and the check is old.",
    FileChecksumState.UNEXPECTED: "Found on disk with no recorded hash, and reported rather than adopted.",
    FileChecksumState.MALFORMED: "This entry's hash is under a key this build cannot read.",
}
"""What each glyph means, in a sentence -- what makes an icon-only column readable on first meeting."""

OLD_CHECKSUM_STATES: Final = frozenset({FileChecksumState.OLD_OK, FileChecksumState.OLD_BAD})
"""The pair a location can be the reason for -- only these two carry a ``verified`` stamp worth aging
against a location's trust (#358)."""

UNTRUSTED_LOCATION_TOOLTIP: Final = "Not yet verified at this location."
"""What an :data:`~FileChecksumState.OLD_OK`/:data:`~FileChecksumState.OLD_BAD` row says instead of its
usual :data:`CHECKSUM_STATE_TOOLTIPS` entry when :func:`checksum_verdict_for` says the *location*, not the
check's age, is why a fresh run would not skip it (#358)."""

FILE_TYPE_ICONS: Final[dict[FileType, str]] = {
    FileType.DIRECTORY: ":/icons/file_browser_folder.svg",
    FileType.RECORD: ":/icons/file_browser_rehu.svg",
    FileType.MANIFEST: ":/icons/file_browser_checksum.svg",
    FileType.BACKUP: ":/icons/file_browser_backup.svg",
    FileType.IMAGE: ":/icons/file_browser_image.svg",
    FileType.VIDEO: ":/icons/file_browser_video.svg",
    FileType.AUDIO: ":/icons/file_browser_audio.svg",
    FileType.ARCHIVE: ":/icons/file_browser_archive.svg",
    FileType.GENERIC: ":/icons/file_browser_generic.svg",
}
"""One glyph per shape, and all nine are present -- what a reader picks a video out of two hundred files
by. The **role** a row plays is the Kind column's to say, not this glyph's (#266)."""

KIND_LABELS: Final[dict[FileKind, str]] = {
    FileKind.OWN_RECORD: "this resource",
    FileKind.OWN_SCREENSHOT: "screenshot",
    FileKind.OWN_MANIFEST: "checksums",
    FileKind.FOREIGN_RECORD: "other resource",
    FileKind.FOREIGN_SIDECAR: "other resource's",
    FileKind.FOREIGN_CONTENT: "other resource's",
    FileKind.CONVERSION_BACKUP: "backup",
    FileKind.EXCLUDED: "ignored",
    FileKind.CONTENT: "content",
    FileKind.DIRECTORY: "folder",
}
"""What the Kind column says -- what the file is **to this resource**.

Plain phrases rather than the enum's own names: the column is read by someone looking at their own
folder, and *other resource's* covers a neighbour's screenshot and a neighbour's content alike, because
the only thing this resource has to say about either is that it is not its."""

INTERACTIVE_KINDS: Final = frozenset(
    {
        FileKind.OWN_SCREENSHOT,
        FileKind.OWN_MANIFEST,
        FileKind.CONVERSION_BACKUP,
        FileKind.EXCLUDED,
        FileKind.CONTENT,
        FileKind.FOREIGN_RECORD,
    }
)
"""Which kinds a reader can act on, and therefore which rows are drawn enabled (#266).

The three that are **not** here are each a deliberate refusal. :data:`~FileKind.OWN_RECORD` is the
document already on screen -- opening a second view of it is the one thing a double-click must not do.
A foreign record's sidecar and a foreign record's content belong to a resource this document cannot
speak for: its screenshots are curated in *its* images dock and its content is covered by *its*
checksums, so there is nothing here to do with either but see that it is there. A
:data:`~FileKind.DIRECTORY` is decided per listing rather than per kind
(:attr:`FilesRows.subdirectories_navigable`), which is why it is absent too."""


# a row's data, one field per cell plus the two answers a cell is not -- where it points and whether it
# can be acted on; there is no grouping of these that is not just a smaller bag inside a row
@dataclass(frozen=True, slots=True)
class FileRow:  # pylint: disable=too-many-instance-attributes
    """One entry of the browsed directory, as the table shows it (#266).

    :param name: the entry's file name, or :data:`PARENT_ROW_NAME` for the row leading out.
    :param path: where it points -- the entry itself, or the parent directory for the ``..`` row.
    :param kind: what it is to this resource.
    :param file_type: what it is by shape, which picks its glyph.
    :param checksum_state: what this resource's record says about it.
    :param untrusted_location: whether an :data:`~FileChecksumState.OLD_OK`/:data:`~FileChecksumState.OLD_BAD`
        ``checksum_state`` is old because of this record's *location* rather than the check's age (#358).
    :param size: its size in bytes, or ``None`` for a directory and for an entry that would not
        ``stat``.
    :param modified: when it last changed, or ``None`` for the same reasons.
    :param enabled: whether a reader can act on this row at all. Held rather than recomputed from
        ``kind``, because a directory's answer is the *listing*'s (#254).
    """

    name: str
    path: Path
    kind: FileKind
    file_type: FileType
    checksum_state: FileChecksumState = FileChecksumState.NONE
    untrusted_location: bool = False
    size: int | None = None
    modified: float | None = None
    enabled: bool = True

    @property
    def is_directory(self) -> bool:
        """Whether activating this row walks into a directory -- a subdirectory, or ``..``."""
        return self.kind is FileKind.DIRECTORY

    @property
    def is_parent(self) -> bool:
        """Whether this is the synthesized ``..`` row rather than something in the folder.

        Asked here rather than compared at each place that cares -- the Kind cell, the sort group and
        the glyph the delegate picks -- so the identity of the way-out row is decided once."""
        return self.name == PARENT_ROW_NAME


@dataclass(frozen=True, slots=True)
class FilesRows:
    """What one read of one directory established (#266).

    :param directory: the directory that was read.
    :param rows: its rows, unsorted -- the view sorts, and a read that imposed an order would fight it.
    :param reachable: whether the directory listed at all. **Empty and away are not the same answer**
        (#245): drawing an empty table over an offline mount
        ([[mounts-and-storage#offline-mounts]]) would say this resource's folder is empty.
    :param at_root: whether this is the resource's own directory, which is as far up as the browser
        goes -- what hides the ``..`` row and greys the up action.
    :param subdirectories_navigable: whether the subdirectories here may be entered. ``False`` where a
        *foreign* directory-scoped record sits in this listing: everything beside it is that resource's
        wholesale (#254), so the way in is to open that record, which is exactly the row offered.
    :param foreign_record: the name of the foreign directory-scoped record covering this directory, or
        ``""``. What :attr:`subdirectories_navigable` is ``False`` *because of*, so the surface can name
        it rather than guessing at which of several foreign records owns the folders.
    :param record_error: why this resource's ``.checksum`` could not be read, when that is what
        happened. The listing is still drawn -- the folder is the folder -- with every checksum cell
        blank, which is honest: this build knows nothing about any of them.
    """

    directory: Path
    rows: tuple[FileRow, ...] = ()
    reachable: bool = True
    at_root: bool = True
    subdirectories_navigable: bool = True
    foreign_record: str = ""
    record_error: str = ""


def checksum_state_for(
    entry: ChecksumEntry,
    stale_after: timedelta,
    now: datetime,
    trusted_since: datetime | None = TRUST_NOT_TRACKED,
) -> FileChecksumState:
    """What one record entry says about a file, resolved to the one glyph state it draws (#266, #303).

    Shared by the file browser and the checksum dock, so an entry's verdict cannot read one way in one
    dock and another way in the other -- there is nothing here for either surface to decide on its own.

    :param entry: the parsed record entry.
    :param stale_after: the staleness window a run would use, so *fresh* here means what it means there.
    :param now: the instant to measure freshness against, so every entry in one read is judged against
        one moment.
    :param trusted_since: when this machine began trusting the record's current location
        (:meth:`~rehuco_core.ChecksumTrust.trusted_since`, #358); the untracked default keeps age the
        only gate, matching every caller with no trust source of its own.
    :returns: the state.
    """
    if entry.status == UNEXPECTED_STATUS:
        return FileChecksumState.UNEXPECTED
    if entry.status == MALFORMED_STATUS:
        return FileChecksumState.MALFORMED
    matched = entry.status == MATCHED_STATUS
    if is_checksum_fresh(entry, stale_after, now, trusted_since):
        return FileChecksumState.OK if matched else FileChecksumState.BAD
    return FileChecksumState.OLD_OK if matched else FileChecksumState.OLD_BAD


def checksum_verdict_for(
    entry: ChecksumEntry,
    stale_after: timedelta,
    now: datetime,
    trusted_since: datetime | None = TRUST_NOT_TRACKED,
) -> tuple[FileChecksumState, bool]:
    """An entry's glyph state, and whether it is old because of *where* its record is rather than *when*
    it was last checked (#358).

    The second answer is defined by what it means, not by which input produced it: **age alone would call
    this entry current, and trust here does not** -- so a dateless entry, or one whose check is simply old,
    is old for the ordinary reason at any location, and a report-state entry is never old at all. Kept as
    a flag beside the state rather than folded into a third glyph state: the record's verdict (matched or
    not) is one axis, and *why* a check would run again is a second one that only the tooltip says.

    One resolver for both docks, the same reason :func:`checksum_state_for` is: computed once, here, so
    neither table has to re-derive the invariant that the flag only ever accompanies an ``old_`` state.

    :param entry: the parsed record entry.
    :param stale_after: the staleness window a run would use.
    :param now: the instant to measure freshness against.
    :param trusted_since: when this machine began trusting the record's current location.
    :returns: the state, and whether the location is the one reason it is not current.
    """
    state = checksum_state_for(entry, stale_after, now, trusted_since)
    untrusted_location = state in OLD_CHECKSUM_STATES and is_checksum_fresh(entry, stale_after, now)
    return state, untrusted_location


def checksum_tooltip_for(state: FileChecksumState, untrusted_location: bool) -> str | None:
    """What the checksum glyph says on hover, in both docks (#358).

    :param state: the resolved state.
    :param untrusted_location: :func:`checksum_verdict_for`'s second answer.
    :returns: the sentence; ``None`` for :data:`FileChecksumState.NONE`, which draws nothing.
    """
    if untrusted_location:
        return UNTRUSTED_LOCATION_TOOLTIP
    return CHECKSUM_STATE_TOOLTIPS.get(state)


class FileChecksumStates:
    """This resource's ``.checksum`` record, asked one filename at a time (#266).

    Built once per read from the record on disk, so a directory of two hundred files costs one JSON read
    rather than two hundred. The names it is keyed by are record-relative and POSIX-separated -- what
    :func:`~rehuco_core.checksum_entry_name` writes -- so a subdirectory's rows look themselves up as
    ``sub/movie.mp4``.

    :param entries: the recorded states by name, already resolved, each paired with whether it is old
        because of its location rather than its age (:func:`checksum_verdict_for`, #358).
    :param error: why the record could not be read, or ``""``.
    """

    def __init__(self, entries: dict[str, tuple[FileChecksumState, bool]], error: str = "") -> None:
        self.__entries: Final = entries
        self.__error: Final = error

    @property
    def error(self) -> str:
        """Why the record could not be read, or ``""`` when it was read (or simply is not there)."""
        return self.__error

    def state_for(self, name: str, kind: FileKind) -> FileChecksumState:
        """What the record says about one entry.

        :param name: the entry's record-relative, POSIX-separated name.
        :param kind: what the entry is to this resource -- only content has a verdict to carry.
        :returns: the state; :data:`FileChecksumState.NONE` for anything that is not this resource's own
            content, and for everything at all when the record could not be read.
        """
        if self.__error or kind is not FileKind.CONTENT:
            return FileChecksumState.NONE
        return self.__entries.get(name, (FileChecksumState.MISSING, False))[0]

    def untrusted_location_for(self, name: str, kind: FileKind) -> bool:
        """Whether the record says this entry is old because of its location rather than its age (#358).

        :param name: the entry's record-relative, POSIX-separated name.
        :param kind: what the entry is to this resource -- only content has a verdict to carry.
        :returns: ``False`` for anything :meth:`state_for` would answer :data:`FileChecksumState.NONE`
            or :data:`FileChecksumState.MISSING` for.
        """
        if self.__error or kind is not FileKind.CONTENT:
            return False
        return self.__entries.get(name, (FileChecksumState.MISSING, False))[1]

    @staticmethod
    def read(rehu_path: Path, stale_after: timedelta, now: datetime) -> FileChecksumStates:
        """Read ``rehu_path``'s record and resolve every entry to a state.

        A record that is simply **not there** is not an error: the resource has never been checksummed,
        and every content row saying so is the honest reading -- and the one that makes the dock worth
        opening on a fresh import.

        :param rehu_path: the resource's record.
        :param stale_after: the staleness window a run would use, so *fresh* here means what it means
            there.
        :param now: the instant to measure freshness against, so every row in one read is judged
            against one moment.
        :returns: the resolved states.
        """
        try:
            record = load_checksum_record(checksum_record_path(rehu_path))
        except FileNotFoundError:
            return FileChecksumStates({})
        except (OSError, ChecksumRecordError) as error:
            return FileChecksumStates({}, str(error))
        # one location for the whole record, asked once rather than per entry (#358)
        trusted_since = DEFAULT_CHECKSUM_TRUST.trusted_since(rehu_path)
        states: dict[str, tuple[FileChecksumState, bool]] = {}
        for raw in record[CHECKSUM_FILES_KEY]:
            entry = parse_checksum_entry(raw)
            if entry is None:
                # an entry this build cannot read says nothing about the file, which leaves the row at
                # MISSING -- the same thing a record with no entry for it says, and equally true
                continue
            states[entry.name] = checksum_verdict_for(entry, stale_after, now, trusted_since)
        return FileChecksumStates(states)


# one public method is the whole of it -- read a directory -- and what it is built with is the rest
# pylint: disable-next=too-few-public-methods
class FilesRowsReader:
    """Reads the directories of one resource's folder into rows (#266).

    Held for a browser's lifetime rather than built per read: the screenshot patterns compile once
    (:class:`~rehuco_core.DirectoryClassifier`), and walking into a subdirectory and back out is the
    ordinary case here rather than a rarity.

    :param rehu_path: the resource's record, whose directory is the root the browser is confined to.
    :param excluded_patterns: the filename globs the content walk leaves out (#226), resolved by the
        caller the way every other core call takes them.
    :param screenshot_name_patterns: the naming rules a legacy screenshot is recognized by (#287),
        resolved by the caller the same way.
    :param stale_after: the staleness window a checksum run would use, so *fresh* here means what it
        means there.
    """

    def __init__(
        self,
        rehu_path: Path,
        excluded_patterns: tuple[str, ...],
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...],
        stale_after: timedelta,
    ) -> None:
        self.__rehu_path: Final = rehu_path
        self.__stale_after: Final = stale_after
        self.__classifier: Final = DirectoryClassifier(rehu_path, excluded_patterns, screenshot_name_patterns)

    def read(self, directory: Path, now: datetime) -> FilesRows:
        """Read one directory into rows.

        Called on a worker thread, so it touches no widget and no ``QObject`` -- a plain filesystem read
        answering a plain value, the shape
        :class:`~rehuco_agent.documents.checksum_rows.ChecksumRowsLoader` established for the checksum
        table.

        :param directory: the directory to list -- the root, or one under it.
        :param now: the instant freshness is measured against, so every row of one read is judged
            against one moment.
        :returns: the rows, and what the listing itself established.
        """
        root = self.__rehu_path.parent
        at_root = directory == root
        listing = self.__classifier.classify(directory)
        if not listing.reachable:
            return FilesRows(directory, reachable=False, at_root=at_root)
        states = FileChecksumStates.read(self.__rehu_path, self.__stale_after, now)
        navigable = listing.foreign_directory_record is None
        rows: list[FileRow] = []
        if not at_root:
            rows.append(
                FileRow(
                    name=PARENT_ROW_NAME,
                    path=directory.parent,
                    kind=FileKind.DIRECTORY,
                    file_type=FileType.DIRECTORY,
                    # always enabled, whatever the listing says about its *sub*directories: walking back
                    # out of a folder can never be the thing another resource owns
                    enabled=True,
                )
            )
        rows.extend(self.__row_for(entry, directory, root, states, navigable=navigable) for entry in listing.entries)
        return FilesRows(
            directory,
            rows=tuple(rows),
            at_root=at_root,
            subdirectories_navigable=navigable,
            foreign_record=listing.foreign_directory_record or "",
            record_error=states.error,
        )

    @staticmethod
    def __row_for(
        entry: DirectoryEntry, directory: Path, root: Path, states: FileChecksumStates, *, navigable: bool
    ) -> FileRow:
        """Turn one classified entry into a row.

        :param entry: the classified entry.
        :param directory: the directory being listed.
        :param root: the resource's own directory, which record-relative names are measured from.
        :param states: what the record says, by record-relative name.
        :param navigable: whether the subdirectories in this listing may be entered.
        :returns: the row.
        """
        path = directory / entry.name
        relative_name = path.relative_to(root).as_posix()
        return FileRow(
            name=entry.name,
            path=path,
            kind=entry.kind,
            file_type=entry.file_type,
            checksum_state=states.state_for(relative_name, entry.kind),
            untrusted_location=states.untrusted_location_for(relative_name, entry.kind),
            size=entry.size,
            modified=entry.modified,
            enabled=navigable if entry.is_directory else entry.kind in INTERACTIVE_KINDS,
        )


class FilesRowsLoader(QObject):
    """Reads one directory off the GUI thread and delivers the rows back onto it (#266).

    :class:`~rehuco_agent.documents.checksum_rows.ChecksumRowsLoader`'s shape, over a listing rather
    than a walk, and for the same reason: one ``scandir`` is cheap, and an away SMB mount
    ([[mounts-and-storage#offline-mounts]]) makes it block for the share timeout -- long enough to
    freeze a window that was only asked to show a tab.

    **A read already in flight is not cancelled, it is disowned.** Walking into a subdirectory while the
    previous listing is still out is the ordinary case here rather than a rarity: each read carries the
    generation it was started in, and an answer from an older one is dropped rather than drawn over the
    directory the reader has since moved to.

    :param parent: optional Qt parent.
    """

    loaded = Signal(object)
    """Fires on the GUI thread with the :class:`FilesRows` of the **most recent** request.

    Queued, because the emit happens on a pool thread. Fires exactly once per :meth:`start` that was
    still current when it finished, **including when the read raised**, so a caller that showed a busy
    state always gets it back."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__generation = 0

    def start(self, reader: FilesRowsReader, directory: Path) -> None:
        """Read ``directory`` on a pool thread and emit :attr:`loaded` with its rows.

        :param reader: the browser's reader, already holding the resource, the caller's patterns and the
            staleness window.
        :param directory: the directory to list.
        """
        self.__generation += 1
        generation = self.__generation
        # the instant is taken here, on the GUI thread, so every row of one read is judged against one
        # moment -- and a frozen clock in a test needs no reach into the pool
        now = datetime.now(tz=UTC)
        QThreadPool.globalInstance().start(lambda: self.__run(reader, directory, now, generation))

    def __run(self, reader: FilesRowsReader, directory: Path, now: datetime, generation: int) -> None:
        """Do the read on the worker thread and report it, raise or no raise.

        The blanket catch is the point rather than a shortcut: an exception escaping here is printed and
        swallowed by the pool, and the :attr:`loaded` that never arrived would leave the dock showing a
        busy state for the rest of the document's life. The emit is guarded too, for the reason
        :class:`~rehuco_agent.documents.checksum_rows.ChecksumRowsLoader` documents: a document closed
        while its read is out takes this object's C++ half with it.

        :param reader: the browser's reader.
        :param directory: the directory to list.
        :param now: the instant freshness is measured against.
        :param generation: which request this is, so a superseded answer can be dropped.
        """
        try:
            rows = reader.read(directory, now)
        except Exception as error:  # pylint: disable=broad-exception-caught
            rows = FilesRows(directory, reachable=False, record_error=str(error))
        if generation != self.__generation:
            return
        try:
            self.loaded.emit(rows)
        except RuntimeError:
            # the dock this belongs to was destroyed while the read was out
            pass


class FilesTableModel(QAbstractTableModel):
    """The rows, as a table (#266).

    A plain snapshot holder, like :class:`~rehuco_agent.documents.checksum_rows.ChecksumTableModel`: it
    is handed a :class:`FilesRows` and shows it, and every refresh is a whole new read. A folder changes
    under the app from outside it, so there is nothing here a diff could be trusted against.

    **A disabled row is disabled in :meth:`flags`**, not merely drawn pale: that is one answer rather
    than a paint rule plus a guard in every activation path, and it is what makes a double-click on
    another resource's screenshot impossible rather than merely ignored.

    :param parent: optional Qt parent.
    """

    SORT_ROLE: Final = Qt.ItemDataRole.UserRole
    """The role :class:`FilesSortProxy` sorts on -- the underlying value, never the drawn text."""

    ROW_ROLE: Final = Qt.ItemDataRole.UserRole + 1
    """The whole :class:`FileRow`, for the delegate that draws its glyphs and the view that activates
    it -- so neither has to map an index back through the proxy to ask what a row is."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__rows: tuple[FileRow, ...] = ()

    def set_rows(self, rows: tuple[FileRow, ...]) -> None:
        """Replace everything shown.

        :param rows: the rows to show.
        """
        self.beginResetModel()
        self.__rows = rows
        self.endResetModel()

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractTableModel``: a flat table has rows only at the root."""
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractTableModel``: :data:`COLUMN_COUNT` at the root, none under a cell."""
        return 0 if parent.isValid() else COLUMN_COUNT

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        """Selectable and enabled, except on a row a reader may not act on.

        :param index: the cell.
        :returns: the flags; :data:`~PySide6.QtCore.Qt.ItemFlag.NoItemFlags` on a disabled row, which
            takes selection, hover and activation with it in one answer.
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if not self.__rows[index.row()].enabled:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """What one cell shows, what it sorts on, and the row behind it.

        :param index: the cell.
        :param role: what is being asked for.
        :returns: the cell's value for that role, or ``None``.
        """
        if not index.isValid():
            return None
        row = self.__rows[index.row()]
        if role == FilesTableModel.ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return FilesTableModel.__display(row, index.column())
        if role == FilesTableModel.SORT_ROLE:
            return FilesTableModel.__sort_key(row, index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            return FilesTableModel.__tooltip(row, index.column())
        return None

    @staticmethod
    def __display(row: FileRow, column: int) -> str:
        """One cell's drawn text.

        The checksum column draws **none**: its glyph is the delegate's, and a cell answering text here
        would size the column for words nobody sees.

        :param row: the row.
        :param column: which column.
        :returns: the text, ``""`` where there is nothing to draw.
        """
        if column == NAME_COLUMN:
            return row.name
        if column == KIND_COLUMN:
            return "" if row.is_parent else KIND_LABELS[row.kind]
        if column == SIZE_COLUMN:
            return SizeMeasurementEdit.format(row.size)
        if column == MODIFIED_COLUMN:
            if row.modified is None:
                return ""
            return datetime.fromtimestamp(row.modified).astimezone().strftime(DATE_FORMAT)
        return ""

    @staticmethod
    def __sort_key(row: FileRow, column: int) -> Any:
        """One cell's sort value.

        ``..`` sorts ahead of everything and every directory ahead of every file, whichever column is
        being sorted: a listing whose folders scattered through its files by size would stop being a
        way to walk a tree. Within a group, the name is compared naturally, so ``file-2`` precedes
        ``file-10``.

        :param row: the row.
        :param column: which column.
        :returns: the value to sort that column on.
        """
        group = 0 if row.is_parent else (1 if row.is_directory else 2)
        if column == KIND_COLUMN:
            return group, KIND_LABELS[row.kind], natural_sort_key(row.name)
        if column == CHECKSUM_COLUMN:
            return group, row.checksum_state.value, natural_sort_key(row.name)
        if column == SIZE_COLUMN:
            return group, row.size or 0, natural_sort_key(row.name)
        if column == MODIFIED_COLUMN:
            return group, row.modified or 0.0, natural_sort_key(row.name)
        return group, natural_sort_key(row.name)

    @staticmethod
    def __tooltip(row: FileRow, column: int) -> str | None:
        """One cell's tooltip -- the glyphs' meanings, and the full path everywhere else.

        :param row: the row.
        :param column: which column.
        :returns: the tooltip, or ``None`` where there is nothing worth saying.
        """
        if column == CHECKSUM_COLUMN:
            return checksum_tooltip_for(row.checksum_state, row.untrusted_location)
        return str(row.path)

    @override
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The column titles.

        :param section: the column or row.
        :param orientation: which header.
        :param role: what is being asked for.
        :returns: the title, or ``None``.
        """
        if role != Qt.ItemDataRole.DisplayRole or orientation is not Qt.Orientation.Horizontal:
            return None
        return COLUMN_TITLES[section] if 0 <= section < COLUMN_COUNT else None


class FilesSortProxy(QSortFilterProxyModel):
    """Sorts the table (#266).

    A proxy rather than sorting in place, so a selection survives a sort -- the same reason
    :class:`~rehuco_agent.documents.checksum_rows.ChecksumSortProxy` is one.

    **It compares the keys itself** rather than leaving it to the sort role, which is where this differs
    from that proxy: the keys are tuples -- ``..``, then folders, then files, and the column's own value
    inside each group -- and a tuple handed through a ``QVariant`` is not something Qt knows how to
    order, so the base implementation silently fell back to comparing the drawn text and scattered the
    folders through the files. Comparing in Python is also what makes a natural-order name
    (``file-2`` before ``file-10``) and a numeric size sort correctly in one key.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setSortRole(FilesTableModel.SORT_ROLE)

    @override
    def lessThan(self, source_left: ModelIndex, source_right: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        """Order two rows by the sort keys the source model builds.

        **The grouping is never reversed.** Descending order flips the values *within* each group, but
        ``..`` stays at the top and the folders stay above the files -- a listing that put ``..`` at the
        bottom on a second header click would be a listing nobody can walk.

        :param source_left: the left row's source index.
        :param source_right: the right row's source index.
        :returns: whether the left row sorts first.
        """
        left = source_left.data(FilesTableModel.SORT_ROLE)
        right = source_right.data(FilesTableModel.SORT_ROLE)
        if not isinstance(left, tuple) or not isinstance(right, tuple):
            return bool(super().lessThan(source_left, source_right))
        if left[0] != right[0]:
            # the group leads the key, so a descending sort would otherwise invert it too
            return bool(left[0] < right[0]) is (self.sortOrder() is Qt.SortOrder.AscendingOrder)
        return bool(left[1:] < right[1:])
