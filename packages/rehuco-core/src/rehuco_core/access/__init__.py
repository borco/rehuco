"""The resource access seam: every operation on a resource's files, local or on another node ([[nodes#access-seam]]).

Built from #413 on, one operation group per issue. The package is split by what a reader is here for:

- :mod:`~rehuco_core.access.keys` -- what a resource is reached by: :class:`LocalKey`, :class:`NodeKey`, and the
  path arithmetic both share.
- :mod:`~rehuco_core.access.key_relocation` -- where keys went once a rename ran.
- :mod:`~rehuco_core.access.change_feed` -- what changed, announced without Qt.
- :mod:`~rehuco_core.access.resource_access` -- the interface itself, its operation groups and capabilities.
- :mod:`~rehuco_core.access.record_ops` -- what the records group answers: a record as read and as saved, a
  conflict.
- :mod:`~rehuco_core.access.catalog_ops` -- what the catalog group answers: a refusal to read, and the session a
  local catalog reads through.
- :mod:`~rehuco_core.access.local_access` -- the implementation over this machine's filesystem, with
  :mod:`~rehuco_core.access.local_records` its records and :mod:`~rehuco_core.access.local_catalog` its catalog.
- :mod:`~rehuco_core.access.access_router` -- which implementation a key goes to.

Nothing here imports Qt.
"""

from .access_router import AccessRouter, NodeUnreachable
from .catalog_ops import CatalogSession, CatalogUnreadable
from .change_feed import Changed, ChangeEvent, ChangeFeed, FolderChanged, Invalidated, Moved
from .key_relocation import KeyRelocation
from .keys import LocalKey, NodeKey, ResourceKey
from .local_access import LOCAL_CAPABILITIES, LocalAccess
from .local_catalog import LocalCatalog
from .local_records import LocalRecords
from .record_ops import FileSignature, LoadedRecord, RecordConflict, SavedRecord
from .resource_access import (
    Capability,
    CatalogOps,
    ContentOps,
    FileOps,
    JobOps,
    MutationOps,
    RecordOps,
    ResourceAccess,
    ScreenshotOps,
)

__all__ = [
    "FileSignature",
    "LOCAL_CAPABILITIES",
    "AccessRouter",
    "Capability",
    "CatalogOps",
    "CatalogSession",
    "CatalogUnreadable",
    "ChangeEvent",
    "ChangeFeed",
    "Changed",
    "ContentOps",
    "FileOps",
    "FolderChanged",
    "Invalidated",
    "JobOps",
    "KeyRelocation",
    "LoadedRecord",
    "LocalAccess",
    "LocalCatalog",
    "LocalKey",
    "LocalRecords",
    "Moved",
    "MutationOps",
    "NodeKey",
    "NodeUnreachable",
    "RecordConflict",
    "RecordOps",
    "ResourceAccess",
    "ResourceKey",
    "SavedRecord",
    "ScreenshotOps",
]
