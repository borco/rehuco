"""Where the resources are: the recursive walk that finds `.rehu` records under a folder (#242).

The counterpart of `rehuco_core.rehu_content_files`, one level out. That module answers *what one
resource's content is*, starting from a record; this one answers *where the records are*, starting from
a folder somebody pointed at. The checksum sweep is its first caller and the catalog cache
([[data-model#scan-and-staleness]]) is the next, which is why it is named for the catalog rather than
for the sweep.

**It says what it could not see** (#245), in the shape `rehuco_core.rehu_content_files` already
established: an offline branch of a mount costs its own subtree and is *named*, rather than silently
reducing the answer -- because a catalog that lists nothing and a catalog that would not list are the
same sentence otherwise, and the second one is the lie. Whether that is fatal is the caller's to
decide, through :meth:`CatalogEnumeration.require_reachable`.

Core-side and GUI-free: no setting is read here, and a folder to start from is always a parameter.
"""

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .constants import REHU_SUFFIX
from .rehu_content_files import MAX_NAMED_UNREADABLE, ContentUnreachableError
from .rename_coordination import RenameCoordinator, ResourceLocation
from .resource_scoping import is_legacy_record_name, is_record_name

CatalogCheckpoint = Callable[[], None]
"""What a walk calls to ask whether it should still be running.

Called once per directory, immediately before its listing, and **never caught** -- the same contract
:data:`~rehuco_core.ChecksumCheckpoint` documents, for the same reason: a cancel that a walk swallowed
is a walk that cannot be stopped. Per directory rather than per entry because a listing is this walk's
unit of work, and a per-entry call would take a lock millions of times to buy nothing."""


@dataclass(frozen=True, slots=True)
class CatalogEnumeration:
    """What one catalog walk found, and what it could not see (#242, #245).

    The shape of :class:`~rehuco_core.ContentEnumeration`, deliberately: an unreachable resource
    directory and an unreachable catalog root are the same condition seen from two distances, and a
    caller that has learned one vocabulary should not have to learn a second.

    :param root: the folder the walk started from.
    :param resources: the ``.rehu`` paths found, in a stable order.
    :param unreadable: the directories that would not list, :attr:`root` itself included when the walk
        never started at all.
    """

    root: Path
    resources: list[Path]
    unreadable: tuple[Path, ...] = ()

    @property
    def reachable(self) -> bool:
        """Whether the root itself listed -- the difference between *no resources* and *away*."""
        return self.root not in self.unreadable

    @property
    def complete(self) -> bool:
        """Whether every directory under the root listed, so :attr:`resources` is the whole catalog."""
        return not self.unreadable

    def require_reachable(self) -> None:
        """Refuse when the root itself could not be read.

        The one refusal a sweep makes: a branch it cannot list costs that branch's resources and is
        reported, while a root it cannot list means the run has nothing to say at all
        ([[mounts-and-storage#offline-mounts]]).

        :raises ContentUnreachableError: the root would not list.
        """
        if not self.reachable:
            raise ContentUnreachableError(f"The folder could not be read: {self.root}")

    def unreadable_text(self) -> str:
        """The unreadable directories, for a sentence a reader can act on.

        :returns: up to :data:`~rehuco_core.rehu_content_files.MAX_NAMED_UNREADABLE` of them, and a
            count of whatever is left.
        """
        named = ", ".join(str(directory) for directory in self.unreadable[:MAX_NAMED_UNREADABLE])
        remaining = len(self.unreadable) - MAX_NAMED_UNREADABLE
        return named if remaining <= 0 else f"{named} (and {remaining} more)"


@dataclass(frozen=True, slots=True)
class CatalogDirectory:
    """One directory a walk listed, and the records it found there (#372).

    What :meth:`CatalogScanner.walk` hands back per listing, so a caller can act on a directory's records
    as soon as they are known -- the catalog cache parses on find ([[data-model#scan-and-staleness]]) --
    rather than after the whole tree has been walked.

    Holds **locations**, not paths, for the reason the walk tracks its pending directories: a caller reading
    the records one hold at a time may meet a rename between two of them, and a location answers where a
    record is now rather than where it was listed.

    :param location: the directory.
    :param record_locations: the records in it, in path order.
    :param listed: whether it listed at all; one that would not has no records, and is named rather than
        read as empty (#245).
    """

    location: ResourceLocation
    record_locations: tuple[ResourceLocation, ...] = ()
    listed: bool = True

    @property
    def path(self) -> Path:
        """Where the directory is now."""
        return self.location.path

    @property
    def records(self) -> tuple[Path, ...]:
        """Where its records are now."""
        return tuple(location.path for location in self.record_locations)


