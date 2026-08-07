"""Which resources under a folder still hold retained conversion backups, read without touching anything
(#193, [[acquisition-tooling#convert-mechanics]]).

`rehuco_core.tc_conversion_backups` answers that for **one** resource; this answers it for a catalog. A
bulk import (#192) leaves thousands of directories holding `.orig` files, and a surface offering to
revert or discard them has to find them first.

**Composed, not re-walked.** The tree walk is
:func:`~rehuco_core.rehu_catalog.enumerate_catalog_resources` and the per-resource read is
:func:`~rehuco_core.conversion_backups`; nothing here lists a directory itself, so this can never come to
a different answer than either of them. It says what it could not see for the same reason the walk does
(#245): a catalog that lists nothing and a catalog that would not list are the same sentence otherwise.

**A resource is here only if it still has backups.** Everything else under the root is examined and
dropped -- the answer is the work a caller could actually do, not an inventory of the catalog. How many
were looked at survives as :attr:`ConversionBackupsTreeScan.examined`, so a surface can say *142 of
9,847* rather than only *142*.

**Not a cache.** A scan is built on demand and discarded after the run; it has nothing to do with
`.rehudb`, and this module never writes one.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .rehu_catalog import CatalogCheckpoint, enumerate_catalog_resources
from .tc_conversion_backups import ConversionBackups, conversion_backups

ConversionBackupsProgress = Callable[[int], None]
"""Called with a running count of resources examined so far, once per record -- a real catalog is
thousands of them, so a caller needs to show it is moving. **Examined**, not found: a catalog where
nothing has backups left would otherwise report a motionless zero for its whole length."""


@dataclass(frozen=True, slots=True)
class ConversionBackupsTreeScan:
    """Every resource under a folder that still holds retained conversion backups (#193).

    :param root: the folder the walk started from.
    :param resources: one :class:`~rehuco_core.ConversionBackups` per resource that still has backups,
        in the walk's own order (sorted by path); a resource with none is not here at all.
    :param unreadable: the directories that would not list -- an offline mount branch costs its own
        subtree rather than the whole scan ([[mounts-and-storage#offline-mounts]]), and is named.
    :param examined: how many ``.rehu`` records were read, including the ones with no backups.
    """

    root: Path
    resources: tuple[ConversionBackups, ...]
    unreadable: tuple[Path, ...] = ()
    examined: int = 0

    @property
    def total_bytes(self) -> int:
        """What every retained backup here occupies -- the reclaimable total a discard would free."""
        return sum(backups.total_bytes for backups in self.resources)

    @property
    def total_files(self) -> int:
        """How many `.orig` files are retained across every resource here."""
        return sum(len(backups.backups) for backups in self.resources)

    @property
    def revertible(self) -> int:
        """How many of these could actually be reverted right now
        (:attr:`~rehuco_core.ConversionBackups.revertible`)."""
        return sum(1 for backups in self.resources if backups.revertible)

    @property
    def edited_since(self) -> int:
        """How many have been saved again since the conversion, so reverting would discard real edits."""
        return sum(1 for backups in self.resources if backups.edited_since)

    @property
    def tie_break(self) -> int:
        """How many had a screenshot tie-break, i.e. a recognized legacy screenshot that was backed up
        and never installed -- the rows #193 exists to review."""
        return sum(1 for backups in self.resources if backups.dropped_screenshots)


def scan_conversion_backups(
    root: Path, *, progress: ConversionBackupsProgress | None = None, checkpoint: CatalogCheckpoint | None = None
) -> ConversionBackupsTreeScan:
    """Find every resource under ``root`` that still holds retained conversion backups.

    :param root: the folder to walk.
    :param progress: called with a running count of resources examined so far, or ``None``; see
        :data:`ConversionBackupsProgress`. Whatever it raises is left to escape, so a caller can unwind
        a long scan from it.
    :param checkpoint: passed to the underlying catalog walk, which calls it once per directory before
        listing it -- how the walk itself is cancellable before a single record has been read. Whatever
        it raises is likewise left to escape.
    :returns: the scan; see :class:`ConversionBackupsTreeScan`.
    """
    return ConversionBackupsScanner(root, progress=progress, checkpoint=checkpoint).scan()


class ConversionBackupsScanner:  # pylint: disable=too-few-public-methods
    """Reads every resource under a folder for retained conversion backups (#193).

    :param root: the folder to walk.
    :param progress: called with a running count of resources examined so far, or ``None``.
    :param checkpoint: called once per directory by the underlying catalog walk, or ``None``.
    """

    def __init__(
        self,
        root: Path,
        *,
        progress: ConversionBackupsProgress | None = None,
        checkpoint: CatalogCheckpoint | None = None,
    ) -> None:
        self.__root: Final = root
        self.__progress: Final = progress
        self.__checkpoint: Final = checkpoint

    def scan(self) -> ConversionBackupsTreeScan:
        """Run the walk.

        :returns: the scan; see :func:`scan_conversion_backups`.
        """
        enumeration = enumerate_catalog_resources(self.__root, checkpoint=self.__checkpoint)
        found: list[ConversionBackups] = []
        for examined, rehu_path in enumerate(enumeration.resources, start=1):
            backups = conversion_backups(rehu_path)
            if backups.backups:
                found.append(backups)
            if self.__progress is not None:
                self.__progress(examined)
        return ConversionBackupsTreeScan(
            self.__root, tuple(found), tuple(enumeration.unreadable), len(enumeration.resources)
        )
