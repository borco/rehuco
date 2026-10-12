"""The operation-level interface every resource is reached through, local or on another node (#413).

One interface, ``ResourceAccess``, with a local implementation and, later, a remote one ([[nodes#access-seam]]). It
is built from small **operation groups**, each declared here and filled by the issue that migrates it; a group joins
:class:`ResourceAccess` as a property in that issue, never before, so nothing can call an operation that answers
nothing. Every call blocks -- a remote one is a network round trip -- so the agent makes them only from workers.
"""

from enum import StrEnum
from typing import Protocol

from .change_feed import ChangeFeed
from .keys import ResourceKey


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


class RecordOps(Protocol):  # pylint: disable=too-few-public-methods
    """Records: load, save as a read-merge-write with a ``RecordVersion``, revert, legacy conversion (#416)."""


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

    def capabilities(self, key: ResourceKey) -> frozenset[Capability]:  # pyright: ignore[reportReturnType]
        """What can be done for ``key`` beyond the operation groups.

        :param key: the resource; one this implementation reaches, which the router guarantees.
        :returns: its capabilities.
        :raises TypeError: for a key of a kind this implementation does not reach.
        """
