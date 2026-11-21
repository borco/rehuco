"""Prefix buckets: a crowded folder of a root's layout split into folders named by the start of its entries' names
([[mounts-and-storage#buckets]], #680).

A ``{buckets}`` level of a layout (:mod:`rehuco_core.root_destination`) puts the level after it -- a record, or a folder
of records -- into the **deepest bucket** its name belongs to. The layout's own folder is depth 0; a bucket at depth
*n* is named by the first *n* characters of its entries' names, folded to lower case, so ``fab/0/01/01abc.rehu``.

**A folder that has been split carries a marker**, an empty file :data:`BUCKETS_MARKER`. An unmarked folder holds
entries; a marked folder at depth *n* holds buckets, each named by *n+1* characters, and the entries too short to
descend -- shorter than *n+1*, so never named like a bucket. A *folder* named :data:`BUCKETS_MARKER` marks its parent
as a plain folder that is never split.

**A folder splits once it holds more than the limit.** Every entry long enough moves into the bucket of one more of
its characters, and every bucket that then holds more than the limit splits the same way. Only a folder whose name is
a bucket's own length could be taken for one, so before the marker is written each such folder is moved into a
temporary bucket (:data:`TEMPORARY_BUCKET_PREFIX` plus its prefix), which is renamed into place once the marker is
there. A folder holding a temporary bucket is a split under way. So every step is one rename, a stop between two
leaves every record in one piece and in one place, and settling again from the disk alone finishes the split.

A prefix no folder may be named by -- one ending in a dot or a space, or one a sanitize step would change -- makes no
bucket: its entries stay where they are. Joining buckets back is the rebalance job's (#681).
"""

import logging
import os
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol

from .path_keys import path_key
from .record_file_lock import is_lock_name
from .resource_scoping import DIRECTORY_SCOPED_FILENAMES, is_record_name
from .sanitized_names import HIDDEN_NAME_PREFIX, location_name_problem, sanitize_name

LOG: Final = logging.getLogger(__name__)

BUCKETS_MARKER: Final = ".rehubuckets"
"""The file a split folder holds, written empty and read by its presence alone; a folder of that name makes its
parent one that is never split."""

TEMPORARY_BUCKET_PREFIX: Final = f"{BUCKETS_MARKER}-tmp-"
"""What a bucket being built is named by before it is renamed into place: this, its prefix, a dash and a random
token."""

DEFAULT_SPLIT_LIMIT: Final = 200
"""How many entries a fresh install lets a folder hold before it splits."""

MIN_SPLIT_LIMIT: Final = 50
"""The fewest entries a split limit may be: below it the tree deepens without any folder becoming easier to read."""

DEFAULT_JOIN_LIMIT: Final = 100
"""How few entries a split folder's whole subtree holds, in a fresh install, before the rebalance joins it (#681)."""

UNNAMED_PREFIX_ENDINGS: Final = (".", " ")
"""What no folder name may end with on Windows, so no prefix ending with one makes a bucket."""

CHAIN_FOLDER_KEY: Final = "folder"
CHAIN_BUCKETS_KEY: Final = "buckets"
"""The keys a :class:`BucketChain` writes itself down under."""


