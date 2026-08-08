"""Dry-run plan for bulk `.tc` -> `.rehu` conversion: what converting a tree would do, writing nothing
(#191, [[acquisition-tooling#tc-to-rehu]]).

Walks a folder tree for legacy `.tc` resources and builds one plan record per resource, composed
entirely from existing read-only pieces -- :func:`~rehuco_core.tc_document.TcDocument.load`/
:meth:`~rehuco_core.tc_document.TcDocument.to_rehu_data`, :func:`~rehuco_core.tc_screenshots.scan_tc_screenshots`,
and :func:`~rehuco_core.tc_conversion.originals_to_back_up` -- so a plan can never drift from what an
actual conversion would do. This is the module `rehuco_agent`'s bulk import wizard (#192) runs before
asking for confirmation; nothing here writes, renames, or deletes anything.

**Every `.tc` found is a conversion target, at any depth.** A directory holding one is a resource, but a
nested `.tc` is not a scan boundary ([[data-model#resource-scoping]], matching
`rehuco_core.rehu_catalog.CatalogScanner`): a tc4 **collection** is a parent record over member
directories, and stopping at the first `.tc` would plan the parent and drop every member.

**Not a cache.** A plan is built on demand and discarded after the run; it has nothing to do with
`.rehudb`, and this module never writes one.
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from .constants import LEGACY_SUFFIX, REHU_SUFFIX
from .plugins import DEFAULT_UNKNOWN_USERNAME
from .rehu_document import RehuFormatError
from .rehu_format import CORE_BLOCK_KEY
from .tc_conversion import originals_to_back_up
from .tc_conversion_backups import backup_path
from .tc_document import TcDocument
from .tc_screenshots import ScreenshotRename, scan_tc_screenshots

CONSUMED_TC_KEYS: Final = frozenset(
    {
        "type",
        "title",
        "publisher",
        "url",
        "description",
        "author",
        "tags",
        "extraTags",
        "released",
        "original_size",
        "current_size",
        "collection",
        "collection_index",
        "learning_paths",
        "complete",
        "online",
        "duration",
        "level",
        "rating",
        "keep",
        "todo",
        "viewed",
    }
)
"""Every key :class:`~rehuco_core.tc_document.TcDocument` reads, whatever the resource's type -- the
vocabulary the mapper knows, not the subset a given type actually keeps. A key outside this set is one
the ``.tc`` carries that no mapping consumes at all, which is what :attr:`TcConversionPlan.unmapped_keys`
flags; a key a *type* happens to drop (e.g. a Collection's stray ``rating``) is not, since the mapper did
read it and made a deliberate choice about it ([[field-schema#resource-types]])."""

CLUSTER_WINDOW_SECONDS: Final = 60
"""How close two `.tc` mtimes must sit to count as the same restore/copy event."""

CLUSTER_MIN_SIZE: Final = 3
"""How many resources must share a :data:`CLUSTER_WINDOW_SECONDS` window before it reads as a wall of
identical timestamps rather than two tutorials genuinely finished minutes apart."""

TcConversionPlanProgress = Callable[[int], None]
"""Called with a running count of resources planned so far, once per resource -- a real catalog is
thousands of them, so a caller needs to show it is moving."""


@dataclass(frozen=True, slots=True)
class TcConversionPlan:  # pylint: disable=too-many-instance-attributes
    """One `.tc` resource's dry-run conversion plan -- what converting it would do, read without
    touching anything (#191).

    :param tc_path: the `.tc` file this plan is for.
    :param rehu_path: the `.rehu` the conversion would write.
    :param data: the mapped `.rehu`-shaped payload :meth:`~rehuco_core.tc_document.TcDocument.to_rehu_data`
        produced, in memory -- carries no `id`/`created`/`updated`, since those are an actual
        conversion's to mint, not a plan's to guess.
    :param renames: the screenshot rename plan (:func:`~rehuco_core.tc_screenshots.scan_tc_screenshots`).
    :param tie_break: two or more files resolved to the same slot in :attr:`renames`; the losers will
        not be installed.
    :param rehu_exists: the target `.rehu` already exists -- blocked; conversion would need overwrite.
    :param stale_backup: a `.orig` sibling already exists for something the conversion would back up --
        blocked by the forward converter's stale-backup guard.
    :param size_unparsed: the `.tc` carried `original_size`/`current_size` but the value would not
        parse, so the field is silently omitted rather than converted.
    :param duration_present: the mapped payload carries `original_duration` -- leaked from tc4's own
        `duration` and advisory until a real scan overwrites it ([[acquisition-tooling#legacy-parsing]]).
    :param unmapped_keys: `.tc` keys the mapper does not consume, sorted.
    :param suspect_mtime: the mtime that would seed `created`/`updated` looks unreliable -- part of a
        wall of near-identical timestamps across this run, the signature of a NAS restore, bulk copy, or
        archive extraction clobbering it.
    """

    tc_path: Path
    rehu_path: Path
    data: dict[str, Any]
    renames: tuple[ScreenshotRename, ...]
    tie_break: bool
    rehu_exists: bool
    stale_backup: bool
    size_unparsed: bool
    duration_present: bool
    unmapped_keys: tuple[str, ...]
    suspect_mtime: bool

    @property
    def blocked(self) -> bool:
        """Whether this resource cannot convert as planned: the target exists, or a stale backup is in
        the way."""
        return self.rehu_exists or self.stale_backup

    @property
    def flagged(self) -> bool:
        """Whether anything here is worth a human's attention, short of being outright blocked."""
        return bool(
            self.tie_break or self.size_unparsed or self.duration_present or self.unmapped_keys or self.suspect_mtime
        )


@dataclass(frozen=True, slots=True)
class TcConversionTreePlan:
    """What a bulk conversion of every `.tc` under a folder would do, read without touching anything.

    :param root: the folder the walk started from.
    :param resources: one :class:`TcConversionPlan` per `.tc` resource found, sorted by path.
    :param unreadable: what the walk could not see: directories that would not list -- an offline
        mount branch costs its own subtree rather than the whole walk
        ([[mounts-and-storage#offline-mounts]]) -- and `.tc` files that would not read or parse, each
        costing its own record rather than the whole plan ([[data-model#write-integrity]]'s
        refuse-don't-crash discipline, at plan scale).
    """

    root: Path
    resources: tuple[TcConversionPlan, ...]
    unreadable: tuple[Path, ...] = ()

    @property
    def clean(self) -> int:
        """How many resources would convert with nothing to flag or block."""
        return sum(1 for plan in self.resources if not plan.blocked and not plan.flagged)

    @property
    def flagged(self) -> int:
        """How many resources would convert but are worth a look first."""
        return sum(1 for plan in self.resources if not plan.blocked and plan.flagged)

    @property
    def blocked(self) -> int:
        """How many resources a bulk run would have to skip."""
        return sum(1 for plan in self.resources if plan.blocked)


def plan_tc_conversion(
    root: Path, *, username: str = DEFAULT_UNKNOWN_USERNAME, progress: TcConversionPlanProgress | None = None
) -> TcConversionTreePlan:
    """Walk ``root`` and report what converting every `.tc` under it would do, writing nothing.

    :param root: the folder to walk.
    :param username: the identity an actual conversion's imported per-user flags would be filed under;
        see :func:`~rehuco_core.tc_conversion.convert_tc`.
    :param progress: called with a running count of resources planned so far, or ``None``.
    :returns: the plan; see :class:`TcConversionTreePlan`.
    """
    return TcConversionPlanner(root, username=username, progress=progress).plan()


class TcConversionPlanner:  # pylint: disable=too-few-public-methods
    """Builds a dry-run plan for every `.tc` resource under a folder ([[acquisition-tooling#tc-to-rehu]], #191).

    :param root: the folder to walk.
    :param username: the identity an actual conversion's imported per-user flags would be filed under.
    :param progress: called with a running count of resources planned so far, or ``None``.
    """

    def __init__(
        self, root: Path, *, username: str = DEFAULT_UNKNOWN_USERNAME, progress: TcConversionPlanProgress | None = None
    ) -> None:
        self.__root: Final = root
        self.__username: Final = username
        self.__progress: Final = progress

    def plan(self) -> TcConversionTreePlan:
        """Run the walk.

        :returns: the plan; see :func:`plan_tc_conversion`.
        """
        entries: list[tuple[TcConversionPlan, float]] = []
        unreadable: list[Path] = []
        pending = [self.__root]
        count = 0
        while pending:
            directory = pending.pop()
            listing = self.__listed(directory)
            if listing is None:
                unreadable.append(directory)
                continue
            tc_files, subdirectories = listing
            pending.extend(subdirectories)
            for tc_path in sorted(tc_files):
                try:
                    entries.append(self.__planned(tc_path))
                except OSError, RehuFormatError:
                    # a `.tc` that will not read or parse costs its own record, not the whole plan --
                    # the single-document path refuses it into a locked stub, and a bulk dry-run has
                    # even less business crashing over it than an editor does
                    unreadable.append(tc_path)
                    continue
                count += 1
                if self.__progress is not None:
                    self.__progress(count)
        resources = self.__with_suspect_mtimes(entries)
        sorted_resources = tuple(sorted(resources, key=lambda plan: str(plan.tc_path)))
        return TcConversionTreePlan(self.__root, sorted_resources, tuple(unreadable))

    @staticmethod
    def __listed(directory: Path) -> tuple[list[Path], list[Path]] | None:
        """List one directory's `.tc` files and subdirectories, without descending into either.

        Every subdirectory is walked regardless of whether this directory holds a `.tc`: a nested `.tc`
        is not a scan boundary ([[data-model#resource-scoping]]), matching
        `rehuco_core.rehu_catalog.CatalogScanner`. A directory symlink is never descended, for the same
        reason that scanner gives -- one pointing at an ancestor would loop forever, one pointing
        sideways would plan the same resource twice.

        :param directory: the directory to read.
        :returns: ``(tc_files, subdirectories)``, or ``None`` when the directory would not list (an
            offline mount branch, [[mounts-and-storage#offline-mounts]]).
        """
        tc_files: list[Path] = []
        subdirectories: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        subdirectories.append(directory / entry.name)
                    elif entry.is_file() and os.path.splitext(entry.name)[1].lower() == LEGACY_SUFFIX:
                        tc_files.append(directory / entry.name)
        except OSError:
            return None
        return tc_files, subdirectories

    def __planned(self, tc_path: Path) -> tuple[TcConversionPlan, float]:
        """Build one resource's plan record and the mtime that would seed it, without writing anything.

        :param tc_path: the `.tc` file to plan.
        :returns: the plan (with :attr:`~TcConversionPlan.suspect_mtime` not yet decided -- that needs
            every resource's mtime, filled in by :meth:`__with_suspect_mtimes`) and its mtime.
        """
        document = TcDocument.load(tc_path)
        renames = tuple(scan_tc_screenshots(tc_path.parent, tc_path.stem))
        data = document.to_rehu_data(username=self.__username)
        core = data[CORE_BLOCK_KEY]
        type_block = data.get(core["type"], {})
        target = tc_path.with_suffix(REHU_SUFFIX)
        originals = originals_to_back_up(tc_path, target, renames)
        plan = TcConversionPlan(
            tc_path=tc_path,
            rehu_path=target,
            data=data,
            renames=renames,
            tie_break=any(len(rename.recognized_filenames) > 1 for rename in renames),
            rehu_exists=target.exists(),
            stale_backup=any(backup_path(original).exists() for original in originals),
            size_unparsed=any(key in document.data and key not in core for key in ("original_size", "current_size")),
            duration_present="original_duration" in type_block,
            unmapped_keys=tuple(sorted(key for key in document.data if key not in CONSUMED_TC_KEYS)),
            suspect_mtime=False,
        )
        return plan, tc_path.stat().st_mtime

    @staticmethod
    def __with_suspect_mtimes(entries: Sequence[tuple[TcConversionPlan, float]]) -> list[TcConversionPlan]:
        """Flag every resource whose mtime sits inside a run's worth of near-identical ones.

        A sliding window over the mtimes sorted by value: any run of at least :data:`CLUSTER_MIN_SIZE`
        falling within :data:`CLUSTER_WINDOW_SECONDS` of each other is a cluster, and every resource in
        it is flagged -- the "wall of identical restore-date timestamps" the mtime seed can't tell
        apart from real activity on its own (#191's notes).

        :param entries: each resource's plan (with :attr:`~TcConversionPlan.suspect_mtime` unset) and
            its mtime, in the order :meth:`__planned` produced them.
        :returns: the plans, in the same order, with :attr:`~TcConversionPlan.suspect_mtime` decided.
        """
        order = sorted(range(len(entries)), key=lambda index: entries[index][1])
        suspect = [False] * len(entries)
        start = 0
        for end, entry_index in enumerate(order):
            while entries[entry_index][1] - entries[order[start]][1] > CLUSTER_WINDOW_SECONDS:
                start += 1
            if end - start + 1 >= CLUSTER_MIN_SIZE:
                for index in range(start, end + 1):
                    suspect[order[index]] = True
        return [replace(plan, suspect_mtime=flag) for (plan, _), flag in zip(entries, suspect, strict=True)]
