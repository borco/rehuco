"""Records, read and written through this machine's filesystem and its mounts (#416): load, save as a read-merge-write
against a :class:`~rehuco_core.RecordVersion`, the text as stored, legacy conversion. Reverting is loading again."""

import logging
from collections.abc import Collection
from pathlib import Path
from typing import Final

from ..record_file_lock import locked_record
from ..record_versions import RecordVersion, merge_users, record_version, same_details
from ..rehu_document import RehuDocument, RehuFormatError
from ..rehu_screenshot_ordering import Deleter
from ..rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from ..tc_conversion import convert_tc
from ..tc_document import load_tc
from ..tc_screenshots import ScreenshotNamePattern
from ..user_sidecars import user_sidecar_paths
from .keys import ResourceKey
from .record_ops import FileSignature, LoadedRecord, RecordConflict, SavedRecord

LOG: Final = logging.getLogger(__name__)

LEGACY_SUFFIX: Final = ".tc"
"""The suffix of a legacy record, read through :func:`~rehuco_core.load_tc`."""


class Records:
    """Records reached through this machine's filesystem.

    Saves hold the record by :func:`~rehuco_core.record_file_lock.locked_record` -- in this process, and by its lock
    file across processes and machines ([[sync#lock-file]], #512) -- the lock a progress write takes too, so no two
    writers interleave between the re-read and the write. **A write is announced by no one here**: the file notifier
    reports it like any other writer's ([[mounts-and-storage#out-of-band]], #511).

    :param coordinator: the rename barrier :meth:`signature` looks under, so it never blocks a rename.
    """

    def __init__(self, coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR) -> None:
        self.__coordinator: Final = coordinator

    def load(self, key: ResourceKey, *, username: str, unknown_username: str) -> LoadedRecord:
        """Read a record, or an empty locked stub standing in for it when it cannot be read.

        :param key: a ``.rehu``, or a legacy ``.tc``.
        :param username: the identity a ``.rehu`` is opened as ([[field-schema#per-user-shared]]).
        :param unknown_username: the identity a ``.tc``'s per-user flags are filed under, their owner being unknown.
        :returns: the record; never raises for a file that cannot be read.
        """
        path = key.path
        signature = self.__signature(path)
        if path.suffix.lower() == LEGACY_SUFFIX:
            try:
                document = load_tc(path, username=unknown_username)
            except (OSError, RehuFormatError) as error:
                return self.__stub(path, error, unknown_username, signature)
            return LoadedRecord(document, None, tuple(document.lock_reasons), signature)
        try:
            document, version = self.__read(path, username)
        except (OSError, RehuFormatError) as error:
            return self.__stub(path, error, username, signature)
        return LoadedRecord(document, version, tuple(document.lock_reasons), signature)

    def save(  # pylint: disable=too-many-arguments
        self,
        key: ResourceKey,
        document: RehuDocument,
        base: RecordVersion | None,
        *,
        username: str,
        overwrite: bool,
        dropped: Collection[str] = (),
        new: bool = False,
    ) -> SavedRecord:
        """Save a record as a read-merge-write: refused on a metadata edit made on disk since ``base``, the per-user
        fields merged field by field.

        ``updated`` follows the file ([[field-schema#record-timestamps]]): a save whose written details are the file's
        -- every conflicting one resolved the file's way -- writes only per-user fields, so it takes the file's
        ``updated``; one whose details differ from the file's is an edit and stamps the save's time, even when it
        restores the values the document was opened with.
        A file that is no longer a readable record -- broken out of band since it was read -- is written over: there
        is nothing left in it to merge or to conflict with, and the write restores it.

        :param key: the record.
        :param document: what to write; the file's per-user fields are merged into it, in place.
        :param base: the version ``document`` was read at, or ``None`` for a record never read from this file -- a
            new one, or a save-as -- which is written as it is.
        :param username: whose per-user fields ``document`` carries.
        :param overwrite: write over a metadata edit made on disk since ``base``.
        :param dropped: the blocks ``document`` leaves out on purpose (:func:`~rehuco_core.merge_users`), for a
            document built from a snapshot that no longer holds them (#497); one that still holds them needs none.
        :param new: the record is believed not to exist yet -- a first save, with no ``base`` -- so one found at
            ``key`` was created meanwhile and is a conflict rather than something to write over unseen (#497).
        :returns: the record as saved.
        :raises RecordConflict: the metadata on disk changed since ``base``, or a ``new`` record already exists, and
            ``overwrite`` is not set.
        :raises RecordLockedError: someone else held the record's lock for longer than a save waits.
        :raises OSError: the file could not be read or written.
        :raises ValueError: the document is locked against saving, or ``key`` is a legacy ``.tc``, which is never
            written -- it is converted ([[acquisition-tooling#tc-to-rehu]]).
        """
        path = key.path
        if path.suffix.lower() == LEGACY_SUFFIX:
            raise ValueError(f"Refusing to save over a legacy record: {path}")
        with locked_record(path, user=username):
            theirs = None if base is None and not new else self.__read_existing(path, document.username)
            if base is None and theirs is not None and not overwrite:
                raise RecordConflict(*theirs)
            users_merged = False
            edited: bool | None = None
            if theirs is not None:
                if base is not None and theirs[1].file_hash != base.file_hash:
                    users_merged = self.__merge_theirs(
                        document, theirs, base, username=username, overwrite=overwrite, dropped=dropped
                    )
                # whether this write changes the resource is a question about the file, not about the document's own
                # baseline: another writer may have moved the file on, and a conflict resolved against the file is
                # saved with the conflict's version, so the file reads as unchanged since the read
                edited = not same_details(document.payload_to_write(), theirs[0].data)
                if not edited and theirs[0].updated:
                    document.updated = theirs[0].updated
            document.save(path, edited=edited)
            # read back rather than derived from the document: a save leaves out the blocks it drops, and the next
            # save's check reads the file
            _, version = self.__read(path, document.username)
            signature = self.__signature(path)
        return SavedRecord(version, signature, users_merged)

    # the save's own inputs, handed on from it whole: splitting them would only move the count into a tuple
    @staticmethod
    def __merge_theirs(  # pylint: disable=too-many-arguments
        document: RehuDocument,
        theirs: tuple[RehuDocument, RecordVersion],
        base: RecordVersion,
        *,
        username: str,
        overwrite: bool,
        dropped: Collection[str],
    ) -> bool:
        """Merge the file's per-user fields into ``document``, refusing a metadata edit made on disk since ``base``.

        :param document: what is about to be written, merged into.
        :param theirs: the record on disk now, and its version.
        :param base: the version ``document`` was read at.
        :param username: whose per-user fields ``document`` carries.
        :param overwrite: write over a metadata edit made on disk since ``base``.
        :param dropped: the blocks ``document`` leaves out on purpose.
        :returns: whether per-user fields the file held were merged in.
        :raises RecordConflict: the metadata on disk changed since ``base``, and ``overwrite`` is not set.
        """
        theirs_document, theirs_version = theirs
        if theirs_version.metadata_hash != base.metadata_hash and not overwrite:
            raise RecordConflict(theirs_document, theirs_version)
        return merge_users(document.data, theirs_document.data, base, username, dropped=dropped)

    def stored_files(self, key: ResourceKey) -> list[tuple[str, str]]:
        """A record's files as stored: the record, then each of its per-user sidecars ([[data-model#single-file]]) --
        every user's, in name order. A legacy ``.tc`` has none.

        :param key: the record.
        :returns: each file's name and text; a sidecar gone between the listing and its read is left out.
        :raises OSError: the record could not be read, its folder listed, or a sidecar read.
        """
        path = key.path
        files = [(path.name, path.read_text(encoding="utf-8"))]
        if path.suffix.lower() == LEGACY_SUFFIX:
            return files
        for sidecar in sorted(user_sidecar_paths(path).values(), key=lambda sidecar: sidecar.name):
            try:
                files.append((sidecar.name, sidecar.read_text(encoding="utf-8")))
            except FileNotFoundError:
                continue
        return files

    def convert(  # pylint: disable=too-many-arguments
        self,
        key: ResourceKey,
        *,
        keep_backups: bool,
        overwrite: bool,
        username: str,
        excluded_patterns: tuple[str, ...],
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...],
        deleter: Deleter,
    ) -> LoadedRecord:
        """Convert a legacy ``.tc`` into a ``.rehu`` beside it ([[acquisition-tooling#tc-to-rehu]]), and read the new
        record.

        :param key: the ``.tc``.
        :param keep_backups: keep the ``.orig`` backups rather than deleting them once the conversion is written.
        :param overwrite: replace a ``.rehu`` already there.
        :param username: the identity the imported per-user flags are filed under, and the new record opened as.
        :param excluded_patterns: filename globs the size walk leaves out.
        :param screenshot_name_patterns: the rules the legacy screenshots are recognized by.
        :param deleter: how a discarded backup is removed.
        :returns: the new record.
        :raises FileExistsError: the ``.rehu`` exists and ``overwrite`` is not set, or a backup is in the way.
        :raises OSError: the conversion failed, and was undone.
        """
        tc_path = key.path
        converted = convert_tc(
            tc_path,
            keep_backups=keep_backups,
            overwrite=overwrite,
            username=username,
            excluded_patterns=excluded_patterns,
            screenshot_name_patterns=screenshot_name_patterns,
            deleter=deleter,
        )
        target = converted.path if converted.path is not None else tc_path.with_suffix(".rehu")
        target_key = ResourceKey(target)
        return self.load(target_key, username=username, unknown_username=username)

    def signature(self, key: ResourceKey) -> FileSignature | None:
        """A record's modification time and size now, looked at under the rename hold -- what a later look is compared
        with to see a change made outside the app ([[mounts-and-storage#out-of-band]]).

        :param key: the record.
        :returns: its signature; ``None`` when it cannot be stat'ed.
        """
        with self.__coordinator.holding():
            return self.__signature(key.path)

    @staticmethod
    def __read(path: Path, username: str) -> tuple[RehuDocument, RecordVersion]:
        """Read a ``.rehu`` and its version from one read of it.

        :param path: the record.
        :param username: the identity it is opened as.
        :returns: the document and its version.
        :raises OSError: it could not be read.
        :raises RehuFormatError: it is not a readable record.
        """
        document, text = RehuDocument.load_with_text(path, username=username)
        return document, record_version(document.data, text)

    def __read_existing(self, path: Path, username: str) -> tuple[RehuDocument, RecordVersion] | None:
        """Read the record a save is about to replace, or nothing when there is none.

        :param path: the record.
        :param username: the identity it is opened as.
        :returns: the document on disk and its version, or ``None`` when the file is gone or no longer a readable
            record -- the latter logged, since what broke it is lost under the write.
        :raises OSError: it could not be read.
        """
        try:
            return self.__read(path, username)
        except FileNotFoundError:
            return None
        except RehuFormatError as error:
            LOG.warning("%s is no longer a readable record and is written over: %s", path, error)
            return None

    @staticmethod
    def __stub(path: Path, error: Exception, username: str, signature: FileSignature | None) -> LoadedRecord:
        """The locked stub standing in for a record that could not be read, its failure logged.

        :param path: the record.
        :param error: why it could not be read.
        :param username: the identity the stub carries.
        :param signature: the file's signature, if it had one.
        :returns: the stub, as a record.
        """
        LOG.error("Could not read %s: %s", path, error)
        document = RehuDocument.locked_stub_for_error(path, error, username=username)
        return LoadedRecord(document, None, tuple(document.lock_reasons), signature)

    @staticmethod
    def __signature(path: Path) -> FileSignature | None:
        """A record's modification time and size, with its per-user sidecars' -- the latest time and the sizes summed
        -- since it is read with them ([[data-model#single-file]]): another device's progress is a change to it too.

        :param path: the record.
        :returns: its signature, or ``None`` when the record cannot be stat'ed or its folder listed -- what a watch
            reads as the record gone; a sidecar that cannot be stat'ed is left out, since the record is still there.
        """
        try:
            stat = path.stat()
            sidecars = user_sidecar_paths(path).values()
        except OSError:
            return None
        mtime_ns, size = stat.st_mtime_ns, stat.st_size
        for sidecar in sidecars:
            try:
                status = sidecar.stat()
            except OSError:
                continue
            mtime_ns, size = max(mtime_ns, status.st_mtime_ns), size + status.st_size
        return mtime_ns, size
