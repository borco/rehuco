"""Prefix buckets: a crowded folder of a root's layout split into folders named by the start of its entries' names
([[mounts-and-storage#buckets]], #680).

A ``{buckets}`` level of a layout (:mod:`rehuco_core.root_destination`) puts the level after it -- a record, or a folder
of records -- into the **deepest bucket** its name belongs to. The layout's own folder is depth 0; a bucket at depth
*n* is named by the first *n* characters of its entries' names, folded to lower case, so ``fab/0/01/01abc.rehu``.

**A folder that has been split carries a marker**, an empty file :data:`BUCKETS_MARKER`. An unmarked folder holds
entries; a marked folder at depth *n* holds buckets, each named by *n+1* characters, and the entries too short to
descend -- shorter than *n+1*, so never named like a bucket. A *folder* named :data:`BUCKETS_MARKER` marks its parent
as a plain folder that is never split.

**A folder splits once it holds more than the limit.** Every entry long enough moves into the deepest bucket of its
name, and every bucket that then holds more than the limit splits the same way. Only a folder whose name is
a bucket's own length could be taken for one, so before the marker is written each such folder is moved into a
temporary bucket (:data:`TEMPORARY_BUCKET_PREFIX` plus its prefix), which is renamed into place once the marker is
there. A folder holding a temporary bucket is a split under way. So every step is one rename, a stop between two
leaves every record in one piece and in one place, and settling again from the disk alone finishes the split.

A prefix no folder may be named by -- one ending in a dot or a space, or one a sanitize step would change -- makes no
bucket: its entries stay where they are. Joining buckets back is the rebalance job's (#681,
:mod:`rehuco_core.bucket_joiner`), never an arriving record's.
"""

import logging
import os
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol

from .constants import REHU_SUFFIX
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

MAX_SPLIT_LIMIT: Final = 100_000
"""The most entries a split limit may be."""

DEFAULT_JOIN_LIMIT: Final = 100
"""How few entries a split folder's whole subtree holds, in a fresh install, before the rebalance joins it (#681)."""

UNNAMED_PREFIX_ENDINGS: Final = (".", " ")
"""What no folder name may end with on Windows, so no prefix ending with one makes a bucket."""

SYSTEM_FOLDER_NAMES: Final = ("$RECYCLE.BIN", "System Volume Information", "@Recycle")
"""The folders an operating system or a NAS keeps at the top of a drive or a share: no entry of a layout that buckets
the root's own folder, where moving one would break the Recycle Bin (#681)."""

CHAIN_FOLDER_KEY: Final = "folder"
CHAIN_BUCKETS_KEY: Final = "buckets"
"""The keys a :class:`BucketChain` writes itself down under."""


def max_join_limit(split: int) -> int:
    """The largest join limit used beside a split limit: half of it, so a join never leaves a folder near the split,
    nor a split one near the join.

    :param split: the split limit.
    :returns: the largest join limit.
    """
    return split // 2


def clamped_limits(split: int, join: int) -> tuple[int, int]:
    """The limits as they are used: the split limit from :data:`MIN_SPLIT_LIMIT` to :data:`MAX_SPLIT_LIMIT`, the join
    limit never above :func:`max_join_limit`.

    :param split: the split limit asked for.
    :param join: the join limit asked for.
    :returns: the split limit and the join limit.
    """
    split = min(max(MIN_SPLIT_LIMIT, split), MAX_SPLIT_LIMIT)
    return split, max(0, min(join, max_join_limit(split)))


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
    return place_chains(levels, relative, bucketed) is not None


def place_chains(
    levels: Sequence[str], relative: PurePosixPath, bucketed: Sequence[int]
) -> tuple[BucketChain, ...] | None:
    """The buckets a path has at each bucketed level of a place, when its levels are the place's (#681) -- how the
    rebalance finds a layout's folders. A temporary bucket is the bucket it is being built for, so a split stopped
    halfway is found too.

    :param levels: the path's levels, relative to its root.
    :param relative: the place, without its buckets.
    :param bucketed: the indices of its bucketed levels.
    :returns: one chain per bucketed level, the outermost first, as the path spells them; ``None`` when the path is not
        the place.
    """
    places = relative.parts

    def chains(at: int, index: int) -> tuple[BucketChain, ...] | None:
        """The chains of ``levels[at:]`` as ``places[index:]``, ``None`` when they are not."""
        if index == len(places):
            return () if at == len(levels) else None
        place = places[index]
        ends = range(at, len(levels)) if index in bucketed else range(at, min(at + 1, len(levels)))
        for end in ends:
            buckets = [temporary_prefix(level) or level for level in levels[at:end]]
            if bucket_key(levels[end]) != bucket_key(place) or not is_bucket_chain(buckets, place):
                continue
            beneath = chains(end + 1, index + 1)
            if beneath is not None:
                here = (BucketChain(PurePosixPath(*levels[:at]), tuple(levels[at:end])),) if index in bucketed else ()
                return (*here, *beneath)
        return None

    return chains(0, 0)


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


