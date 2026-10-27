"""A file browser's rows as data: what one entry of a folder is, and what one read of it established (#266).

Apart from :mod:`~rehuco_agent.documents.files_rows`, which reads them and tabulates them, so what the progress readout
(:mod:`~rehuco_agent.documents.files_progress`) and the reader both build on has a home of its own.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from rehuco_core import FileKind, FileType

PARENT_ROW_NAME: Final = ".."
"""What the row leading out of a subdirectory is called.

The shell's own spelling, and deliberately not a *Go up* button only: a reader who has walked into a
subdirectory looks for it in the listing, and the toolbar's up action is the same act reachable from
somewhere else."""


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
    """Content this record holds no hash for -- whether because the resource has no ``.checksum`` at all,
    because that record skips this file, or because it lists the file with no hash (the ``unexpected`` an
    older build wrote, #467). Deliberately one state rather than three: all are *nothing is recorded about
    these bytes*, and the remedy for all is the same generate."""

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

    MALFORMED = "malformed"
    """The entry's hash sits under a key this build cannot read (#303). Distinct from
    :data:`MISSING` and ``mismatched``: this build has made **no claim at all** about the bytes and never
    re-hashes them -- drawing it as a mismatch would assert a check that never happened, and drawing it
    as :data:`MISSING` would invite a generate that overwrites a neighbour's entry. Never actually
    written by this build ([[data-model#checksums]]), so an entry resting here came from elsewhere.
    Carries no ``verified`` stamp either, so there is no ``old_`` pair."""


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
    :param key: the content key of a video of the resource, which its progress is filed under (#316); ``None`` for
        everything else.
    :param missing: whether this is no file at all but the entry of one that is gone, drawn so it can be forgotten.
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
    key: str | None = None
    missing: bool = False

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


# a read's answer, one field per thing a read establishes; grouping them would only move the count into a bag
@dataclass(frozen=True, slots=True)
class FilesRows:  # pylint: disable=too-many-instance-attributes
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
    :param video_keys: the content key of every video of the resource on disk, at any depth -- what a folder's share of
        watching and a missing entry are judged against (#316); ``None`` when that was not asked for (a document that
        is not a tutorial) or a folder under the resource would not list.
    """

    directory: Path
    rows: tuple[FileRow, ...] = ()
    reachable: bool = True
    at_root: bool = True
    subdirectories_navigable: bool = True
    foreign_record: str = ""
    record_error: str = ""
    video_keys: tuple[str, ...] | None = None
