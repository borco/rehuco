"""The target of a library scan's title link: the record of one store item, found again by the store's own id."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class LibraryRecordLink:
    """A library item's record, named by what stays true of it however it is moved afterwards (#700).

    Not by its path: a scan's line is read long after it was logged, and the bucket folders a root splits into move
    records. The store's id is what the record keeps ([[assets#site-id]]), so it is looked up again when the link is
    clicked.

    :param root_id: the root the scan filed the item into.
    :param site: the store, as its records' source names it.
    :param site_id: the store's own id for the item.
    """

    root_id: UUID
    site: str
    site_id: str
