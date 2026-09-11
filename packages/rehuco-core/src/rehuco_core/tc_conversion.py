"""Converts a legacy `.tc` into a real `.rehu`, safely replacing it and renumbering its recognized
legacy screenshots on disk ([[acquisition-tooling#tc-to-rehu]]).

Never overwrites, never deletes-then-writes: the `.tc` is renamed to a `.orig` sibling *before* any new
file is written, and it is only ever deleted -- once every new file is confirmed written -- when the
caller opts to discard backups. **No screenshot is ever backed up**: a rename is not a write, so nothing
is lost by one, and a file whose slot is taken keeps its own name rather than being set aside (#288).
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from .constants import EXCLUDED_FILE_PATTERNS
from .plugins import DEFAULT_UNKNOWN_USERNAME
from .rehu_content_files import ContentUnreachableError, content_size_on_disk
from .rehu_document import RehuDocument
from .rehu_format import CORE_BLOCK_KEY
from .rehu_screenshot_ordering import DEFAULT_DELETER, Deleter, NoTrashBinError
from .tc_conversion_backups import backup_path, restore_backup
from .tc_description import rewrite_description_images
from .tc_document import TcDocument
from .tc_screenshots import (
    SCREENSHOT_NAME_PATTERNS,
    ScreenshotNamePattern,
    ScreenshotRename,
    scan_tc_screenshots,
)

LOG: Final = logging.getLogger(__name__)


def originals_to_back_up(tc_path: Path, target: Path) -> list[Path]:
    """Every original file a conversion of ``tc_path`` must back up before writing anything new.

    Two files at most, and usually one (#288): the `.tc` itself, and the target `.rehu` when an
    overwrite is about to replace one that is already there. **No screenshot is here** -- every image a
    conversion touches, it renames, and a rename loses nothing to back up against; an image whose slot
    is taken is left exactly where it was ([[acquisition-tooling#tc-to-rehu]]).

    Shared between :class:`TcConverter`, which runs it, and
    :mod:`~rehuco_core.tc_conversion_plan` (#191), which only needs to read it to decide whether a
    stale ``.orig`` sibling would block the conversion.

    :param tc_path: the ``.tc`` file the conversion reads.
    :param target: the destination ``.rehu`` path.
    :returns: ``tc_path``, and ``target`` itself when it already exists.
    """
    originals = [tc_path]
    if target.exists():
        originals.append(target)
    return originals


# the parameters *are* the conversion's inputs, and the two resolved sets (#226, #53) are handed in
# rather than read from a setting; collapsing them into a bag would put a second shape between the
# caller and the call
# pylint: disable-next=too-many-arguments
def convert_tc(
    tc_path: Path,
    *,
    keep_backups: bool,
    overwrite: bool = False,
    username: str = DEFAULT_UNKNOWN_USERNAME,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    screenshot_name_patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS,
    deleter: Deleter = DEFAULT_DELETER,
) -> RehuDocument:
    """Convert ``tc_path`` into a real, unlocked ``.rehu``, renumbering its legacy screenshots.

    :param tc_path: the ``.tc`` file to convert.
    :param keep_backups: if ``True``, the ``.orig`` backup of the ``.tc`` (and of the previous
        ``.rehu``, if overwriting) is kept; if ``False``, it is deleted once every new file is
        confirmed written. No screenshot is ever backed up (#288).
    :param overwrite: must be ``True`` if the target ``.rehu`` already exists, or ``FileExistsError``
        is raised before anything on disk is touched.
    :param username: the identity the imported per-user flags are filed under
        ([[field-schema#per-user-shared]], #109); defaults to
        :data:`~rehuco_core.plugins.DEFAULT_UNKNOWN_USERNAME`, since a flag carried in from the ``.tc``
        was not set by this install's own identity.
    :param screenshot_name_patterns: the naming rules the legacy screenshots are recognized by (#53),
        resolved by the caller for the same reason -- the walk measuring ``current_size`` and the rename
        plan must agree on which files are screenshots, or converting would change the measurement.
    :param excluded_patterns: filename globs the walk measuring ``current_size`` leaves out (#226),
        resolved by the caller -- core never reads a setting.
    :param deleter: how a discarded ``.orig`` backup is actually removed when ``keep_backups`` is
        ``False``; defaults to a plain unlink (#298). A `~rehuco_core.NoTrashBinError` it raises is
        logged and swallowed rather than undoing an otherwise-successful conversion -- see
        :meth:`TcConverter.convert`.
    :returns: the fresh, unlocked document, already saved at the target path.
    :raises FileExistsError: the target ``.rehu`` exists and ``overwrite`` is ``False``; or a
        ``.orig`` backup sibling already exists for something about to be backed up.
    """
    return TcConverter(
        tc_path,
        keep_backups=keep_backups,
        overwrite=overwrite,
        username=username,
        excluded_patterns=excluded_patterns,
        screenshot_name_patterns=screenshot_name_patterns,
        deleter=deleter,
    ).convert()


class TcConverter:  # pylint: disable=too-few-public-methods
    """Converts one legacy ``.tc`` into a real ``.rehu``, safely replacing it and renumbering its
    recognized legacy screenshots on disk ([[acquisition-tooling#tc-to-rehu]]).

    Two phases: **plan** (pure reads -- parse the ``.tc``, scan screenshots, build the new JSON
    payload in memory; nothing on disk changes) then **replace** (back up the ``.tc`` to a ``.orig``
    sibling, write the ``.rehu``, rename each pattern-matched image to its own slot, and -- only once
    everything new is confirmed written -- optionally delete the backup). Any failure during the write
    phase undoes every image rename already applied, removes whatever new files were created and
    restores the backups to their original names, so a crash or permission error never leaves the
    resource half-converted.

    :param tc_path: the ``.tc`` file to convert.
    :param keep_backups: whether to keep the ``.orig`` backup after a successful conversion.
    :param overwrite: whether an existing target ``.rehu`` may be replaced.
    :param username: the identity the imported per-user flags are filed under; see :func:`convert_tc`.
    :param screenshot_name_patterns: the naming rules the legacy screenshots are recognized by; see
        :func:`convert_tc`.
    :param excluded_patterns: filename globs the walk measuring ``current_size`` leaves out; see
        :func:`convert_tc`.
    :param deleter: how a discarded ``.orig`` backup is removed; see :func:`convert_tc`.
    """

    # the same inputs as :func:`convert_tc`, for the same reason
    # pylint: disable-next=too-many-arguments
    def __init__(
        self,
        tc_path: Path,
        *,
        keep_backups: bool,
        overwrite: bool,
        username: str,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS,
        deleter: Deleter = DEFAULT_DELETER,
    ) -> None:
        self.__tc_path: Final = tc_path
        self.__keep_backups: Final = keep_backups
        self.__overwrite: Final = overwrite
        self.__username: Final = username
        self.__excluded_patterns: Final = excluded_patterns
        self.__screenshot_name_patterns: Final = screenshot_name_patterns
        self.__deleter: Final = deleter

    def convert(self) -> RehuDocument:
        """Run the full plan-then-replace sequence.

        A `~rehuco_core.NoTrashBinError` from the discard at the end (:meth:`__delete_backups`) never
        reaches here -- see there -- so this always returns once the write phase itself has succeeded.

        :returns: the fresh, unlocked document, already saved at the target ``.rehu`` path.
        :raises FileExistsError: see :func:`convert_tc`.
        """
        target = self.__tc_path.with_suffix(".rehu")
        if target.exists() and not self.__overwrite:
            raise FileExistsError(target)
        plan = scan_tc_screenshots(self.__tc_path.parent, self.__tc_path.stem, self.__screenshot_name_patterns)
        data = self.__built_rehu_data(plan.renames)
        originals = originals_to_back_up(self.__tc_path, target)
        self.__check_no_stale_backups(originals)
        backups = self.__backed_up(originals)
        installed: list[Path] = []
        renamed: list[tuple[Path, Path]] = []
        try:
            document = RehuDocument(data, username=self.__username)
            document.save(target)
            installed.append(target)
            self.__renumber_images(plan.renames, renamed)
        except Exception:
            self.__undo(installed, renamed, backups)
            raise
        if not self.__keep_backups:
            self.__delete_backups(backups)
        return document

    def __built_rehu_data(self, renames: Sequence[ScreenshotRename]) -> dict[str, Any]:
        """Build the fresh ``.rehu`` JSON payload in memory, writing nothing.

        :param renames: this conversion's screenshot renames, consulted to rewrite the description's
            embedded image references.
        :returns: the JSON object ready to back a fresh, unlocked :class:`RehuDocument`.
        """
        data = TcDocument.load(self.__tc_path).to_rehu_data(username=self.__username)
        core = data[CORE_BLOCK_KEY]
        core["description"] = rewrite_description_images(str(core.get("description", "")), renames)
        core["id"] = str(uuid4())
        seeded = self.__seeded_timestamp()
        core["created"] = seeded
        core["updated"] = seeded
        self.__put_measured_current_size(core)
        return data

    def __put_measured_current_size(self, core: dict[str, Any]) -> None:
        """Replace whatever ``current_size`` the ``.tc`` claimed with a fresh measurement of the
        resource's content, through the same enumeration checksums use
        ([[field-schema#duration-size]], #255) -- the legacy value may be years stale about a directory
        that has since changed, and conversion is the one moment the resource is being handled anyway.

        A resource whose directory will not list is left without a stored size rather than given a
        wrong one ([[mounts-and-storage#offline-mounts]]): the key is omitted entirely, never filled
        with the untrusted legacy value.

        :param core: the core block being built, mutated in place.
        """
        core.pop("current_size", None)
        try:
            core["current_size"] = content_size_on_disk(
                self.__tc_path, self.__excluded_patterns, self.__screenshot_name_patterns
            )
        except ContentUnreachableError:
            pass

    def __seeded_timestamp(self) -> str:
        """The ``.tc`` file's mtime, as the UTC ISO-8601 string ``created``/``updated`` seed from
        ([[field-schema#record-timestamps]]) -- mtime is used for both, since tc4 tracked no separate
        creation/edit history and cross-platform ctime is unreliable as a creation-time proxy.

        :returns: e.g. ``"2026-01-15T09:30:00Z"``.
        """
        mtime = self.__tc_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def __check_no_stale_backups(self, originals: Sequence[Path]) -> None:
        """Refuse to proceed if any ``.orig`` sibling already exists for an original about to be
        backed up -- a leftover from a previous interrupted attempt, not safe to guess about.

        :param originals: this conversion's planned backup set.
        :raises FileExistsError: a ``.orig`` sibling already exists.
        """
        for original in originals:
            backup = backup_path(original)
            if backup.exists():
                raise FileExistsError(backup)

    def __backed_up(self, originals: Sequence[Path]) -> dict[Path, Path]:
        """Rename every original to its ``.orig`` sibling, rolling back on a mid-loop failure.

        :param originals: this conversion's planned backup set.
        :returns: ``{original: backup}`` for every file successfully backed up.
        """
        backups: dict[Path, Path] = {}
        try:
            for original in originals:
                backup = backup_path(original)
                original.rename(backup)
                backups[original] = backup
        except Exception:
            self.__restore(backups)
            raise
        return backups

    def __renumber_images(self, renames: Sequence[ScreenshotRename], renamed: list[tuple[Path, Path]]) -> None:
        """Rename each pattern-matched screenshot to the ``<stem>NN`` slot its own name carries.

        The scan hands out no slot that is already spoken for, so a destination here is free; it is
        checked anyway, because *never overwrite* is the contract this module is built on and
        :meth:`~pathlib.Path.rename` silently replaces the target on POSIX.

        :param renames: this conversion's screenshot scan.
        :param renamed: appended with each ``(source, destination)`` actually renamed, for rollback.
        :raises FileExistsError: a destination appeared between the scan and the rename.
        """
        directory = self.__tc_path.parent
        for rename in renames:
            source = directory / rename.source_filename
            destination = directory / rename.new_name
            if destination.exists():
                raise FileExistsError(destination)
            source.rename(destination)
            renamed.append((source, destination))

    def __undo(
        self, installed: Sequence[Path], renamed: Sequence[tuple[Path, Path]], backups: dict[Path, Path]
    ) -> None:
        """Put the directory back exactly as it was found.

        In the reverse order of the write phase: the image renames first, since a restored ``.tc``
        beside half-renumbered screenshots is not the state the conversion was asked about. A rename
        back that fails itself is skipped rather than raised, the discipline
        :class:`~rehuco_core.ScreenshotRenumberer` rolls back under -- this already runs because
        something on disk failed, and restoring what can be restored beats abandoning the rest to let
        a second error hide the first.

        :param installed: new files actually created before the failure.
        :param renamed: the ``(source, destination)`` pairs already renamed before the failure.
        :param backups: this conversion's ``{original: backup}`` map.
        """
        for source, destination in reversed(renamed):
            try:
                destination.rename(source)
            except OSError:
                continue
        for path in installed:
            path.unlink(missing_ok=True)
        self.__restore(backups)

    def __restore(self, backups: dict[Path, Path]) -> None:
        """Rename every backup back to its original name, through the same rename-back an
        after-the-fact revert runs (:func:`~rehuco_core.tc_conversion_backups.restore_backup`, #190).

        :param backups: this conversion's ``{original: backup}`` map.
        """
        for backup in backups.values():
            restore_backup(backup)

    def __delete_backups(self, backups: dict[Path, Path]) -> None:
        """Delete every backup after a fully successful conversion, through :attr:`__deleter`.

        Tolerates a backup already gone (a rename here backs onto a plain ``.unlink(missing_ok=True)``
        before #298, so a `Deleter` without that option is given the same tolerance explicitly). A
        backup the deleter cannot reach at all (`NoTrashBinError`) is logged and left in place rather
        than raised out of an otherwise-successful conversion: this is cleanup, not the conversion
        itself, the same distinction :meth:`__undo` draws for the mid-conversion rollback's own plain
        unlink.

        :param backups: this conversion's ``{original: backup}`` map.
        """
        for backup in backups.values():
            try:
                self.__deleter.delete(backup)
            except FileNotFoundError:
                pass
            except NoTrashBinError:
                LOG.warning("Could not move %s to the Recycle Bin / Trash; left in place.", backup)
