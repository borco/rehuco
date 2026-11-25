"""Joining the buckets of a split folder back into it ([[mounts-and-storage#bucket-rebalance]], #681) -- the reverse of
:class:`~rehuco_core.BucketSplitter`, and like it stopped anywhere with every record whole and in one place.

A folder is joined once its whole subtree holds no more than the limit -- or whatever it holds, when no layout buckets
it any more. Every entry beneath moves straight up into it, the emptied buckets are removed, and **the marker goes
after them**, so until then the folder is a split one whatever was moved: whoever settles it meanwhile moves the
entries down again. Only a folder named as long as a bucket could be taken for one by a folder still marked
(``a/ab/ab``), so it goes into a temporary bucket, as a split does, and out of it once the marker is gone. A stop
between those two leaves what a split stopped before its marker leaves -- an unmarked folder holding a temporary
bucket -- which a split finishes as a split and the next join as a join.

**A bucket that holds a file belonging to no record stays**, and its folder with it, as does a folder two of whose
entries have one name: asked of every bucket beneath before the first move, so nothing is half joined. The junk an
operating system leaves behind (the Files page's excluded patterns) is deleted instead, as the app deletes anything. A
bucket its owner marked *never split* (a folder named like the marker) keeps the folders above it split too.
"""

import logging
import math
import os
import secrets
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from enum import Enum, auto
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

from .prefix_buckets import (
    BUCKETS_MARKER,
    TEMPORARY_BUCKET_PREFIX,
    BucketEntry,
    BucketListing,
    BucketMover,
    bucket_key,
    is_never_split,
    is_split,
)
from .record_file_lock import is_lock_name
from .rehu_rename import files_of_record, is_named_after
from .rehu_screenshot_ordering import DEFAULT_DELETER, Deleter

LOG: Final = logging.getLogger(__name__)


class JoinResult(Enum):
    """What became of one folder a join looked at."""

    NONE = auto()
    """Nothing moved: it has no buckets, holds too much, or is left split."""

    JOINED = auto()
    """Its buckets are joined into it."""

    HALTED = auto()
    """It is left split after its entries moved up, by something that arrived meanwhile: splitting it in the same pass
    would only move them down again."""


# a value filled in by one walk, each field read once by the join
@dataclass(slots=True)
class BucketSurvey:  # pylint: disable=too-many-instance-attributes
    """What a split folder's buckets hold, all the way down.

    :param entries: every entry in a bucket beneath, at any depth.
    :param held: the entries in the folder's own temporary buckets, which leave them last.
    :param buckets: every bucket and temporary bucket beneath but the folder's own temporaries, the deepest first.
    :param temporaries: the folder's own temporary buckets, by the prefix each was made for.
    :param junk: the files beneath an operating system left, which a join deletes.
    :param strays: the other files and folders beneath that belong to no record.
    :param names: the entries of the whole subtree by the name each has on the disk, folded.
    :param twins: the entries that have another's name.
    :param count: how many entries the whole subtree holds, the folder's own included.
    :param pinned: whether a bucket beneath is one never split.
    """

    entries: list[BucketEntry] = field(default_factory=list)
    held: list[BucketEntry] = field(default_factory=list)
    buckets: list[Path] = field(default_factory=list)
    temporaries: dict[str, Path] = field(default_factory=dict)
    junk: list[Path] = field(default_factory=list)
    strays: list[Path] = field(default_factory=list)
    names: dict[str, BucketEntry] = field(default_factory=dict)
    twins: list[BucketEntry] = field(default_factory=list)
    count: int = 0
    pinned: bool = False

    def count_in(self, entries: Sequence[BucketEntry]) -> None:
        """Count entries, and tell the ones that have the name of another.

        :param entries: the entries.
        """
        self.count += len(entries)
        for entry in entries:
            if self.names.setdefault(bucket_key(entry.path.name), entry) is not entry:
                self.twins.append(entry)


class BucketJunk:
    """The files a join deletes from the buckets it empties: what an operating system leaves behind (#681).

    :param patterns: the globs naming them, matched in any case.
    :param deleter: how one is deleted.
    """

    def __init__(self, patterns: Sequence[str] = (), deleter: Deleter = DEFAULT_DELETER) -> None:
        self.__patterns: Final = tuple(pattern.lower() for pattern in patterns)
        self.__deleter: Final = deleter

    def holds(self, name: str, is_folder: bool) -> bool:
        """Whether an item in a bucket is junk.

        :param name: its name.
        :param is_folder: whether it is a folder, which never is.
        :returns: whether a join deletes it.
        """
        return not is_folder and any(fnmatchcase(name.lower(), pattern) for pattern in self.__patterns)

    def delete(self, path: Path) -> None:
        """Delete a junk file; one already gone is no failure.

        :param path: the file.
        :raises OSError: it could not be deleted.
        """
        try:
            self.__deleter.delete(path)
        except FileNotFoundError:
            return
        LOG.info("Deleted %s, left in a bucket being joined.", path)