def clamped_limits(split: int, join: int) -> tuple[int, int]:
    """The limits as they are used: the split limit never under :data:`MIN_SPLIT_LIMIT`, the join limit never above
    half of it, so a join never leaves a folder near the split, nor a split one near the join.

    :param split: the split limit asked for.
    :param join: the join limit asked for.
    :returns: the split limit and the join limit.
    """
    split = max(MIN_SPLIT_LIMIT, split)
    return split, max(0, min(join, split // 2))


def bucket_key(name: str) -> str:
    """A name as buckets compare it: folded, as root folders are (#629).

    :param name: an entry's name.
    :returns: its key.
    """
    return path_key(name)


def bucket_prefix(name: str, depth: int) -> str | None:
    """The bucket an entry belongs to in a split folder at ``depth``.

    :param name: the entry's name: a record's stem, or a folder's name.
    :param depth: the folder's depth, 0 for the layout's own.
    :returns: the bucket's name, the first ``depth + 1`` characters of the key; ``None`` when the name is too short to
        descend or no folder may be named by its prefix.
    """
    key = bucket_key(name)
    if len(key) <= depth:
        return None
    prefix = key[: depth + 1]
    if sanitize_name(prefix) != prefix or prefix.endswith(UNNAMED_PREFIX_ENDINGS) or location_name_problem(prefix):
        return None
    return prefix


def is_bucket_chain(levels: Sequence[str], name: str) -> bool:
    """Whether ``levels`` are buckets an entry named ``name`` may sit in, from the layout's folder down: each the
    prefix of one more of its characters (#680). Pure; none is a chain too.

    :param levels: the folders between the layout's folder and the entry.
    :param name: the entry's name.
    :returns: whether they are its buckets.
    """
    return all(bucket_prefix(name, depth) == bucket_key(level) for depth, level in enumerate(levels))


def place_holds(levels: Sequence[str], relative: PurePosixPath, bucketed: Sequence[int]) -> bool:
    """Whether a path's levels are a bucketed place's, each bucketed level under any chain of its buckets (#680) --
    how the path row tells a record already there without reading the disk. Levels compare folded.

    :param levels: the path's levels, relative to its root.
    :param relative: the place, without its buckets.
    :param bucketed: the indices of its bucketed levels.
    :returns: whether the path is the place.
    """
    places = relative.parts

    def holds(at: int, index: int) -> bool:
        """Whether ``levels[at:]`` are ``places[index:]``, buckets and all."""
        if index == len(places):
            return at == len(levels)
        place = places[index]
        ends = range(at, len(levels)) if index in bucketed else range(at, min(at + 1, len(levels)))
        return any(
            bucket_key(levels[end]) == bucket_key(place)
            and is_bucket_chain(levels[at:end], place)
            and holds(end + 1, index + 1)
            for end in ends
        )

    return holds(0, 0)


def is_split(folder: Path) -> bool:
    """Whether a folder has been split: it holds the marker file.

    :param folder: the folder.
    :returns: whether it holds buckets.
    """
    return (folder / BUCKETS_MARKER).is_file()


def is_never_split(folder: Path) -> bool:
    """Whether a folder is never split: it holds a folder named like the marker.

    :param folder: the folder.
    :returns: whether it stays a plain folder.
    """
    return (folder / BUCKETS_MARKER).is_dir()


def temporary_prefix(name: str) -> str | None:
    """The prefix a temporary bucket's name was made for.

    :param name: a folder's name.
    :returns: the prefix, or ``None`` when the name is no temporary bucket's.
    """
    if not name.startswith(TEMPORARY_BUCKET_PREFIX):
        return None
    prefix, separator, _ = name[len(TEMPORARY_BUCKET_PREFIX) :].rpartition("-")
    return prefix if separator and prefix else None


def records_beneath(folder: Path) -> tuple[Path, ...]:
    """Every record beneath a folder, for a folder move to tell its listeners and check its locks.

    :param folder: the folder.
    :returns: each record's ``.rehu`` (or legacy ``.tc``), in walk order.
    :raises OSError: a folder could not be listed.
    """

    def failed(error: OSError) -> None:
        """Let a folder that cannot be listed fail the walk, instead of being skipped unseen.

        :param error: what listing it raised.
        :raises OSError: always.
        """
        raise error

    found: list[Path] = []
    for directory, _, files in os.walk(folder, onerror=failed):
        found.extend(Path(directory, name) for name in files if is_record_name(name) and not is_lock_name(name))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class BucketEntry:
    """One entry of a folder a layout buckets: a file record, or a folder -- a folder record, or a folder of records.

    :param name: what it is bucketed by: the record's stem, or the folder's name.
    :param path: the record's ``.rehu``, or the folder.
    :param is_folder: whether it is a folder, moved whole.
    """

    name: str
    path: Path
    is_folder: bool


@dataclass(slots=True)
class BucketListing:
    """What a folder a layout buckets holds.

    :param entries: its entries, in name order.
    :param buckets: its buckets by name, when it has been split.
    :param temporaries: its temporary buckets by the prefix each was made for.
    """

    entries: list[BucketEntry] = field(default_factory=list)
    buckets: dict[str, Path] = field(default_factory=dict)
    temporaries: dict[str, Path] = field(default_factory=dict)

    @classmethod
    def of(cls, folder: Path, depth: int) -> BucketListing:
        """List a folder: a temporary bucket is one by its name, a bucket is a folder named by *depth+1* characters in
        a split folder, and an entry is a record file or any other folder. Hidden names are left out, since no
        location starts with a dot, and so are a record's sidecars, which move with it.

        :param folder: the folder.
        :param depth: its depth, 0 for the layout's own.
        :returns: what it holds.
        :raises OSError: it could not be listed.
        """
        listing = cls()
        split = is_split(folder)
        with os.scandir(folder) as found:
            for item in sorted(found, key=lambda item: item.name):
                listing.add(item, folder, depth, split)
        return listing

    def add(self, item: os.DirEntry[str], folder: Path, depth: int, split: bool) -> None:
        """File one listed item where it belongs.

        :param item: the item.
        :param folder: the folder listed.
        :param depth: its depth.
        :param split: whether it has been split.
        """
        name, path = item.name, folder / item.name
        if item.is_dir(follow_symlinks=False):
            prefix = temporary_prefix(name)
            if prefix is not None:
                self.temporaries[prefix] = path
            elif name.startswith(HIDDEN_NAME_PREFIX):
                return
            elif split and len(bucket_key(name)) == depth + 1:
                self.buckets[bucket_key(name)] = path
            else:
                self.entries.append(BucketEntry(name, path, is_folder=True))
        elif is_record_name(name) and name not in DIRECTORY_SCOPED_FILENAMES:
            if name.startswith(HIDDEN_NAME_PREFIX):
                return
            self.entries.append(BucketEntry(Path(name).stem, path, is_folder=False))


def temporary_bucket_of(folder: Path, prefix: str) -> Path | None:
    """The temporary bucket a split under way is building for ``prefix`` in ``folder``.

    :param folder: the folder being split.
    :param prefix: the bucket's name.
    :returns: the temporary bucket, or ``None`` when none is being built.
    :raises OSError: the folder could not be listed.
    """
    with os.scandir(folder) as found:
        for item in found:
            if temporary_prefix(item.name) == prefix and item.is_dir(follow_symlinks=False):
                return folder / item.name
    return None


def bucket_of(layout_folder: Path, name: str) -> PurePosixPath:
    """The buckets an entry named ``name`` lands in under a layout's folder, read off the disk: down every split
    folder to the bucket of one more of its characters, the last one possibly still to be made. A bucket being built
    is landed in under its temporary name; its split renames it into place.

    :param layout_folder: the folder of the level before ``{buckets}``.
    :param name: the entry's name.
    :returns: the buckets, from the layout's folder down; none when the folder is not split.
    :raises OSError: a folder could not be read.
    """
    chain: list[str] = []
    folder = layout_folder
    while is_split(folder):
        prefix = bucket_prefix(name, len(chain))
        if prefix is None:
            break
        temporary = temporary_bucket_of(folder, prefix)
        if temporary is not None:
            chain.append(temporary.name)
            break
        chain.append(prefix)
        folder = folder / prefix
        if not folder.is_dir():
            break
    return PurePosixPath(*chain)


def resolve_buckets(root: Path, relative: PurePosixPath, bucketed: Sequence[int]) -> BucketedPlace:
    """A layout's place with its buckets read off the disk.

    :param root: the root's folder.
    :param relative: the place under it, without its buckets.
    :param bucketed: the indices of its bucketed levels (:attr:`~rehuco_core.Placement.bucketed`).
    :returns: the place with its buckets, and each layout folder's chain, the innermost first.
    :raises OSError: a folder could not be read.
    """
    levels: list[str] = []
    chains: list[BucketChain] = []
    for index, level in enumerate(relative.parts):
        if index in bucketed:
            folder = PurePosixPath(*levels)
            chain = bucket_of(root.joinpath(*levels), level)
            chains.append(BucketChain(folder, chain.parts))
            levels.extend(chain.parts)
        levels.append(level)
    return BucketedPlace(PurePosixPath(*levels), tuple(reversed(chains)))


@dataclass(frozen=True, slots=True)
class BucketChain:
    """The buckets a place went into under one layout folder.

    :param folder: the layout folder, relative to the root.
    :param chain: the buckets below it, from the top; a temporary bucket's name possibly last.
    """

    folder: PurePosixPath
    chain: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        """This chain as JSON primitives, for a move to keep.

        :returns: the state.
        """
        return {CHAIN_FOLDER_KEY: self.folder.as_posix(), CHAIN_BUCKETS_KEY: list(self.chain)}

    @classmethod
    def from_state(cls, state: Any) -> BucketChain:
        """A chain from what :meth:`to_state` wrote.

        :param state: the saved value.
        :returns: the chain.
        :raises ValueError: the value is not the shape written.
        """
        folder = state.get(CHAIN_FOLDER_KEY) if isinstance(state, dict) else None
        buckets = state.get(CHAIN_BUCKETS_KEY) if isinstance(state, dict) else None
        if not (isinstance(folder, str) and isinstance(buckets, list)) or not all(isinstance(b, str) for b in buckets):
            raise ValueError("A saved move's buckets are not a folder and the buckets below it.")
        return cls(PurePosixPath(folder), tuple(buckets))


@dataclass(frozen=True, slots=True)
class BucketedPlace:
    """A layout's place with its buckets resolved.

    :param relative: the place, relative to the root, buckets included.
    :param chains: each bucketed level's chain, the innermost first -- the order they are settled in, since an outer
        split moves the inner levels' folders whole.
    """

    relative: PurePosixPath
    chains: tuple[BucketChain, ...]


class BucketMover(Protocol):
    """How a split moves what it moves: through the rename barrier, so every holder of a path follows."""

    def move_record(self, record: Path, into: Path) -> None:
        """Move a file record, keeping its name.

        :param record: its ``.rehu``.
        :param into: the folder it lands in, made when missing.
        """

    def move_folder(self, folder: Path, into: Path, name: str) -> None:
        """Move a folder whole, with every record beneath it.

        :param folder: the folder.
        :param into: the folder it lands in, made when missing.
        :param name: its name there.
        """


class BucketSplitter:
    """Splits the folders a bucketed level crowds, from the disk alone, so a split stopped anywhere is finished by
    settling again (#680).

    :param limit: how many entries a folder holds before it splits; clamped to :data:`MIN_SPLIT_LIMIT`.
    :param mover: how a record or a folder is moved.
    :param checkpoint: called before every move; what it raises stops the split there.
    """

    def __init__(self, limit: int, mover: BucketMover, checkpoint: Callable[[], None] = lambda: None) -> None:
        self.__limit: Final = clamped_limits(limit, 0)[0]
        self.__mover: Final = mover
        self.__checkpoint: Final = checkpoint

    @property
    def limit(self) -> int:
        """How many entries a folder holds before it splits, as clamped."""
        return self.__limit

    def settle(self, layout_folder: Path, chain: Sequence[str]) -> None:
        """Settle a layout folder and the buckets a place went into below it, top-down, and every bucket a split
        fills.

        :param layout_folder: the folder of the level before ``{buckets}``.
        :param chain: the buckets below it the place went into; a temporary bucket by its name.
        :raises OSError: a folder could not be read, or a move failed.
        """
        folder, depth = layout_folder, 0
        while True:
            self.__settle(folder, depth)
            if depth == len(chain):
                return
            level = chain[depth]
            folder, depth = folder / (temporary_prefix(level) or level), depth + 1
            if not folder.is_dir():
                return

    def __settle(self, folder: Path, depth: int) -> None:
        """Split one folder when it is over the limit or a split of it is under way, then every bucket that took
        entries.

        :param folder: the folder.
        :param depth: its depth.
        """
        if is_never_split(folder):
            return
        listing = BucketListing.of(folder, depth)
        if not is_split(folder):
            if not listing.temporaries and len(listing.entries) <= self.__limit:
                return
            LOG.info("%s holds %d entries, more than %d: splitting it.", folder, len(listing.entries), self.__limit)
            if not self.__set_aside(folder, depth, listing):
                return
            (folder / BUCKETS_MARKER).touch()
            listing = BucketListing.of(folder, depth)
        filled: set[str] = set()
        for prefix, temporary in listing.temporaries.items():
            self.__place_temporary(folder, depth, prefix, temporary)
            filled.add(prefix)
        for entry in BucketListing.of(folder, depth).entries:
            prefix = bucket_prefix(entry.name, depth)
            if prefix is not None:
                self.__move(entry, folder / prefix)
                filled.add(prefix)
        for prefix in sorted(filled):
            self.__settle(folder / prefix, depth + 1)

    def __set_aside(self, folder: Path, depth: int, listing: BucketListing) -> bool:
        """Move every folder named like a bucket into a temporary bucket, so the marker never makes one look like a
        bucket.

        :param folder: the folder about to be split.
        :param depth: its depth.
        :param listing: what it holds; its temporaries gain the buckets made.
        :returns: whether the split may go on: ``False`` for such a folder no bucket may be named after, asked of
            every one before the first is moved, so a split that cannot go on leaves nothing in a temporary bucket.
        """
        aside: list[tuple[BucketEntry, str]] = []
        for entry in listing.entries:
            if not entry.is_folder or len(bucket_key(entry.name)) != depth + 1:
                continue
            prefix = bucket_prefix(entry.name, depth)
            if prefix is None:
                LOG.warning("%s cannot be split: no bucket may be named after %s.", folder, entry.name)
                return False
            aside.append((entry, prefix))
        for entry, prefix in aside:
            temporary = listing.temporaries.get(prefix)
            if temporary is None:
                temporary = folder / f"{TEMPORARY_BUCKET_PREFIX}{prefix}-{secrets.token_hex(4)}"
                temporary.mkdir()
                listing.temporaries[prefix] = temporary
            self.__move(entry, temporary)
        return True

    def __place_temporary(self, folder: Path, depth: int, prefix: str, temporary: Path) -> None:
        """Rename a temporary bucket into place; when its bucket exists already, move what it holds there instead.

        :param folder: the split folder.
        :param depth: its depth.
        :param prefix: the bucket's name.
        :param temporary: the temporary bucket.
        """
        bucket = folder / prefix
        if not bucket.exists():
            self.__checkpoint()
            self.__mover.move_folder(temporary, folder, prefix)
            return
        for entry in BucketListing.of(temporary, depth + 1).entries:
            self.__move(entry, bucket)
        try:
            temporary.rmdir()
        except OSError:
            LOG.warning("%s was left: it still holds files that are no record.", temporary, exc_info=True)

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
