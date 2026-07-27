"""The ``collections`` field: this resource's place in each publisher-defined series it belongs to
([[field-schema#sources]]).

A collection is **publisher-defined and belongs to nobody**, so its records sit inline in the plugin
block alongside the shared flags -- no owner, no per-user map, nothing to resolve across identities.
That is the whole difference from ``learning_paths``
(:mod:`rehuco_core.learning_path_entries`), which is stored the same way and is otherwise unrelated.

Read-only ([[data-model#write-integrity]]): the projection here coerces defensively and never touches the
payload, so whatever else a record carries -- the cached ``url`` the collection itself owns, a future
``id`` -- survives untouched and a document that is merely *looked at* round-trips byte for byte.
Editing the records is the record-list machinery (#97).
"""

from dataclasses import dataclass
from typing import Any, Final

from .titled_index import titled_index

COLLECTIONS_KEY: Final = "collections"
"""The block-inline key holding this resource's collection memberships ([[field-schema#sources]])."""


@dataclass(frozen=True, order=True)
class CollectionEntry:
    """This resource's place in one publisher-defined series ([[field-schema#sources]]).

    A projection, not the stored record -- the record keeps everything this drops.

    Ordered by ``index`` then ``title``, because ``index`` is a position and not a key: duplicates are
    legal and entries sharing one sort alphabetically ([[field-schema#sources]]).

    :param index: the position within the series; ``0`` when none was recorded.
    :param title: the series name, which is what links a member to it until identities are minted.
    """

    index: int
    title: str


def collection_entries(records: Any) -> list[CollectionEntry]:
    """Project a stored ``collections`` list into sorted :class:`CollectionEntry` values.

    A value that isn't a list reads as no entries at all, and a record that isn't a map is skipped --
    the same defensive read every accessor gives ([[data-model#write-integrity]]).

    :param records: the stored list, as read from the block.
    :returns: the renderable entries, sorted by ``index`` then ``title``.
    """
    if not isinstance(records, list):
        return []
    found = [titled_index(record) for record in records if isinstance(record, dict)]
    return sorted(CollectionEntry(*pair) for pair in found if pair is not None)
