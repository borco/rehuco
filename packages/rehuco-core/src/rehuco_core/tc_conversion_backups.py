"""The `.orig` backups a `.tc` conversion keeps: what they would restore, undoing the conversion from
them, and discarding them ([[acquisition-tooling#convert-mechanics]], #190).

This module owns *what a backup is* -- the `.orig` naming, and the rename-back that turns one into its
original again. :mod:`rehuco_core.tc_conversion` builds on it, so the same rename-back serves both its
in-run rollback and the after-the-fact revert here: a conversion that fails half-way and a conversion
undone a week later put the directory back the same way.

**A revert deletes the written `.rehu`**, so any edit made since the conversion is lost with it. That is
the honest meaning of *undo the conversion*, and it is why :attr:`ConversionBackups.edited_since` exists
-- the caller is expected to warn before calling :func:`revert_conversion`.

Backups are enumerated as **the directory's `.orig` siblings**, not by stem: a legacy screenshot is
named ``cover.jpg`` or ``sample-01.jpg``, carrying nothing that ties it back to the resource it belongs
to. That is exact for the directory-scoped resources tc4 catalogs are made of (one resource, one
directory) and it is why a revert names the whole directory rather than a file.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .constants import IMAGE_EXTENSIONS
from .rehu_document import RehuDocument, RehuFormatError
from .rehu_screenshots import scan_rehu_screenshot_files

BACKUP_SUFFIX: Final = ".orig"
"""Appended to an original's full name (``info.tc`` -> ``info.tc.orig``) before anything new is written
over it -- the conversion's never-overwrite, never-delete-then-write contract."""

STAGED_SUFFIX: Final = ".reverting"
"""Appended, for the length of a revert, to each file the conversion *wrote* (``info.rehu`` ->
``info.rehu.reverting``). Nothing is deleted until every backup is back under its original name, so a
revert that fails part-way can put the converted state back exactly as it found it -- and a restore
target the conversion had itself overwritten is free by the time its backup needs it."""

LEGACY_SUFFIX: Final = ".tc"
"""The source format a conversion consumes; its backup is what marks a directory as revertible."""


def is_conversion_backup(filename: str) -> bool:
    """Whether ``filename`` names one of a conversion's retained backups.

    The one predicate both readers of that definition ask: the inventory here, listing what a revert
    would restore, and the content walk (:mod:`rehuco_core.rehu_content_files`), keeping a resource's
    backups out of the content they are backups *of* (#253). A bulk import retains them by default
    ([[acquisition-tooling#convert-mechanics]]), so counting them would put each converted resource's own
    ``info.tc.orig`` in its first checksum baseline, and discarding the backups afterwards -- the
    encouraged cleanup step -- would then report a missing file for every resource in the catalog.

    **Any ``.orig`` sibling**, never one matched against a record's stem, for the reason the module
    docstring gives: a legacy screenshot is named ``cover.jpg`` or ``sample-01.jpg`` and carries nothing
    tying it back to its resource. Following that one rule is what keeps the two sets identical by
    construction -- what a revert holds is exactly what the content walk skips.

    Matched exactly rather than case-insensitively, unlike the junk globs a content walk applies to names
    *other* tools wrote: this suffix is one this app appends itself, and folding case would take a
    ``render.blend.ORIG`` out of a measurement while leaving it to no revert at all.

    :param filename: a file's name, not its path.
    :returns: whether it is a retained backup.
    """
    return filename.endswith(BACKUP_SUFFIX)


def backup_path(original: Path) -> Path:
    """The ``.orig`` sibling for ``original``.

    :param original: the file being backed up.
    :returns: ``original`` with :data:`BACKUP_SUFFIX` appended to its full name.
    """
    return original.with_name(original.name + BACKUP_SUFFIX)


