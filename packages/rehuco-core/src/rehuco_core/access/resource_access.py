"""The operation-level interface every resource is reached through, local or on another node (#413).

One interface, ``ResourceAccess``, with a local implementation and, later, a remote one ([[nodes#access-seam]]). It
is built from small **operation groups**, each declared here and filled by the issue that migrates it; a group joins
:class:`ResourceAccess` as a property in that issue, never before, so nothing can call an operation that answers
nothing. Every call blocks -- a remote one is a network round trip -- so the agent makes them only from workers.
"""

from enum import StrEnum
from typing import Protocol

from ..record_versions import RecordVersion
from ..rehu_document import RehuDocument
from ..rehu_screenshot_ordering import Deleter
from ..tc_screenshots import ScreenshotNamePattern
from .change_feed import ChangeFeed
from .keys import ResourceKey
from .record_ops import LoadedRecord, SavedRecord


class Capability(StrEnum):
    """What an implementation can do for a resource beyond the operation groups; the UI turns a feature off without
    it. String-valued, so the wire schema carries it as is."""

    LOCAL_PATH = "local_path"
    """The resource is a file this machine opens itself."""

    REVEAL = "reveal"
    """It can be shown in the system's file manager."""

    RECYCLE_BIN = "recycle_bin"
    """Deleting it can go to the Recycle Bin rather than for good."""

    LEGACY_CONVERSION = "legacy_conversion"
    """A legacy ``.tc`` record of it can be converted."""


class RecordOps(Protocol):
    """Records: load, save as a read-merge-write against a :class:`~rehuco_core.RecordVersion`, the text as stored,
    legacy conversion (#416). Reverting is loading again."""

    def load(
        self,
        key: ResourceKey,
        *,
        username: str,
        unknown_username: str,
    ) -> LoadedRecord:  # pyright: ignore[reportReturnType]
        """Read a record, or an empty locked stub standing in for it when it cannot be read.

        :param key: a ``.rehu``, or a legacy ``.tc``.
        :param username: the identity a ``.rehu`` is opened as ([[field-schema#per-user-shared]]).
        :param unknown_username: the identity a ``.tc``'s per-user flags are filed under, their owner being unknown.
        :returns: the record; never raises for a file that cannot be read.
        """

    def save(
        self, key: ResourceKey, document: RehuDocument, base: RecordVersion | None, *, username: str, overwrite: bool
    ) -> SavedRecord:  # pyright: ignore[reportReturnType]
        """Save a record as a read-merge-write ([[nodes#access-seam]]): the file is read again, ``document``'s
        metadata written over it, and the per-user fields merged field by field
        (:func:`~rehuco_core.record_versions.merge_users`).

        :param key: the record.
        :param document: what to write; the file's per-user fields are merged into it, in place.
        :param base: the version ``document`` was read at, or ``None`` for a record never read from this file -- a
            new one, or a save-as -- which is written as it is.
        :param username: whose per-user fields ``document`` carries.
        :param overwrite: write over a metadata edit made on disk since ``base`` rather than refusing.
        :returns: the record as saved.
        :raises RecordConflict: the metadata on disk changed since ``base``, and ``overwrite`` is not set.
        :raises OSError: the file could not be read or written.
        :raises ValueError: the document is locked against saving, or ``key`` is a legacy ``.tc``, which is converted
            rather than written.
        :raises TypeError: for a key this implementation does not reach.
        """

    def stored_text(self, key: ResourceKey) -> str:  # pyright: ignore[reportReturnType]
        """A record's text as stored.

        :param key: the record.
        :returns: its text.
        :raises OSError: it could not be read.
        """

    # the parameters are the conversion's own inputs (rehuco_core.convert_tc)
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
    ) -> LoadedRecord:  # pyright: ignore[reportReturnType]
        """Convert a legacy ``.tc`` into a ``.rehu`` beside it ([[acquisition-tooling#tc-to-rehu]]).

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


class CatalogOps(Protocol):  # pylint: disable=too-few-public-methods
    """The Root Catalog: roots, query, one row (#417)."""


class FileOps(Protocol):  # pylint: disable=too-few-public-methods
    """A resource's file listing and its on-disk facts (#423)."""


class ScreenshotOps(Protocol):  # pylint: disable=too-few-public-methods
    """Screenshots: scan and read (#424); reorder, convert, acquire, remove (#429)."""


class ContentOps(Protocol):  # pylint: disable=too-few-public-methods
    """Content images: enumerate, read one member, a playback source (#425)."""


class JobOps(Protocol):  # pylint: disable=too-few-public-methods
    """Heavy work as jobs on the node owning the files: checksums, measuring, scans (#426)."""


class MutationOps(Protocol):  # pylint: disable=too-few-public-methods
    """Rename, relocation, delete (#428)."""


class ResourceAccess(Protocol):
    """Everything done to a resource's files, whichever machine holds them."""

    @property
    def changes(self) -> ChangeFeed:  # pyright: ignore[reportReturnType]
        """Where this implementation announces every change it makes."""

    @property
    def records(self) -> RecordOps:  # pyright: ignore[reportReturnType]
        """Records: load, save, the text as stored, legacy conversion."""

    def capabilities(self, key: ResourceKey) -> frozenset[Capability]:  # pyright: ignore[reportReturnType]
        """What can be done for ``key`` beyond the operation groups.

        :param key: the resource; one this implementation reaches, which the router guarantees.
        :returns: its capabilities.
        :raises TypeError: for a key of a kind this implementation does not reach.
        """