def is_record_folder(folder: Path) -> bool:
    """Whether a folder is a folder record, and so never a bucket however it is named (#681): put there by hand, its
    own folders would otherwise be split as a bucket's entries.

    :param folder: the folder.
    :returns: whether it holds a record describing it.
    """
    return any((folder / name).is_file() for name in DIRECTORY_SCOPED_FILENAMES)


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
        a split folder and no folder record, and an entry is a record file or any other folder. Hidden names are left
        out, since no location starts with a dot, and so are a system's folders and a record's sidecars, which move
        with it -- a legacy record beside the ``.rehu`` of its name among them.

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
        rehus = {bucket_key(entry.name) for entry in listing.entries if entry.path.suffix.lower() == REHU_SUFFIX}
        listing.entries = [
            entry
            for entry in listing.entries
            if entry.is_folder or entry.path.suffix.lower() == REHU_SUFFIX or bucket_key(entry.name) not in rehus
        ]
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
            elif is_passed_over(name):
                return
            elif split and len(bucket_key(name)) == depth + 1 and not is_record_folder(path):
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


def bucket_of(folder: Path, name: str, depth: int = 0) -> PurePosixPath:
    """The buckets an entry named ``name`` lands in under a folder, read off the disk: down every split folder to the
    bucket of one more of its characters, the last one possibly still to be made. A bucket being built is landed in
    under its temporary name; its split renames it into place.

    :param folder: the folder of the level before ``{buckets}``, or a bucket beneath it.
    :param name: the entry's name.
    :param depth: the folder's depth, 0 for the layout's own.
    :returns: the buckets, from the folder down; none when the folder is not split.
    :raises OSError: a folder could not be read.
    """
    chain: list[str] = []
    while is_split(folder):
        prefix = bucket_prefix(name, depth + len(chain))
        if prefix is None:
            break
        temporary = temporary_bucket_of(folder, prefix)
        if temporary is not None:
            chain.append(temporary.name)
            break
        folder = folder / prefix
        if is_record_folder(folder):
            break
        chain.append(prefix)
        if not folder.is_dir():
            break
    return PurePosixPath(*chain)


def resolve_buckets(root: Path, relative: PurePosixPath, bucketed: Sequence[int]) -> BucketedPlace:
    """A layout's place with its buckets read off the disk, and the first folder on its way that is split where the
    layout has no ``{buckets}`` (#681).

    :param root: the root's folder.
    :param relative: the place under it, without its buckets.
    :param bucketed: the indices of its bucketed levels (:attr:`~rehuco_core.Placement.bucketed`).
    :returns: the place with its buckets, each layout folder's chain, the innermost first, and that folder.
    :raises OSError: a folder could not be read.
    """
    levels: list[str] = []
    chains: list[BucketChain] = []
    ungoverned: Path | None = None
    for index, level in enumerate(relative.parts):
        folder = root.joinpath(*levels)
        if index in bucketed:
            chain = bucket_of(folder, level)
            chains.append(BucketChain(PurePosixPath(*levels), chain.parts))
            levels.extend(chain.parts)
        elif ungoverned is None and is_split(folder):
            ungoverned = folder
        levels.append(level)
    return BucketedPlace(PurePosixPath(*levels), tuple(reversed(chains)), ungoverned)


def ungoverned_reason(folder: Path) -> str:
    """Why nothing may be put on a path that leads into a folder split where its layout has no ``{buckets}`` (#681).

    :param folder: the folder (:attr:`BucketedPlace.ungoverned`).
    :returns: the reason, in a sentence a user reads.
    """
    return (
        f"{folder.name or folder} is split into buckets, and this layout has none there: give it {{buckets}} there, or "
        "balance the root's buckets if no layout has them any more."
    )


def is_passed_over(name: str) -> bool:
    """Whether a folder's name says it is no entry of a layout: hidden, or a system's.

    :param name: its name.
    :returns: whether it is left out.
    """
    return name.startswith(HIDDEN_NAME_PREFIX) or bucket_key(name) in map(bucket_key, SYSTEM_FOLDER_NAMES)


