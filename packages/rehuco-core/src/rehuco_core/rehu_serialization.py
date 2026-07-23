"""Canonical ``.rehu`` key ordering: the exact top-to-bottom layout a save writes to disk.

The ordering is a property of the *write*, not of the document ([[data-model#rehu-format]]): JSON objects
are unordered, so ``RehuDocument.__data`` carries its keys in whatever order construction and the setters
left them, and order is imposed only here, at the one boundary that produces a file. Splitting it out of
the document (as :mod:`rehuco_core.lock_reasons` split the lock vocabulary) keeps it a set of **pure
functions of the payload** -- no session state, no ``self`` -- so the byte-for-byte layout two differently
built documents share (a converted ``.tc`` and a migrated v1 file) is decided in one readable place.

The block persistence invariant ([[plugins#plugin-blocks]]) reaches this layer only as its *result*: the
caller passes in which blocks are dropped (``RehuDocument`` computes that from session state, its single
:meth:`~rehuco_core.rehu_document.RehuDocument._RehuDocument__dropped_block_keys` predicate), so the
serialization never re-derives it and the logged discard can never diverge from what is written.
"""

from collections.abc import Iterable, Sequence
from typing import Any, Final

from .plugins import USERS_KEY
from .rehu_format import CORE_BLOCK_KEY, FORMAT_VERSION_KEY, RESERVED_KEYS

CORE_LEADING_KEYS: Final = ("type", "id", "created", "updated", "sources")
"""The core block's keys that lead the file, in this order; everything else follows alphabetically
(:func:`ordered_for_file`).

What a reader looks for first when opening a `.rehu` by hand: what it is, which record it is, when it was
made, and -- via ``sources`` -- what it is *called* ([[field-schema#sources]]). Everything after is
alphabetical, which is why this list can stay short and needs no maintenance: a field missing from it
merely sorts with the rest, it is never misplaced. Unlike a *recognition* list (a migration's frozen
common-field set), being incomplete here costs nothing."""


def ordered_for_file(data: dict[str, Any], active_key: str, dropped_keys: Iterable[str]) -> dict[str, Any]:
    """Lay the document out in canonical key order, for :meth:`~rehuco_core.rehu_document.RehuDocument.save`
    to write.

    The top-level order is ``format_version`` (it describes the file), then ``core``, then the
    **active** plugin block, then every remaining top-level key alphabetically -- the inactive/unknown
    blocks, plus any stray key carried verbatim, which sorts among them rather than needing a category
    of its own. The active block leads the blocks (rather than sorting among them) because it is the
    one this file's ``type`` names -- the block a reader opening the file by hand looks for first,
    right after the common core it belongs to.

    Inside ``core``, :data:`CORE_LEADING_KEYS` lead and the rest sort. The **active** block is
    ordered the same way, led by its own ``format_version`` ([[plugins#plugin-blocks]]) -- and if it
    carries a ``users`` map (#98, [[field-schema#per-user-shared]]), that map is ordered too:
    usernames alphabetically, each user's own fields alphabetically (:func:`ordered_block` applies
    this one level deeper, see there).

    **The block persistence invariant is applied here** ([[plugins#plugin-blocks]]): a block is
    written **iff** it is the active block, or it is inactive and its key is not in ``dropped_keys``
    (foreign payload the file is merely custodian of -- carried verbatim, never reordered, since
    reordering would churn bytes to reorganize fields this document does not understand). A block
    **claimed then abandoned** -- named by ``dropped_keys`` -- is skipped: by claiming and leaving it
    the user asserted the file is no longer that type. The caller supplies ``dropped_keys`` from its own
    session state (``RehuDocument``'s single ``__dropped_block_keys`` predicate), so this stays a pure
    function of the payload and the logged discard can never diverge from what is written.

    A retained active/foreign block that is malformed (not an object) is passed through as-is rather
    than skipped -- it is still the file's content, and dropping it would be exactly the silent loss
    the round-trip rule forbids ([[data-model#schema-version]]).

    :param data: the backing payload; left untouched, since its own key order is not meaningful.
    :param active_key: the key of the block the document's ``type`` names, empty when typeless.
    :param dropped_keys: the block keys the persistence invariant drops on this save.
    :returns: a fresh dict in canonical order.
    """
    # not a guarded read: `rehuco_core.migrations` stamps every payload it is handed, including an
    # empty one, so a constructed document always carries a version
    ordered: dict[str, Any] = {FORMAT_VERSION_KEY: data[FORMAT_VERSION_KEY]}
    if CORE_BLOCK_KEY in data:
        ordered[CORE_BLOCK_KEY] = ordered_block(data[CORE_BLOCK_KEY], CORE_LEADING_KEYS)
    if active_key in data:
        # the active block leads the plugin blocks, right after the core it belongs to -- its own
        # format_version first, then the rest of its keys ordered ([[plugins#plugin-blocks]])
        ordered[active_key] = ordered_block(data[active_key], (FORMAT_VERSION_KEY,))
    dropped = set(dropped_keys)
    for key in sorted(key for key in data if key not in RESERVED_KEYS and key != active_key):
        if key in dropped:
            # claimed-then-abandoned: made active this session and left, so the user asserted the file
            # is no longer this type -- dropped on save ([[plugins#plugin-blocks]]).
            continue
        ordered[key] = data[key]
    return ordered


def ordered_block(block: Any, leading: Sequence[str]) -> Any:
    """Order one block's keys: ``leading`` first, in the given order, then the rest alphabetically.

    A ``users`` map (#98, [[field-schema#per-user-shared]]), if present, is ordered one level
    deeper too (:func:`ordered_users_map`) -- it is per-user storage *inside* the block, not a
    block of its own, so it doesn't get a second top-level pass through this function, but it still
    owes the same canonical-order guarantee every other key here gets.

    :param block: the block's value; returned untouched when it is not an object
        ([[data-model#write-integrity]]).
    :param leading: the keys to place first; those absent from ``block`` are skipped.
    :returns: the block with its keys ordered.
    """
    if not isinstance(block, dict):
        return block
    lead = [key for key in leading if key in block]
    ordered = {key: block[key] for key in (*lead, *sorted(set(block) - set(lead)))}
    if USERS_KEY in ordered:
        ordered[USERS_KEY] = ordered_users_map(ordered[USERS_KEY])
    return ordered


def ordered_users_map(users: Any) -> Any:
    """Order a block's ``users`` map: usernames alphabetically, and each user's own fields
    alphabetically ([[field-schema#per-user-shared]]) -- the same discipline :func:`ordered_block`
    applies to a block's own keys, one level deeper.

    :param users: the block's ``users`` value; returned untouched when it is not an object
        ([[data-model#write-integrity]]).
    :returns: the map with usernames and each user's fields ordered; a per-user value that isn't
        an object is passed through as-is, the same tolerance :func:`ordered_block` gives a
        malformed block.
    """
    if not isinstance(users, dict):
        return users
    ordered: dict[str, Any] = {}
    for username in sorted(users):
        fields = users[username]
        ordered[username] = {key: fields[key] for key in sorted(fields)} if isinstance(fields, dict) else fields
    return ordered
