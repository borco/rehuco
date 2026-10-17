"""Every operation on a resource's files: records and the Root Catalog, over this machine's filesystem and its mounts
([[nodes#access-seam]]).

The package is split by what a reader is here for:

- :mod:`~rehuco_core.access.keys` -- what a resource is reached by: :class:`ResourceKey` and its path arithmetic.
- :mod:`~rehuco_core.access.key_relocation` -- where keys went once a rename ran.
- :mod:`~rehuco_core.access.change_feed` -- what changed, announced without Qt.
- :mod:`~rehuco_core.access.records` -- records: load, save, the text as stored, legacy conversion; with
  :mod:`~rehuco_core.access.record_ops` the values it answers: a record as read and as saved, a conflict.
- :mod:`~rehuco_core.access.catalog` -- the Root Catalog: roots, query, one row, a root's size; with
  :mod:`~rehuco_core.access.catalog_ops` a refusal to read, and the session it reads through.

Nothing here imports Qt.
"""

from .catalog import Catalog
from .catalog_ops import CatalogSession, CatalogUnreadable
from .change_feed import Changed, ChangeEvent, ChangeFeed, FolderChanged, Moved, RootStale
from .key_relocation import KeyRelocation
from .keys import ResourceKey
from .record_ops import FileSignature, LoadedRecord, RecordConflict, SavedRecord
from .records import Records

__all__ = [
    "FileSignature",
    "CatalogSession",
    "CatalogUnreadable",
    "ChangeEvent",
    "ChangeFeed",
    "Changed",
    "FolderChanged",
    "KeyRelocation",
    "LoadedRecord",
    "Catalog",
    "ResourceKey",
    "Records",
    "Moved",
    "RecordConflict",
    "RootStale",
    "SavedRecord",
]