class BucketJoiner:
    """Joins the folders whose whole subtree no longer needs its buckets, from the disk alone (#681).

    :param limit: how few entries a split folder's whole subtree holds to be joined, clamped by the caller
        (:func:`~rehuco_core.clamped_limits`); ``None`` joins it whatever it holds, a folder no layout buckets any more.
    :param mover: how a record or a folder is moved.
    :param junk: the files it deletes from the buckets it empties; none by default.
    :param checkpoint: called before every move and while a folder is surveyed; what it raises stops the join there.
    :param exclusively: entered around the marker's removal, so that nothing lands in a bucket between the last look
        and the removal; what entering it raises stops the join there.
    """

    def __init__(
        self,
        limit: int | None,
        mover: BucketMover,
        *,
        junk: BucketJunk | None = None,
        checkpoint: Callable[[], None] = lambda: None,
        exclusively: Callable[[], AbstractContextManager[object]] = nullcontext,
    ) -> None:
        self.__limit: Final[float] = math.inf if limit is None else limit
        self.__mover: Final = mover
        self.__junk: Final = junk if junk is not None else BucketJunk()
        self.__checkpoint: Final = checkpoint
        self.__exclusively: Final = exclusively
        self.__left: Final[list[str]] = []
        self.__told: Final[set[Path]] = set()
        """The files that keep a folder split, told already: a folder beneath it is split for the same one."""

    @property
    def left(self) -> tuple[str, ...]:
        """Why each folder that could have been joined was left split, in the order they were met."""
        return tuple(self.__left)

    def join(self, folder: Path, depth: int) -> JoinResult:
        """Join a folder's buckets back into it, when it has any and its whole subtree is within the limit.

        :param folder: the folder.
        :param depth: its depth, 0 for the layout's own.
        :returns: what became of it; :attr:`left` says why one was left split.
        :raises OSError: a folder could not be read, or a move failed.
        """
        survey = self.__survey(folder, depth)
        if survey is None or survey.pinned or not self.__may_join(folder, survey):
            return JoinResult.NONE
        LOG.info("%s holds %d entries in all: joining it.", folder, survey.count)
        split = is_split(folder)
        for entry in survey.entries:
            if entry.is_folder and len(bucket_key(entry.name)) == depth + 1:
                self.__set_aside(folder, entry, survey)
            else:
                self.__move(entry, folder)
        if not self.__remove_buckets(folder, survey.buckets) or (split and not self.__unmark(folder, depth)):
            return JoinResult.HALTED
        for entry in survey.held:
            self.__move(entry, folder)
        if not self.__remove_buckets(folder, tuple(survey.temporaries.values())):
            return JoinResult.HALTED
        return JoinResult.JOINED

    def __may_join(self, folder: Path, survey: BucketSurvey) -> bool:
        """Whether nothing beneath a folder keeps it split, its junk deleted.

        :param folder: the folder.
        :param survey: what it holds.
        :returns: whether the join may go on; why not is told once, not again for each folder beneath.
        """
        for path, reason in (
            *((stray, "belongs to no record") for stray in survey.strays),
            *((twin.path, "has the name of another entry") for twin in survey.twins),
        ):
            if path not in self.__told:
                self.__told.add(path)
                self.__leave(folder, f"{path} {reason}")
            return False
        return self.__delete_junk(folder, survey.junk)

    def __unmark(self, folder: Path, depth: int) -> bool:
        """Remove a folder's marker, unless a bucket is back since the last was removed.

        :param folder: the folder.
        :param depth: its depth.
        :returns: whether it is gone.
        """
        with self.__exclusively():
            back = next(iter(BucketListing.of(folder, depth).buckets.values()), None)
            if back is not None:
                return self.__leave(folder, f"{back} arrived while it was joined")
            (folder / BUCKETS_MARKER).unlink()
        return True

    def __survey(self, folder: Path, depth: int) -> BucketSurvey | None:
        """Read what a folder's buckets hold.

        :param folder: the folder.
        :param depth: its depth.
        :returns: the survey; ``None`` for a folder with no buckets, or holding more than the limit.
        """
        listing = BucketListing.of(folder, depth)
        if not is_split(folder) and not listing.temporaries:
            return None
        survey = BucketSurvey()
        survey.count_in(listing.entries)
        for bucket in listing.buckets.values():
            survey.entries.extend(self.__survey_bucket(bucket, depth + 1, survey))
            survey.buckets.append(bucket)
        for prefix, temporary in listing.temporaries.items():
            survey.held.extend(self.__survey_bucket(temporary, depth + 1, survey))
            survey.temporaries[prefix] = temporary
        return None if survey.count > self.__limit else survey

    def __survey_bucket(self, bucket: Path, depth: int, survey: BucketSurvey) -> list[BucketEntry]:
        """Read one bucket and those beneath it, no further than the limit.

        :param bucket: the bucket.
        :param depth: its depth.
        :param survey: what the folder being surveyed holds; its count, its buckets beneath this one, its junk and
            its strays are added to.
        :returns: the entries in the bucket and beneath it.
        """
        if survey.count > self.__limit:
            return []
        self.__checkpoint()
        if is_never_split(bucket):
            survey.pinned = True
        listing = BucketListing.of(bucket, depth)
        survey.count_in(listing.entries)
        self.__sort_files(bucket, listing, survey)
        entries = list(listing.entries)
        for beneath in (*listing.buckets.values(), *listing.temporaries.values()):
            entries.extend(self.__survey_bucket(beneath, depth + 1, survey))
            survey.buckets.append(beneath)
        return entries

    def __sort_files(self, bucket: Path, listing: BucketListing, survey: BucketSurvey) -> None:
        """Tell a bucket's junk and strays from what its records take with them.

        :param bucket: the bucket.
        :param listing: what it holds.
        :param survey: where the junk and the strays are added.
        """
        folders = {entry.path.name for entry in listing.entries if entry.is_folder}
        folders.update(path.name for path in (*listing.buckets.values(), *listing.temporaries.values()))
        records = [entry for entry in listing.entries if not entry.is_folder]
        with os.scandir(bucket) as found:
            items = {item.name: item.is_dir(follow_symlinks=False) for item in found}
        files = [name for name, is_folder in items.items() if not is_folder]
        owned = {name for record in records for name in files_of_record(files, record.path.name)}
        for name, is_folder in items.items():
            if name in folders or name in owned or name == BUCKETS_MARKER:
                continue
            # a lock beside its record is a write under way, which the record's move waits for
            if is_lock_name(name) and any(is_named_after(name, record.name) for record in records):
                continue
            (survey.junk if self.__junk.holds(name, is_folder) else survey.strays).append(bucket / name)

    def __delete_junk(self, folder: Path, junk: Sequence[Path]) -> bool:
        """Delete the junk files in a folder's buckets.

        :param folder: the folder about to be joined.
        :param junk: the files.
        :returns: whether all are gone; a folder one of which could not be deleted is left split.
        """
        for path in junk:
            self.__checkpoint()
            try:
                self.__junk.delete(path)
            except OSError as error:
                return self.__leave(folder, f"{path} could not be deleted ({error})")
        return True

    def __set_aside(self, folder: Path, entry: BucketEntry, survey: BucketSurvey) -> None:
        """Move a folder named like one of the folder's buckets into a temporary bucket, out of which it goes once the
        marker is gone.

        :param folder: the folder being joined.
        :param entry: the entry.
        :param survey: what the folder holds; it gains the temporary bucket and the entry there.
        """
        prefix = bucket_key(entry.name)
        temporary = survey.temporaries.setdefault(
            prefix, folder / f"{TEMPORARY_BUCKET_PREFIX}{prefix}-{secrets.token_hex(4)}"
        )
        self.__checkpoint()
        self.__mover.move_folder(entry.path, temporary, entry.name)
        survey.held.append(BucketEntry(entry.name, temporary / entry.name, is_folder=True))

    def __remove_buckets(self, folder: Path, buckets: Sequence[Path]) -> bool:
        """Remove emptied buckets, the marker of each just before it, with the junk a file manager showing one wrote
        back.

        :param folder: the folder being joined.
        :param buckets: the buckets, the deepest first.
        :returns: whether all are gone; a folder one of which holds something that was not there when it was surveyed
            is left split.
        """
        for bucket in buckets:
            self.__checkpoint()
            left = [path for path in bucket.iterdir() if path.name != BUCKETS_MARKER]
            junk = [path for path in left if self.__junk.holds(path.name, path.is_dir())]
            found = next((path for path in left if path not in junk), None)
            if found is not None:
                return self.__leave(folder, f"{found} arrived while it was joined")
            if not self.__delete_junk(folder, junk):
                return False
            (bucket / BUCKETS_MARKER).unlink(missing_ok=True)
            bucket.rmdir()
        return True

    def __leave(self, folder: Path, reason: str) -> bool:
        """Say why a folder is left split.

        :param folder: the folder.
        :param reason: what keeps it so.
        :returns: ``False``, for the callers that return this.
        """
        LOG.warning("%s was not joined: %s.", folder, reason)
        self.__left.append(f"{folder}: {reason}")
        return False

    def __move(self, entry: BucketEntry, into: Path) -> None:
        """Move one entry into a folder, keeping its name.

        :param entry: the entry.
        :param into: the folder.
        """
        self.__checkpoint()
        if entry.is_folder:
            self.__mover.move_folder(entry.path, into, entry.name)
        else:
            self.__mover.move_record(entry.path, into)
