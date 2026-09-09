"""The `.orig` backups a `.tc` conversion keeps: what they add up to, and discarding them
([[acquisition-tooling#convert-mechanics]], #190).

This module owns *what a backup is* -- the `.orig` naming, and the rename-back that turns one into its
original again. :mod:`rehuco_core.tc_conversion` builds on it: the same rename-back is what its own
in-run rollback uses to put a directory back when a conversion fails part-way -- atomicity, not an
after-the-fact undo, and the only place a backup is ever restored to its original name (#288).

Backups are enumerated as **the directory's `.orig` siblings**, not by stem: a legacy screenshot is
named ``cover.jpg`` or ``sample-01.jpg``, carrying nothing that ties it back to the resource it belongs
to. That is exact for the directory-scoped resources tc4 catalogs are made of (one resource, one
directory).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .constants import IMAGE_EXTENSIONS
from .rehu_document import RehuDocument, RehuFormatError
from .rehu_screenshots import scan_rehu_screenshot_files

BACKUP_SUFFIX: Final = ".orig"
"""Appended to an original's full name (``info.tc`` -> ``info.tc.orig``) before anything new is written
over it -- the conversion's never-overwrite, never-delete-then-write contract."""


def is_conversion_backup(filename: str) -> bool:
    """Whether ``filename`` names one of a conversion's retained backups.

    The one predicate both readers of that definition ask: the inventory here, and the content walk
    (:mod:`rehuco_core.rehu_content_files`), keeping a resource's backups out of the content they are
    backups *of* (#253). A bulk import retains them by default
    ([[acquisition-tooling#convert-mechanics]]), so counting them would put each converted resource's own
    ``info.tc.orig`` in its first checksum baseline, and discarding the backups afterwards -- the
    encouraged cleanup step -- would then report a missing file for every resource in the catalog.

    **Any ``.orig`` sibling**, never one matched against a record's stem, for the reason the module
    docstring gives: a legacy screenshot is named ``cover.jpg`` or ``sample-01.jpg`` and carries nothing
    tying it back to its resource.

    Matched exactly rather than case-insensitively, unlike the junk globs a content walk applies to names
    *other* tools wrote: this suffix is one this app appends itself, and folding case would take a
    ``render.blend.ORIG`` out of a measurement for no reason.

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

    The single rename-back :class:`~rehuco_core.tc_conversion.TcConverter` uses to roll back a conversion
    that is failing part-way -- that is atomicity, not a revert, and keeps a directory from being left
    half-converted.

    :param backup: the ``.orig`` sibling to restore.
    :returns: the path it now sits at.
    """
    original = original_path(backup)
    backup.rename(original)
    return original


@dataclass(frozen=True, slots=True)
class ConversionBackups:
    """What one directory's retained backups amount to, read without touching anything (#190).

    :param rehu_path: the converted ``.rehu``.
    :param backups: every ``.orig`` sibling, sorted by name.
    :param total_bytes: what those backups occupy, for a caller offering to discard them.
    :param dropped_screenshots: how many recognized legacy screenshots the conversion backed up and never
        installed -- the losers of a tie-break ([[acquisition-tooling#screenshot-schemes]]).
    :param converted: when the conversion wrote the ``.rehu``, read off its ``created`` stamp
        ([[field-schema#record-timestamps]]) -- empty when the file is gone or will not read. A
        conversion mints that stamp, so it dates the conversion and not the resource.
    """

    rehu_path: Path
    backups: tuple[Path, ...]
    total_bytes: int
    dropped_screenshots: int
    converted: str


def conversion_backups(rehu_path: Path) -> ConversionBackups:
    """Report what ``rehu_path``'s conversion left behind, changing nothing.

    :param rehu_path: the converted ``.rehu``.
    :returns: the inventory; see :class:`ConversionBackups`.
    """
    return ConversionBackupsManager(rehu_path).inventory()


def discard_conversion_backups(rehu_path: Path) -> tuple[Path, ...]:
    """Delete every retained backup beside ``rehu_path``, making the conversion permanent.

    :param rehu_path: the converted ``.rehu``.
    :returns: the backups deleted, sorted by name.
    """
    return ConversionBackupsManager(rehu_path).discard()


class ConversionBackupsManager:
    """Reads -- or discards -- one completed conversion's retained backups (#190).

    :param rehu_path: the converted ``.rehu``.
    """

    def __init__(self, rehu_path: Path) -> None:
        self.__rehu_path: Final = rehu_path

    def inventory(self) -> ConversionBackups:
        """Read what this directory's backups amount to, touching nothing.

        :returns: the inventory; see :class:`ConversionBackups`.
        """
        backups = self.__backups()
        created = self.__created()
        return ConversionBackups(
            rehu_path=self.__rehu_path,
            backups=backups,
            total_bytes=sum(self.__size(backup) for backup in backups),
            dropped_screenshots=self.__dropped_screenshots(backups),
            converted=created,
        )

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
            [[mounts-and-storage#offline-mounts]]).
        """
        try:
            siblings = list(self.__rehu_path.parent.iterdir())
        except OSError:
            return ()
        return tuple(sorted((s for s in siblings if is_conversion_backup(s.name)), key=lambda s: s.name))

    def __dropped_screenshots(self, backups: tuple[Path, ...]) -> int:
        """How many recognized legacy screenshots the conversion backed up and never installed.

        Every recognized screenshot is backed up, winners and losers of the tie-break alike, and only a
        winner is installed under its ``<stem>NN`` name, so the difference between the two counts *is*
        the drop. Re-running :func:`~rehuco_core.scan_tc_screenshots` could not answer it anyway -- after
        a conversion the legacy names all end in :data:`BACKUP_SUFFIX`, which no scheme recognizes.

        A conversion that backed up no image renamed its screenshots into their slots instead of copying
        them (#288), so no image backups here means nothing was dropped.

        :param backups: the resource's ``.orig`` siblings; see :meth:`__backups`.
        :returns: the number of dropped screenshots, ``0`` when the tie-break dropped nothing.
        """
        if not any(original_path(backup).suffix.lower() in IMAGE_EXTENSIONS for backup in backups):
            return 0
        backed_up = sum(1 for backup in backups if original_path(backup).suffix.lower() in IMAGE_EXTENSIONS)
        installed = len(scan_rehu_screenshot_files(self.__rehu_path.parent, self.__rehu_path.stem))
        return max(0, backed_up - installed)

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

    def __created(self) -> str:
        """The ``.rehu``'s ``created`` stamp -- when the conversion wrote it
        ([[field-schema#record-timestamps]]).

        :returns: the stamp, or an empty string when the ``.rehu`` is not there or will not read.
        """
        try:
            document = RehuDocument.load(self.__rehu_path)
        except FileNotFoundError:
            return ""
        except OSError, RehuFormatError:
            return ""
        return document.created
