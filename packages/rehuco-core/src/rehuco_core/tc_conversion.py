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

from rehuco_core.plugins import DEFAULT_USERNAME
from rehuco_core.rehu_document import RehuDocument
from rehuco_core.rehu_format import CORE_BLOCK_KEY
from rehuco_core.tc_description import rewrite_description_images
from rehuco_core.tc_document import TcDocument
from rehuco_core.tc_screenshots import ScreenshotRename, scan_tc_screenshots


def convert_tc(
    tc_path: Path, *, keep_backups: bool, overwrite: bool = False, username: str = DEFAULT_USERNAME
) -> RehuDocument:
    """Convert ``tc_path`` (and its recognized legacy screenshots) into a real, unlocked ``.rehu``.

    :param tc_path: the ``.tc`` file to convert.
    :param keep_backups: if ``True``, ``.orig`` backups of the ``.tc`` and every recognized legacy
        image (and the previous ``.rehu``, if overwriting) are kept; if ``False``, they are deleted
        once every new file is confirmed written.
    :param overwrite: must be ``True`` if the target ``.rehu`` already exists, or ``FileExistsError``
        is raised before anything on disk is touched.
    :param username: the identity the imported per-user flags are filed under
        ([[field-schema#per-user-shared]]); defaults to :data:`~rehuco_core.plugins.DEFAULT_USERNAME`.
    :returns: the fresh, unlocked document, already saved at the target path.
    :raises FileExistsError: the target ``.rehu`` exists and ``overwrite`` is ``False``; or a
        ``.orig`` backup sibling already exists for something about to be backed up.
    """
    return TcConverter(tc_path, keep_backups=keep_backups, overwrite=overwrite, username=username).convert()


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
    """

    __BACKUP_SUFFIX: Final = ".orig"

    def __init__(self, tc_path: Path, *, keep_backups: bool, overwrite: bool, username: str) -> None:
        self.__tc_path: Final = tc_path
        self.__keep_backups: Final = keep_backups
        self.__overwrite: Final = overwrite
        self.__username: Final = username

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
        originals = self.__originals_to_back_up(target, renames)
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
        """Build the fresh ``.rehu`` JSON payload in memory, reading nothing but ``__tc_path``.

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
        return data

    def __seeded_timestamp(self) -> str:
        """The ``.tc`` file's mtime, as the UTC ISO-8601 string ``created``/``updated`` seed from
        ([[field-schema#record-timestamps]]) -- mtime is used for both, since tc4 tracked no separate
        creation/edit history and cross-platform ctime is unreliable as a creation-time proxy.

        :returns: e.g. ``"2026-01-15T09:30:00Z"``.
        """
        mtime = self.__tc_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def __originals_to_back_up(self, target: Path, renames: Sequence[ScreenshotRename]) -> list[Path]:
        """Every original file this conversion must back up before writing anything new.

        :param target: the destination ``.rehu`` path.
        :param renames: this conversion's screenshot scan.
        :returns: ``tc_path``, every recognized legacy image (winners and losers alike), and
            ``target`` itself when overwriting an existing ``.rehu``.
        """
        directory = self.__tc_path.parent
        originals = [self.__tc_path]
        if target.exists():
            originals.append(target)
        for rename in renames:
            originals.extend(directory / name for name in rename.recognized_filenames)
        return list(dict.fromkeys(originals))

    def __check_no_stale_backups(self, originals: Sequence[Path]) -> None:
        """Refuse to proceed if any ``.orig`` sibling already exists for an original about to be
        backed up -- a leftover from a previous interrupted attempt, not safe to guess about.

        :param originals: this conversion's planned backup set.
        :raises FileExistsError: a ``.orig`` sibling already exists.
        """
        for original in originals:
            backup = self.__backup_path(original)
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
                backup = self.__backup_path(original)
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
        """Rename every backup back to its original name.

        :param backups: this conversion's ``{original: backup}`` map.
        """
        for original, backup in backups.items():
            backup.rename(original)

    def __delete_backups(self, backups: dict[Path, Path]) -> None:
        """Delete every backup after a fully successful conversion.

        :param backups: this conversion's ``{original: backup}`` map.
        """
        for backup in backups.values():
            backup.unlink(missing_ok=True)

    def __backup_path(self, original: Path) -> Path:
        """The ``.orig`` sibling for ``original``.

        :param original: the file being backed up.
        :returns: ``original`` with :data:`__BACKUP_SUFFIX` appended to its full name.
        """
        return original.with_name(original.name + self.__BACKUP_SUFFIX)