def original_path(backup: Path) -> Path:
    """The name ``backup`` was renamed from.

    :param backup: a ``.orig`` sibling.
    :returns: ``backup`` with :data:`BACKUP_SUFFIX` stripped from its full name.
    :raises ValueError: ``backup`` is not a ``.orig`` sibling.
    """
    if not backup.name.endswith(BACKUP_SUFFIX):
        raise ValueError(f"{backup} is not a {BACKUP_SUFFIX} backup.")
    return backup.with_name(backup.name[: -len(BACKUP_SUFFIX)])


def restore_backup(backup: Path) -> Path:
    """Rename one ``.orig`` backup back to its original name.

    The single rename-back both undo paths run: :class:`~rehuco_core.tc_conversion.TcConverter`'s
    rollback while a conversion is failing, and :func:`revert_conversion` long after one succeeded.

    :param backup: the ``.orig`` sibling to restore.
    :returns: the path it now sits at.
    """
    original = original_path(backup)
    backup.rename(original)
    return original


@dataclass(frozen=True, slots=True)
class ConversionBackups:  # pylint: disable=too-many-instance-attributes
    """What one directory's retained backups would restore, read without touching anything (#190).

    :param rehu_path: the converted ``.rehu`` a revert would delete.
    :param backups: every ``.orig`` sibling, sorted by name.
    :param total_bytes: what those backups occupy, for a caller offering to discard them.
    :param written: the files the conversion wrote and a revert therefore deletes -- the ``.rehu`` and
        its ``<stem>NN`` screenshots.
    :param obstructions: restore targets already occupied by a file a revert does *not* delete -- a
        legacy name the user has since put back by hand. Any one of these refuses the whole revert.
    :param legacy_restored: where the backed-up ``.tc`` would land, or ``None`` when no such backup is
        here -- in which case this directory holds no revertible conversion, whatever else it holds.
    :param edited_since: whether the ``.rehu`` has been written again since the conversion wrote it,
        i.e. whether reverting discards real edits.
    :param converted: when the conversion wrote the ``.rehu``, read off its ``created`` stamp
        ([[field-schema#record-timestamps]]) -- empty when the file is gone or will not read. A
        conversion mints that stamp, so it dates the conversion and not the resource.
    """

    rehu_path: Path
    backups: tuple[Path, ...]
    total_bytes: int
    written: tuple[Path, ...]
    obstructions: tuple[Path, ...]
    legacy_restored: Path | None
    edited_since: bool
    converted: str

    @property
    def dropped_screenshots(self) -> int:
        """How many recognized legacy screenshots the conversion backed up and never installed -- the
        losers of a tie-break ([[acquisition-tooling#screenshot-schemes]]).

        Derived from what is already here rather than re-scanned: every recognized screenshot is backed
        up, winners and losers alike, and only a winner is installed under its ``<stem>NN`` name, so the
        difference between the two counts *is* the drop. Re-running
        :func:`~rehuco_core.scan_tc_screenshots` could not answer it anyway -- after a conversion the
        legacy names all end in :data:`BACKUP_SUFFIX`, which no scheme recognizes.

        :returns: the number of dropped screenshots, ``0`` when the tie-break dropped nothing.
        """
        backed_up = sum(1 for backup in self.backups if original_path(backup).suffix.lower() in IMAGE_EXTENSIONS)
        installed = sum(1 for path in self.written if path != self.rehu_path)
        return max(0, backed_up - installed)

    @property
    def revertible(self) -> bool:
        """Whether :func:`revert_conversion` would run: a backed-up ``.tc`` is here and every restore
        target is free."""
        return self.legacy_restored is not None and not self.obstructions

    @property
    def restores(self) -> tuple[Path, ...]:
        """Where each of :attr:`backups` would land, in the same order."""
        return tuple(original_path(backup) for backup in self.backups)


def conversion_backups(rehu_path: Path) -> ConversionBackups:
    """Report what reverting ``rehu_path``'s conversion would restore, changing nothing.

    :param rehu_path: the converted ``.rehu``.
    :returns: the inventory; see :class:`ConversionBackups`.
    """
    return ConversionReverter(rehu_path).inventory()