def split_folders(root: Path, checkpoint: Callable[[], None] = lambda: None) -> tuple[Path, ...]:
    """Every folder under a root that holds buckets of its own, by what is on the disk (#681): one that is split, or
    holds a temporary bucket. A bucket is part of the folder it is a bucket of. A folder record is one when it is split,
    and nothing is looked for in it, nor in a hidden folder or a system's. A folder that may not be listed is passed
    over.

    :param root: the root's folder, itself one of them when it holds buckets.
    :param checkpoint: called before each folder is listed; what it raises stops the search.
    :returns: the folders, the deepest first.
    :raises OSError: a folder could not be listed, other than for lack of permission.
    """
    found: list[Path] = []

    def walk(folder: Path, depth: int, is_bucket: bool) -> None:
        """Look at one folder and everything beneath it.

        :param folder: the folder.
        :param depth: its depth as a bucket, 0 for one that is none.
        :param is_bucket: whether it is one.
        """
        checkpoint()
        try:
            with os.scandir(folder) as items:
                names = {item.name: item.is_dir(follow_symlinks=False) for item in items}
        except PermissionError:
            LOG.warning("%s could not be looked at for buckets.", folder, exc_info=True)
            return
        split = names.get(BUCKETS_MARKER) is False
        if folder != root and any(names.get(name) is False for name in DIRECTORY_SCOPED_FILENAMES):
            if split:
                found.append(folder)
            return
        folders = sorted(name for name, is_folder in names.items() if is_folder)
        temporaries = {name for name in folders if temporary_prefix(name) is not None}
        for name in folders:
            if name not in temporaries and is_passed_over(name):
                continue
            beneath = name in temporaries or (split and len(bucket_key(name)) == depth + 1)
            walk(folder / name, depth + 1 if beneath else 0, beneath)
        if (split or temporaries) and not is_bucket:
            found.append(folder)

    walk(root, 0, False)
    return tuple(sorted(found, key=lambda folder: (-len(folder.parts), folder)))


def unresolve_buckets(relative: PurePosixPath, chains: Sequence[BucketChain]) -> tuple[PurePosixPath, tuple[int, ...]]:
    """A place as it was before its buckets were read -- :func:`resolve_buckets` undone, for a move that is to read them
    again (#681).

    :param relative: the place, its buckets included.
    :param chains: each bucketed level's chain.
    :returns: the place without its buckets, and the indices of its bucketed levels.
    """
    levels = list(relative.parts)
    bucketed: list[int] = []
    removed = 0
    for chain in sorted(chains, key=lambda chain: len(chain.folder.parts)):
        index = len(chain.folder.parts) - removed
        del levels[index : index + len(chain.chain)]
        removed += len(chain.chain)
        bucketed.append(index)
    return PurePosixPath(*levels), tuple(bucketed)


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


def restored_buckets(bucketed: Any, chains: Any) -> tuple[tuple[int, ...], tuple[BucketChain, ...]]:
    """The bucketed levels and the chains a saved move names (#680).

    :param bucketed: the saved levels.
    :param chains: the saved chains.
    :returns: the levels still to resolve, and the chains still to settle.
    :raises ValueError: either is not the shape written.
    """
    if not (
        isinstance(bucketed, list) and all(isinstance(index, int) and not isinstance(index, bool) for index in bucketed)
    ):
        raise ValueError("A saved move's bucketed levels are not a list of indices.")
    if not isinstance(chains, list):
        raise ValueError("A saved move's buckets are not a list.")
    return tuple(bucketed), tuple(BucketChain.from_state(chain) for chain in chains)


