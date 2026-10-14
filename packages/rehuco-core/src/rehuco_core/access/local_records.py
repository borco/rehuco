"""Records on this machine's own filesystem (#416): the local :class:`~rehuco_core.access.RecordOps`."""

import logging
from pathlib import Path
from typing import Final, override

from ..record_merge import record_lock
from ..record_versions import RecordVersion, merge_users, record_version, same_details
from ..rehu_document import RehuDocument, RehuFormatError
from ..rehu_screenshot_ordering import Deleter
from ..tc_conversion import convert_tc
from ..tc_document import load_tc
from ..tc_screenshots import ScreenshotNamePattern
from .change_feed import Changed, ChangeFeed
from .keys import LocalKey, ResourceKey
from .record_ops import FileSignature, LoadedRecord, RecordConflict, SavedRecord
from .resource_access import RecordOps

LOG: Final = logging.getLogger(__name__)

LEGACY_SUFFIX: Final = ".tc"
"""The suffix of a legacy record, read through :func:`~rehuco_core.load_tc`."""


class LocalRecords(RecordOps):
    """Records reached through this machine's filesystem.

    Saves are serialized per file within this process by :func:`~rehuco_core.record_merge.record_lock` -- the lock a
    progress write takes too, so the two never interleave.

    :param changes: where every write is announced.
    """

    def __init__(self, changes: ChangeFeed) -> None:
        self.__changes: Final = changes

    @override
    def load(self, key: ResourceKey, *, username: str, unknown_username: str) -> LoadedRecord:
        """Read a record, or an empty locked stub standing in for it when it cannot be read.

        :param key: a ``.rehu``, or a legacy ``.tc``.
        :param username: the identity a ``.rehu`` is opened as.
        :param unknown_username: the identity a ``.tc``'s per-user flags are filed under.
        :returns: the record.
        :raises TypeError: for a key this machine does not reach.
        """
        path = self.__path(key)
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

    @override
    def save(
        self, key: ResourceKey, document: RehuDocument, base: RecordVersion | None, *, username: str, overwrite: bool
    ) -> SavedRecord:
        """Save a record as a read-merge-write: refused on a metadata edit made on disk since ``base``, the per-user
        fields merged field by field.

        ``updated`` follows the file ([[field-schema#record-timestamps]]): a save whose written details are the file's
        -- every conflicting one resolved the file's way -- writes only per-user fields, so it takes the file's
        ``updated``; one whose details differ from the file's is an edit and stamps the save's time, even when it
        restores the values the document was opened with.
        A file that is no longer a readable record -- broken out of band since it was read -- is written over, as
        it was before the seam: there is nothing left in it to merge or to conflict with, and the write restores it.

        :param key: the record.
        :param document: what to write; the file's per-user fields are merged into it, in place.
        :param base: the version ``document`` was read at, or ``None`` to write it as it is.
        :param username: whose per-user fields ``document`` carries.
        :param overwrite: write over a metadata edit made on disk since ``base``.
        :returns: the record as saved.
        :raises RecordConflict: the metadata on disk changed since ``base``, and ``overwrite`` is not set.
        :raises OSError: the file could not be read or written.
        :raises ValueError: the document is locked against saving, or ``key`` is a legacy ``.tc``, which is never
            written -- it is converted ([[acquisition-tooling#tc-to-rehu]]).
        :raises TypeError: for a key this machine does not reach.
        """
        path = self.__path(key)
        if path.suffix.lower() == LEGACY_SUFFIX:
            raise ValueError(f"Refusing to save over a legacy record: {path}")
        with record_lock(path):
            users_merged = False
            edited: bool | None = None
            theirs = None if base is None else self.__read_existing(path, document.username)
            if base is not None and theirs is not None and theirs[1].file_hash != base.file_hash:
                theirs_document, theirs_version = theirs
                if theirs_version.metadata_hash != base.metadata_hash and not overwrite:
                    raise RecordConflict(theirs_document, theirs_version)
                users_merged = merge_users(document.data, theirs_document.data, base, username)
            if theirs is not None:
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
        self.__changes.publish(Changed((key,)))
        return SavedRecord(version, signature, users_merged)

    @override
    def stored_text(self, key: ResourceKey) -> str:
        """A record's text as stored.

        :param key: the record.
        :returns: its text.
        :raises OSError: it could not be read.
        :raises TypeError: for a key this machine does not reach.
        """
        return self.__path(key).read_text(encoding="utf-8")

    @override
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
        """Convert a legacy ``.tc`` into a ``.rehu`` beside it, and read the new record.

        :param key: the ``.tc``.
        :param keep_backups: keep the ``.orig`` backups.
        :param overwrite: replace a ``.rehu`` already there.
        :param username: the identity the imported per-user flags are filed under, and the new record opened as.
        :param excluded_patterns: filename globs the size walk leaves out.
        :param screenshot_name_patterns: the rules the legacy screenshots are recognized by.
        :param deleter: how a discarded backup is removed.
        :returns: the new record.
        :raises FileExistsError: the ``.rehu`` exists and ``overwrite`` is not set, or a backup is in the way.
        :raises OSError: the conversion failed, and was undone.
        :raises TypeError: for a key this machine does not reach.
        """
        tc_path = self.__path(key)
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
        target_key = LocalKey(target)
        self.__changes.publish(Changed((target_key, key)))
        return self.load(target_key, username=username, unknown_username=username)

    @staticmethod
    def __path(key: ResourceKey) -> Path:
        """The file a key names.

        :param key: the key.
        :returns: its path.
        :raises TypeError: for a :class:`~rehuco_core.access.NodeKey`, which only its node's access answers.
        """
        if not isinstance(key, LocalKey):
            raise TypeError(f"Local access cannot reach {key}")
        return key.path

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
        """A file's modification time and size, or ``None`` when it cannot be stat'ed.

        :param path: the file.
        :returns: its signature.
        """
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size
