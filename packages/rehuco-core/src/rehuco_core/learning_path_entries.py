"""The ``learning_paths`` field: whose paths this resource is in, and which of them an identity may see
([[field-schema#learning-path-ownership]]).

A learning path is **somebody's** -- one person curates its order -- so its records live in the plugin
block's ``users`` map ([[field-schema#per-user-shared]]) and ownership is expressed by *where a record
sits and what it carries*: a full ``{title, index, ref}`` is owned, a bare ``{ref}`` is a subscription to
whichever record owns that slot, and the reserved ``public`` scope holds what was published to everyone.
Reading the field therefore means resolving across identities, which is why it is nothing like
``collections`` (:mod:`rehuco_core.collection_entries`) despite being stored the same way.

Everything here past :func:`learning_path_records_by_scope` works on the **scope -> records** mapping that
function projects, not on the raw ``users`` map: the map also holds ratings and per-user flags that none
of this is about, and an editor that has to write records back should be handed the records and nothing
else ([[data-model#write-integrity]]). Nothing here touches the payload -- an unresolvable ``ref`` is
ignored on read rather than repaired -- so a document that is merely *looked at* round-trips byte for byte.
"""

from dataclasses import dataclass
from typing import Any, Final

from .plugins import PUBLIC_USERNAME
from .titled_index import titled_index

LEARNING_PATHS_KEY: Final = "learning_paths"
"""The per-user key holding one identity's learning-path records ([[field-schema#learning-path-ownership]])."""

REF_KEY: Final = "ref"
"""The **file-scoped slot** a path is minted with and a subscription points at
([[field-schema#learning-path-ownership]]).

Deliberately a small integer rather than a UUID, and never compared across files: it exists so a
subscription survives its owner retitling the path, which linking by name could not."""


@dataclass(frozen=True, order=True)
class LearningPathEntry:
    """One learning path as an identity sees it ([[field-schema#learning-path-ownership]]).

    Deliberately **not** the same type as `CollectionEntry`, despite the matching fields: a path is
    *owned* -- somebody curates its order, publishing copies it, a subscriber follows the owner's
    retitling -- where a collection belongs to nobody. Nothing that reads one should silently accept the
    other.

    Ordered by ``index`` then ``title``. The tie-break carries real weight here: every imported path
    arrives at ``index: 0`` to say *no order chosen yet* ([[field-schema#sources]]'s legacy-import rule,
    #188), so alphabetical is the only order such a set has.

    :param index: the curated position; ``0`` when the owner has chosen none.
    :param title: the path's name **as its owner spells it** -- a subscriber has no title of its own.
    """

    index: int
    title: str


def learning_path_ref(record: dict[str, Any]) -> int | None:
    """The file-scoped slot one stored record carries, if it carries a usable one.

    Coerced the way every accessor here coerces ([[data-model#write-integrity]]): a missing, non-integer
    or boolean ``ref`` reads as none at all. ``bool`` is excluded explicitly because Python's ``True``
    *is* an ``int``, and a slot numbered ``1`` by a stray ``true`` would silently collide with a real one.

    :param record: one stored learning-path record.
    :returns: the slot, or ``None`` when the record carries none this reader can use.
    """
    ref = record.get(REF_KEY)
    return ref if isinstance(ref, int) and not isinstance(ref, bool) else None


def learning_path_records_by_scope(users: Any) -> dict[str, list[dict[str, Any]]]:
    """Project a block's ``users`` map into the **scope -> records** mapping the rest of this module
    (and the editor) works on ([[field-schema#learning-path-ownership]]).

    The learning-path slice of the map and nothing else: the ratings and per-user flags sitting beside it
    are a different field's business, and handing an editor the whole map would hand it the power to lose
    them. Scopes carrying no records at all are left out, so the mapping reads as *who has paths*.

    :param users: the block's ``users`` map, as stored; anything that isn't a map reads as no paths.
    :returns: ``{scope: records}``, the records by reference and in stored order.
    """
    if not isinstance(users, dict):
        return {}
    found = {scope: learning_path_records(users.get(scope)) for scope in users}
    return {scope: records for scope, records in found.items() if records}