class CatalogScanner:
    """Finds every ``.rehu`` record under a folder ([[data-model#resource-scoping]], #242).

    **Every record counts, at any depth** -- a directory-scoped ``info.rehu``, a file-scoped
    ``foo.rehu``, several of either in one directory. A record's own directory is descended like any
    other, because a nested record is not a scan boundary ([[data-model#resource-scoping]]) and the
    sweep is asked to find it. Type-directed descent -- a tutorial terminating the walk where a
    collection does not ([[data-model#scan-and-staleness]]) -- would mean reading every record to decide
    where to stop, and belongs with the catalog cache that has somewhere to keep what it read.

    **A nested resource's content is verified once, by the record that covers it** (#254). Under #226 a
    ``sub/info.rehu``'s content used to be the enclosing ``info.rehu``'s as well, so a sweep that found both
    records hashed ``sub/video.mp4`` into each of them. Scanning and *covering* are different questions:
    this walk still descends past a record, because the sweep is asked to find the nested one, while the
    content walk stops there, because that record covers its own directory. What made the overlap
    defensible was that the outer record already held an entry for those bytes and leaving it unverified
    would be a hole -- and under exclusive coverage it holds none.

    **It excludes nothing.** ``EXCLUDED_FILE_PATTERNS`` is a rule about *content* files, matched against
    junk a browser or a Mac left behind; no ``.rehu`` can match one, and letting the pattern list decide
    which resources a sweep can see would make an unrelated settings edit hide resources from
    verification. The list is handed to each resource's run instead, where it means something.

    **A symlinked directory is never descended**, matching `rehuco_core.rehu_content_files`: one
    pointing at an ancestor would loop the walk forever, and one pointing sideways would sweep the same
    resources twice under two names. A symlink *to* a ``.rehu`` file is a record like any other, because
    it is a file the caller can open.

    **It never blocks a rename**, given a coordinator ([[data-model#cache-schema]], #372). Each listing is
    one chunk inside :meth:`~rehuco_core.RenameCoordinator.holding`, the handle closed before the block
    ends, so a rename waits at most one directory read; and the directories still to visit are tracked
    locations, so one renamed mid-walk is listed under its new name rather than reported unreadable.

    **A legacy record counts where no** ``.rehu`` **covers it**, when asked for (#372). The catalog cache
    lists a ``.tc`` a conversion has not reached yet, but not one left beside the ``.rehu`` that replaced
    it: a ``foo.tc`` is covered by a ``foo.rehu`` in the same directory, the stem compared case-folded as
    the conversion plan compares it. Coverage stops at the directory, so a nested ``sub/info.tc`` under an
    ``info.rehu`` is a resource of its own.

    :param root: the folder to walk.
    :param checkpoint: called once per directory before its listing, or ``None`` for a walk nobody can
        stop.
    :param coordinator: the rename barrier each listing is held under, or ``None`` for a walk that holds
        nothing across renames -- the checksum sweep's, which reads each record later under its own hold.
    :param include_legacy: whether a ``.tc`` no ``.rehu`` covers is a record too.
    """

    def __init__(
        self,
        root: Path,
        *,
        checkpoint: CatalogCheckpoint | None = None,
        coordinator: RenameCoordinator | None = None,
        include_legacy: bool = False,
    ) -> None:
        self.__root: Final = root
        self.__checkpoint: Final = checkpoint
        self.__coordinator: Final = coordinator
        self.__include_legacy: Final = include_legacy

    def scan(self) -> CatalogEnumeration:
        """Walk :attr:`root`, collecting the records under it and the directories that would not list.

        :returns: what the walk found; see :func:`enumerate_catalog_resources` for the full order and
            failure-handling contract.
        """
        resources: list[Path] = []
        unreadable: list[Path] = []
        for directory in self.walk():
            if directory.listed:
                resources.extend(directory.records)
            else:
                unreadable.append(directory.path)
        return CatalogEnumeration(self.__root, sorted(resources, key=str), tuple(unreadable))

    def walk(self) -> Iterator[CatalogDirectory]:
        """Walk :attr:`root` one listing at a time, the root first.

        Nothing is held while the caller has a directory in hand: the listing is closed before it is
        yielded, so whatever the caller does with its records -- open each under a hold of its own -- never
        overlaps it, and a generator left suspended holds nothing a rename would wait for.

        :yields: one :class:`CatalogDirectory` per directory visited, one that would not list included.
        """
        pending = [self.__located(self.__root)]
        while pending:
            if self.__checkpoint is not None:
                self.__checkpoint()
            subdirectories: list[Path] = []
            # tracked before the hold ends: a rename waiting on it must find every path it would move
            with self.__holding():
                current = pending.pop()
                records = self.__read_directory(current.path, subdirectories)
                pending.extend(self.__located(subdirectory) for subdirectory in subdirectories)
                found = tuple(self.__located(record) for record in records or ())
            yield CatalogDirectory(current, found, listed=records is not None)

    def __located(self, path: Path) -> ResourceLocation:
        """A directory still to visit, followed across renames when there is a coordinator to follow it.

        :param path: the directory.
        :returns: its location -- tracked, or a plain one nothing will ever move.
        """
        return self.__coordinator.track(path) if self.__coordinator is not None else ResourceLocation(path)

    def __holding(self) -> AbstractContextManager[None]:
        """The hold one listing runs under, or none without a coordinator."""
        return self.__coordinator.holding() if self.__coordinator is not None else nullcontext()

    def __is_wanted(self, filename: str) -> bool:
        """Whether a file of this name is a record this walk collects."""
        if self.__include_legacy:
            return is_record_name(filename)
        return os.path.splitext(filename)[1].lower() == REHU_SUFFIX

    @staticmethod
    def __uncovered(names: list[str]) -> list[str]:
        """Drop each ``.tc`` that a same-stem ``.rehu`` in the same listing covers.

        :param names: one directory's record names.
        :returns: the names that are resources of their own.
        """
        rehu_stems = {os.path.splitext(name)[0].casefold() for name in names if not is_legacy_record_name(name)}
        return [
            name
            for name in names
            if not is_legacy_record_name(name) or os.path.splitext(name)[0].casefold() not in rehu_stems
        ]

    def __read_directory(self, directory: Path, subdirectories: list[Path]) -> tuple[Path, ...] | None:
        """Read one directory, appending its subdirectories to ``subdirectories`` for later.

        :func:`os.scandir` rather than :meth:`~pathlib.Path.iterdir`, and for the reason
        `rehuco_core.rehu_content_files` gives at length: the listing already knows whether an entry is
        a directory, where ``iterdir`` would cost a ``stat`` per entry to learn it -- and a catalog walk
        crosses far more directories than a single resource's does.

        A directory that will not list is reported rather than swallowed, whatever the reason: an
        unmapped drive raises :class:`FileNotFoundError` where a refused share raises
        :class:`PermissionError`, and both take their whole subtree with them (#245).

        :param directory: the directory to read.
        :param subdirectories: where its subdirectories go, appended to in place.
        :returns: the records in that one directory, sorted, or ``None`` when it would not list.
        """
        names: list[str] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        subdirectories.append(directory / entry.name)
                    elif entry.is_file() and self.__is_wanted(entry.name):
                        names.append(entry.name)
        except OSError:
            subdirectories.clear()
            return None
        return tuple(sorted((directory / name for name in self.__uncovered(names)), key=str))


def enumerate_catalog_resources(root: Path, *, checkpoint: CatalogCheckpoint | None = None) -> CatalogEnumeration:
    """Find every ``.rehu`` record under ``root`` -- where the resources are, not what they hold.

    :param root: the folder to walk.
    :param checkpoint: called once per directory before its listing, so a long walk over a mount can be
        cancelled; whatever it raises is left to escape.
    :returns: the records, sorted by path so an interrupted walk resumes over the same order it left,
        **and the directories that would not list**. An unreadable branch contributes nothing rather
        than raising, but it is named, so no caller has to mistake an offline mount for an empty
        catalog (#245).
    """
    return CatalogScanner(root, checkpoint=checkpoint).scan()
