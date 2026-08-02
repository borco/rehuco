"""The ``collections`` field: this resource's place in each publisher-defined series it belongs to
([[field-schema#sources]]).

A collection is **publisher-defined and belongs to nobody**, so its records sit inline in the plugin
block alongside the shared flags -- no owner, no per-user map, nothing to resolve across identities.
That is the whole difference from ``learning_paths``
(:mod:`rehuco_core.learning_path_entries`), which is stored the same way and is otherwise unrelated.

Two readings, deliberately separate ([[data-model#write-integrity]]). :func:`collection_entries` is the
**display projection**: coerced defensively, sorted, and dropping everything a viewer has no cell for.
:func:`collection_records` is the **stored records themselves**, which is what an editor must hold --
whatever else a record carries (the cached ``url`` the collection itself owns, a future ``id``) has to
survive an edit to the title beside it (#235's merge contract), and nothing but the records can carry it.
Neither touches the payload, so a document that is merely *looked at* round-trips byte for byte.
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
    found = [titled_index(record) for record in collection_records(records)]
    return sorted(CollectionEntry(*pair) for pair in found if pair is not None)


def collection_records(records: Any) -> list[dict[str, Any]]:
    """The stored ``collections`` records themselves, in stored order ([[field-schema#sources]]).

    What an **editor** binds to, where :func:`collection_entries` is what a *viewer* binds to: a title
    cell that wrote back a rebuilt ``{title, index}`` would drop the ``url`` the collection owns and any
    key a later version adds, on an entry nobody meant to touch (#235). Only the records carry those, so
    only the records can be edited.

    Defensive in the same two ways the projection is ([[data-model#write-integrity]]): a value that isn't
    a list reads as no records, and a record that isn't a map is skipped. Stored **order** is kept -- it
    means nothing (``index`` is the position, [[field-schema#sources]]), which is exactly why an editor
    must not quietly rewrite it.

    :param records: the stored list, as read from the block.
    :returns: the records, by reference -- a caller that edits one copies it first (the merge contract).
    """
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]