def visible_learning_paths(
    records_by_scope: dict[str, list[dict[str, Any]]], *, username: str
) -> list[LearningPathEntry]:
    """The learning paths ``username`` sees ([[field-schema#learning-path-ownership]]).

    Three sources, per the viewer rule: this identity's **own** records, its **subscriptions** (resolved
    against whichever record in this block owns that ``ref``), and the reserved ``public`` scope
    (:data:`~rehuco_core.PUBLIC_USERNAME`), which is visible to everyone without subscribing. Another
    user's *private* paths are never included -- the **editor** shows those, in its all-scopes view, which
    is a different question ("what is in this file") from this one ("what am I in").

    An **unresolvable ``ref`` is ignored** rather than rendered blank or raised on: a subscription whose
    target is gone is nothing. A path reached twice -- subscribed to *and* published, say -- renders
    once, keyed by its ``ref``; a record carrying no ``ref`` at all can't be recognized as a duplicate of
    anything, so it renders on its own terms.

    :param records_by_scope: the block's learning-path records per scope
        (:func:`learning_path_records_by_scope`).
    :param username: the identity to resolve for -- the *current* one, which for a freshly imported
        document is not the ``unknown`` the import filed its state under (the identity-collapse item in
        [[field-schema#deferred-items]]).
    :returns: the visible paths, sorted by ``index`` then ``title``.
    """
    owned = owned_learning_paths(records_by_scope)
    found: dict[int, LearningPathEntry] = {}
    unreferenced: list[LearningPathEntry] = []
    # the current identity first, then the public scope; a path in both is the same path, deduplicated
    # by ref below rather than shown twice
    for scope in dict.fromkeys((username, PUBLIC_USERNAME)):
        for record in records_by_scope.get(scope, []):
            ref = learning_path_ref(record)
            if ref is None:
                # no slot to subscribe by, so it is whatever it carries itself -- and nothing else in
                # the file can be the same path, since nothing can point at it
                if (refless := titled_index(record)) is not None:
                    unreferenced.append(LearningPathEntry(*refless))
                continue
            # the identity's own title wins over the copy publishing left behind; a bare ``{ref}``
            # resolves to whichever record owns that slot, and stays unrendered when none does
            own = titled_index(record)
            resolved = LearningPathEntry(*own) if own is not None else owned.get(ref)
            if resolved is not None:
                found.setdefault(ref, resolved)
    return sorted([*found.values(), *unreferenced])


def owned_learning_paths(records_by_scope: dict[str, list[dict[str, Any]]]) -> dict[int, LearningPathEntry]:
    """Index every **owned** learning path in a block by its ``ref``
    ([[field-schema#learning-path-ownership]]).

    What a subscription resolves against: an owned record is a full one, whoever holds it, so a
    subscriber's bare ``{ref}`` finds its title and index here regardless of which identity owns the
    original -- that is the point of :data:`REF_KEY` being a file-scoped slot rather than a name.

    Scopes are walked in name order so a file that (malformedly) has two owners of one ``ref`` resolves
    the same way every time rather than by mapping insertion order.

    :param records_by_scope: the block's learning-path records per scope
        (:func:`learning_path_records_by_scope`).
    :returns: ``{ref: path}`` for every owned record carrying an integer ``ref``.
    """
    owned: dict[int, LearningPathEntry] = {}
    for scope in sorted(records_by_scope):
        for record in records_by_scope[scope]:
            ref = learning_path_ref(record)
            found = titled_index(record)
            if found is not None and ref is not None:
                owned.setdefault(ref, LearningPathEntry(*found))
    return owned


def learning_path_records(user: Any) -> list[dict[str, Any]]:
    """One identity's learning-path records, as stored.

    :param user: one entry of the ``users`` map; anything that isn't a map reads as no records.
    :returns: the stored records, skipping any that isn't a map.
    """
    if not isinstance(user, dict):
        return []
    records = user.get(LEARNING_PATHS_KEY)
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]
