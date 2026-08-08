"""Converts a legacy `.tc` into a real `.rehu`, safely replacing it and its recognized legacy
screenshots on disk ([[acquisition-tooling#tc-to-rehu]]).

Never overwrites, never deletes-then-writes: every original file the conversion touches is renamed to
a `.orig` sibling *before* any new file is written, and an original is only ever deleted -- once every
new file is confirmed written -- when the caller opts to discard backups.
"""

import shutil
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
from .tc_conversion_backups import backup_path, restore_backup
from .tc_description import rewrite_description_images
from .tc_document import TcDocument
from .tc_screenshots import ScreenshotRename, scan_tc_screenshots


def originals_to_back_up(tc_path: Path, target: Path, renames: Sequence[ScreenshotRename]) -> list[Path]:
    """Every original file a conversion of ``tc_path`` must back up before writing anything new.

    Shared between :class:`TcConverter`, which runs it, and
    :mod:`~rehuco_core.tc_conversion_plan` (#191), which only needs to read it to decide whether a
    stale ``.orig`` sibling would block the conversion.

    :param tc_path: the ``.tc`` file the conversion reads.
    :param target: the destination ``.rehu`` path.
    :param renames: the conversion's screenshot scan.
    :returns: ``tc_path``, every recognized legacy image (winners and losers alike), ``target`` itself
        when it already exists, and any pre-existing file already sitting at a ``<stem>NN`` install
        destination -- invisible to the legacy scan, yet about to be overwritten, so it too must be
        backed up first.
    """
    directory = tc_path.parent
    originals = [tc_path]
    if target.exists():
        originals.append(target)
    for rename in renames:
        originals.extend(directory / name for name in rename.recognized_filenames)
        destination = directory / rename.new_name
        if destination.exists():
            originals.append(destination)
    return list(dict.fromkeys(originals))


def convert_tc(
    tc_path: Path,
    *,
    keep_backups: bool,
    overwrite: bool = False,
    username: str = DEFAULT_UNKNOWN_USERNAME,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
) -> RehuDocument:
    """Convert ``tc_path`` (and its recognized legacy screenshots) into a real, unlocked ``.rehu``.

    :param tc_path: the ``.tc`` file to convert.
    :param keep_backups: if ``True``, ``.orig`` backups of the ``.tc`` and every recognized legacy
        image (and the previous ``.rehu``, if overwriting) are kept; if ``False``, they are deleted
        once every new file is confirmed written.
    :param overwrite: must be ``True`` if the target ``.rehu`` already exists, or ``FileExistsError``
        is raised before anything on disk is touched.
    :param username: the identity the imported per-user flags are filed under
        ([[field-schema#per-user-shared]], #109); defaults to
        :data:`~rehuco_core.plugins.DEFAULT_UNKNOWN_USERNAME`, since a flag carried in from the ``.tc``
        was not set by this install's own identity.
    :param excluded_patterns: filename globs the walk measuring ``current_size`` leaves out (#226),
        resolved by the caller -- core never reads a setting.
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
    ).convert()


class TcConverter:  # pylint: disable=too-few-public-methods
    """Converts one legacy ``.tc`` into a real ``.rehu``, safely replacing it and its recognized
    legacy screenshots on disk ([[acquisition-tooling#tc-to-rehu]]).

    Two phases: **plan** (pure reads -- parse the ``.tc``, scan screenshots, build the new JSON
    payload in memory; nothing on disk changes) then **replace** (back up every original file the
    conversion touches to a ``.orig`` sibling, write the new files, and -- only once everything new is
    confirmed written -- optionally delete the backups). Any failure during the write phase rolls the
    backups back to their original names and removes whatever new files were already created, so a
    crash or permission error never leaves the resource half-converted.

    :param tc_path: the ``.tc`` file to convert.
    :param keep_backups: whether to keep the ``.orig`` backups after a successful conversion.
    :param overwrite: whether an existing target ``.rehu`` may be replaced.
    :param username: the identity the imported per-user flags are filed under; see :func:`convert_tc`.
    :param excluded_patterns: filename globs the walk measuring ``current_size`` leaves out; see
        :func:`convert_tc`.
    """

    def __init__(
        self,
        tc_path: Path,
        *,
        keep_backups: bool,
        overwrite: bool,
        username: str,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    ) -> None:
        self.__tc_path: Final = tc_path
        self.__keep_backups: Final = keep_backups
        self.__overwrite: Final = overwrite
        self.__username: Final = username
        self.__excluded_patterns: Final = excluded_patterns

    def convert(self) -> RehuDocument:
        """Run the full plan-then-replace sequence.

        :returns: the fresh, unlocked document, already saved at the target ``.rehu`` path.
        :raises FileExistsError: see :func:`convert_tc`.
        """
        target = self.__tc_path.with_suffix(".rehu")
        if target.exists() and not self.__overwrite:
            raise FileExistsError(target)
        renames = scan_tc_screenshots(self.__tc_path.parent, self.__tc_path.stem)
        data = self.__built_rehu_data(renames)
        originals = originals_to_back_up(self.__tc_path, target, renames)
        self.__check_no_stale_backups(originals)
        backups = self.__backed_up(originals)
        installed: list[Path] = []
        try:
            document = RehuDocument(data, username=self.__username)
            document.save(target)
            installed.append(target)
            self.__install_images(renames, backups, installed)
        except Exception:
            self.__undo(installed, backups)
            raise
        if not self.__keep_backups:
            self.__delete_backups(backups)
        return document

    def __built_rehu_data(self, renames: Sequence[ScreenshotRename]) -> dict[str, Any]:
        """Build the fresh ``.rehu`` JSON payload in memory, writing nothing.

        :param renames: this conversion's screenshot scan, consulted to rewrite embedded description
            image references and to mint each new ``id``.
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
            core["current_size"] = content_size_on_disk(self.__tc_path, self.__excluded_patterns)
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

    def __install_images(
        self, renames: Sequence[ScreenshotRename], backups: dict[Path, Path], installed: list[Path]
    ) -> None:
        """Copy each slot's winning screenshot from its backup to its final ``slugNN`` name.

        :param renames: this conversion's screenshot scan.
        :param backups: this conversion's ``{original: backup}`` map.
        :param installed: appended with each new image path actually created, for rollback.
        """
        directory = self.__tc_path.parent
        for rename in renames:
            source_backup = backups[directory / rename.source_filename]
            destination = directory / rename.new_name
            shutil.copy2(source_backup, destination)
            installed.append(destination)

    def __undo(self, installed: Sequence[Path], backups: dict[Path, Path]) -> None:
        """Remove every new file already created and restore every backup to its original name.

        :param installed: new files actually created before the failure.
        :param backups: this conversion's ``{original: backup}`` map.
        """
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
        """Delete every backup after a fully successful conversion.

        :param backups: this conversion's ``{original: backup}`` map.
        """
        for backup in backups.values():
            backup.unlink(missing_ok=True)