@dataclass(frozen=True, slots=True)
class BucketedPlace:
    """A layout's place with its buckets resolved.

    :param relative: the place, relative to the root, buckets included.
    :param chains: each bucketed level's chain, the innermost first -- the order they are settled in, since an outer
        split moves the inner levels' folders whole.
    :param ungoverned: the first folder on its way that is split where the layout has no ``{buckets}``: nothing may be
        put there until a balance joins it (#681).
    """

    relative: PurePosixPath
    chains: tuple[BucketChain, ...]
    ungoverned: Path | None = None


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
        self.__left: Final[list[str]] = []

    @property
    def limit(self) -> int:
        """How many entries a folder holds before it splits, as clamped."""
        return self.__limit

    @property
    def left(self) -> tuple[str, ...]:
        """Why each entry that was to move was left where it is, in the order they were met."""
        return tuple(self.__left)

    def settle(self, layout_folder: Path, chain: Sequence[str]) -> None:
        """Settle a layout folder and the buckets a place went into below it, top-down, and every bucket a split
        fills.

        :param layout_folder: the folder of the level before ``{buckets}``.
        :param chain: the buckets below it the place went into; a temporary bucket by its name.
        :raises OSError: a folder could not be read, or a move failed.
        """
        folder, depth = layout_folder, 0
        while True:
            self.settle_folder(folder, depth)
            if depth == len(chain):
                return
            level = chain[depth]
            folder, depth = folder / (temporary_prefix(level) or level), depth + 1
            if not folder.is_dir():
                return

    def settle_folder(self, folder: Path, depth: int) -> None:
        """Split one folder when it is over the limit or a split of it is under way, then every bucket that took
        entries.

        :param folder: the folder.
        :param depth: its depth, 0 for the layout's own.
        :raises OSError: a folder could not be read, or a move failed.
        """
        if is_never_split(folder):
            return
        listing = BucketListing.of(folder, depth)
        split = is_split(folder)
        if not split:
            if not listing.temporaries and len(listing.entries) <= self.__limit:
                return
            LOG.info("%s holds %d entries, more than %d: splitting it.", folder, len(listing.entries), self.__limit)
        # in a folder already split, only a folder record put there by hand is named so
        if not self.__set_aside(folder, depth, listing):
            return
        if not split:
            (folder / BUCKETS_MARKER).touch()
        filled: set[tuple[str, ...]] = set()
        for prefix, temporary in listing.temporaries.items():
            filled |= self.__place_temporary(folder, depth, prefix, temporary)
        for entry in BucketListing.of(folder, depth).entries:
            prefix = bucket_prefix(entry.name, depth)
            if prefix is not None:
                filled |= self.__sweep(entry, folder, depth, prefix)
        for buckets in sorted(filled, key=lambda buckets: (len(buckets), buckets)):
            self.settle_folder(folder.joinpath(*buckets), depth + len(buckets))

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
            if prefix in listing.temporaries and (listing.temporaries[prefix] / entry.name).exists():
                self.__leave(entry, listing.temporaries[prefix])
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

    def __place_temporary(self, folder: Path, depth: int, prefix: str, temporary: Path) -> set[tuple[str, ...]]:
        """Rename a temporary bucket into place; when its bucket exists already, move what it holds there instead.

        :param folder: the split folder.
        :param depth: its depth.
        :param prefix: the bucket's name.
        :param temporary: the temporary bucket.
        :returns: the buckets that took entries, each by the buckets from ``folder`` down to it.
        """
        bucket = folder / prefix
        filled = {(prefix,)}
        if not bucket.exists():
            self.__checkpoint()
            self.__mover.move_folder(temporary, folder, prefix)
            return filled
        for entry in BucketListing.of(temporary, depth + 1).entries:
            filled |= self.__sweep(entry, folder, depth, prefix)
        try:
            temporary.rmdir()
        except OSError:
            LOG.warning("%s was left: it still holds files that are no record.", temporary, exc_info=True)
        return filled

    def __sweep(self, entry: BucketEntry, folder: Path, depth: int, prefix: str) -> set[tuple[str, ...]]:
        """Move an entry into the deepest bucket its name lands in: one level at a time, a folder named as long as the
        buckets of a bucket already split would be taken for one of them there (#681).

        :param entry: the entry.
        :param folder: the split folder.
        :param depth: its depth.
        :param prefix: the folder's bucket it goes into, or beneath.
        :returns: that bucket and those beneath it down to where the entry went, each by the buckets from ``folder``
            down to it, a temporary one by the bucket it is being built for.
        """
        bucket = folder / prefix
        beneath = bucket_of(bucket, entry.name, depth + 1)
        self.__move(entry, bucket.joinpath(*beneath.parts))
        chain = (prefix, *(temporary_prefix(level) or level for level in beneath.parts))
        return {chain[: end + 1] for end in range(len(chain))}

    def __leave(self, entry: BucketEntry, into: Path) -> None:
        """Say that an entry is left where it is, its name taken where it was to go.

        :param entry: the entry.
        :param into: the folder it was to go into.
        """
        LOG.warning("%s was left where it is: its name is taken in %s.", entry.path, into)
        self.__left.append(f"{entry.path}: its name is taken in {into}")

    def __move(self, entry: BucketEntry, into: Path) -> None:
        """Move one entry into a folder, keeping its name; one whose name is taken there is left where it is, said in
        the log, so one duplicate stops nothing else.

        :param entry: the entry.
        :param into: the folder.
        """
        if (into / entry.path.name).exists():
            self.__leave(entry, into)
            return
        self.__checkpoint()
        if entry.is_folder:
            self.__mover.move_folder(entry.path, into, entry.name)
        else:
            self.__mover.move_record(entry.path, into)
