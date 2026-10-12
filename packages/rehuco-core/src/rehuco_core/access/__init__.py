"""The resource access seam: every operation on a resource's files, local or on another node ([[nodes#access-seam]]).

Built from #413 on, one operation group per issue. The package is split by what a reader is here for:

- :mod:`~rehuco_core.access.keys` -- what a resource is reached by: :class:`LocalKey`, :class:`NodeKey`, and the
  path arithmetic both share.
- :mod:`~rehuco_core.access.key_relocation` -- where keys went once a rename ran.
- :mod:`~rehuco_core.access.change_feed` -- what changed, announced without Qt.
- :mod:`~rehuco_core.access.resource_access` -- the interface itself, its operation groups and capabilities.
- :mod:`~rehuco_core.access.local_access` -- the implementation over this machine's filesystem.
- :mod:`~rehuco_core.access.access_router` -- which implementation a key goes to.

Nothing here imports Qt.
"""

from .access_router import AccessRouter, NodeUnreachable
from .change_feed import Changed, ChangeEvent, ChangeFeed, FolderChanged, Invalidated, Moved
from .key_relocation import KeyRelocation
from .keys import LocalKey, NodeKey, ResourceKey
from .local_access import LOCAL_CAPABILITIES, LocalAccess
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
    "LOCAL_CAPABILITIES",
    "AccessRouter",
    "Capability",
    "CatalogOps",
    "ChangeEvent",
    "ChangeFeed",
    "Changed",
    "ContentOps",
    "FileOps",
    "FolderChanged",
    "Invalidated",
    "JobOps",
    "KeyRelocation",
    "LocalAccess",
    "LocalKey",
    "Moved",
    "MutationOps",
    "NodeKey",
    "NodeUnreachable",
    "RecordOps",
    "ResourceAccess",
    "ResourceKey",
    "ScreenshotOps",
]