def revert_conversion(rehu_path: Path) -> ConversionBackups:
    """Undo the conversion that produced ``rehu_path``: delete what it wrote, restore what it renamed.

    Refuses rather than half-reverts -- if no backed-up ``.tc`` is here, or a restore target is occupied
    by a file this would not delete, nothing on disk is touched. A failure part-way puts the converted
    state back and re-raises, so the directory is never left split between the two.

    **The written ``.rehu`` is deleted**, discarding any edit made since the conversion; check
    :attr:`ConversionBackups.edited_since` first.

    :param rehu_path: the converted ``.rehu``.
    :returns: the inventory the revert ran from -- what was restored, and what was deleted.
    :raises FileNotFoundError: no backed-up ``.tc`` sits beside ``rehu_path``.
    :raises FileExistsError: a restore target is occupied, or a leftover ``.reverting`` file from an
        interrupted revert is in the way.
    """
    return ConversionReverter(rehu_path).revert()


def discard_conversion_backups(rehu_path: Path) -> tuple[Path, ...]:
    """Delete every retained backup beside ``rehu_path``, making the conversion permanent.

    :param rehu_path: the converted ``.rehu``.
    :returns: the backups deleted, sorted by name.
    """
    return ConversionReverter(rehu_path).discard()


class ConversionReverter:
    """Undoes -- or discards -- one completed conversion's retained backups (#190).

    The inverse of :class:`~rehuco_core.tc_conversion.TcConverter` and shaped like it: **plan** (read the
    directory, decide whether the revert can run at all) then **replace** (move what the conversion wrote
    aside, rename every backup back, and only then delete what was moved aside). Nothing is deleted while
    a rename can still fail, so a failure part-way rolls back to the converted state.

    :param rehu_path: the converted ``.rehu``.
    """

    __UNREADABLE_UPDATED: Final = "?"
    """Stands in for the ``updated`` of a ``.rehu`` that is there but will not read, so
    :meth:`__timestamps` reports a pair that has drifted while leaving ``created`` empty -- the caller
    warns before reverting, and shows no conversion date it cannot actually vouch for."""

    def __init__(self, rehu_path: Path) -> None:
        self.__rehu_path: Final = rehu_path

    def inventory(self) -> ConversionBackups:
        """Read what a revert would do, touching nothing.

        :returns: the inventory; see :class:`ConversionBackups`.
        """
        backups = self.__backups()
        written = self.__written()
        legacy = self.__rehu_path.with_suffix(LEGACY_SUFFIX)
        restores = [original_path(backup) for backup in backups]
        created, updated = self.__timestamps()
        return ConversionBackups(
            rehu_path=self.__rehu_path,
            backups=backups,
            total_bytes=sum(self.__size(backup) for backup in backups),
            written=written,
            obstructions=tuple(path for path in restores if path.exists() and path not in written),
            legacy_restored=legacy if legacy in restores else None,
            edited_since=created != updated,
            converted=created,
        )

    def revert(self) -> ConversionBackups:
        """Run the full plan-then-replace sequence.

        :returns: the inventory the revert ran from.
        :raises FileNotFoundError: see :func:`revert_conversion`.
        :raises FileExistsError: see :func:`revert_conversion`.
        """
        inventory = self.inventory()
        if inventory.legacy_restored is None:
            raise FileNotFoundError(backup_path(self.__rehu_path.with_suffix(LEGACY_SUFFIX)))
        if inventory.obstructions:
            raise FileExistsError(inventory.obstructions[0])
        staged = self.__staged(inventory.written)
        restored: dict[Path, Path] = {}
        try:
            for backup in inventory.backups:
                restored[restore_backup(backup)] = backup
        except Exception:
            self.__undo(restored, staged)
            raise
        for staging in staged.values():
            staging.unlink(missing_ok=True)
        return inventory

    def discard(self) -> tuple[Path, ...]:
        """Delete every retained backup.

        :returns: the backups deleted, sorted by name.
        """
        backups = self.__backups()
        for backup in backups:
            backup.unlink(missing_ok=True)
        return backups

    def __backups(self) -> tuple[Path, ...]:
        """Every ``.orig`` sibling in the resource's directory, sorted by name.

        :returns: the backups; empty when the directory is missing or unreadable (an offline mount,
            [[mounts-and-storage#offline-mounts]]) -- which reads as *nothing to revert*, and is why a
            revert refuses rather than assuming an empty directory means a discarded-originals run.
        """
        try:
            siblings = list(self.__rehu_path.parent.iterdir())
        except OSError:
            return ()
        return tuple(sorted((s for s in siblings if is_conversion_backup(s.name)), key=lambda s: s.name))

    def __written(self) -> tuple[Path, ...]:
        """What the conversion wrote: the ``.rehu`` and the ``<stem>NN`` screenshots it installed.

        :returns: the existing ones, ``.rehu`` first.
        """
        screenshots = scan_rehu_screenshot_files(self.__rehu_path.parent, self.__rehu_path.stem)
        rehu = [self.__rehu_path] if self.__rehu_path.exists() else []
        return tuple(rehu + screenshots)

    def __size(self, backup: Path) -> int:
        """One backup's size on disk.

        :param backup: the ``.orig`` sibling to measure.
        :returns: its byte count, or ``0`` when it cannot be stat'd -- a total is a caller's hint about
            reclaimable space, not a number worth failing an inventory over.
        """
        try:
            return backup.stat().st_size
        except OSError:
            return 0

    def __timestamps(self) -> tuple[str, str]:
        """The ``.rehu``'s ``created`` and ``updated`` stamps, in one read.

        A conversion seeds ``created`` and ``updated`` with the same stamp
        ([[field-schema#record-timestamps]]) and a changed save refreshes ``updated`` alone (#142), so the
        two having drifted apart *is* the edit -- no mtime comparison, which a backup's preserved mtime
        could not answer anyway.

        Both answers come from the one load, so :attr:`ConversionBackups.converted` costs nothing beyond
        the read :attr:`~ConversionBackups.edited_since` already needed.

        :returns: ``(created, updated)``. Two empty strings when the ``.rehu`` is not there, since a
            revert then deletes nothing and there is no conversion date to name; a drifted **pair of
            sentinels** when it is there but will not read, so the caller still warns -- unreadable is
            not *unedited*, and warning is the cheaper mistake.
        """
        try:
            document = RehuDocument.load(self.__rehu_path)
        except FileNotFoundError:
            return "", ""
        except OSError, RehuFormatError:
            return "", self.__UNREADABLE_UPDATED
        return document.created, document.updated

    def __staged(self, written: tuple[Path, ...]) -> dict[Path, Path]:
        """Move every file the conversion wrote aside, to a :data:`STAGED_SUFFIX` sibling.

        :param written: what the conversion wrote; see :meth:`__written`.
        :returns: ``{written: staging}`` for every file moved aside.
        :raises FileExistsError: a leftover staging sibling from an interrupted revert is in the way.
        """
        stagings = {path: path.with_name(path.name + STAGED_SUFFIX) for path in written}
        for staging in stagings.values():
            if staging.exists():
                raise FileExistsError(staging)
        staged: dict[Path, Path] = {}
        try:
            for path, staging in stagings.items():
                path.rename(staging)
                staged[path] = staging
        except Exception:
            self.__undo({}, staged)
            raise
        return staged

    def __undo(self, restored: Mapping[Path, Path], staged: Mapping[Path, Path]) -> None:
        """Put the converted state back after a failed revert: re-back-up what was restored, then move
        every staged file back to the name the conversion gave it.

        :param restored: ``{original: backup}`` for every backup already renamed back.
        :param staged: ``{written: staging}``; see :meth:`__staged`.
        """
        for original, backup in restored.items():
            original.rename(backup)
        for path, staging in staged.items():
            staging.rename(path)
