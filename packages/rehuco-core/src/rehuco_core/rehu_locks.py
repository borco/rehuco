"""Lock-reason **derivation** for a genuinely-parsed document, and the field-value coercion the two
consumers of a field share ([[data-model#write-integrity]]).

Where :mod:`rehuco_core.lock_reasons` holds the read-only *vocabulary* (the :class:`LockReasonKind` enum,
the :class:`LockReason` record, the save-blocking set), this holds the *computation*: given a document's
already-derived views -- its core block, its active block, its per-user submap, its versions -- which
:class:`LockReason` s does it carry. Splitting it off keeps ``RehuDocument.lock_reasons`` to orchestration
(the load-failure / legacy-``.tc`` / newer-file causes, which are document *state*, stay there) and this to
the per-field and per-block checks, which are pure functions of the payload.

The optional-scalar **coercion** predicates (:func:`optional_int`, :func:`optional_str`) live here rather
than beside the accessors because a field is lock-worthy *exactly when* its coercion is lossy -- the read
value and the validity verdict are the same computation, so one home keeps the getter and the
:attr:`~LockReasonKind.INVALID_FIELD` check from ever disagreeing about what counts as malformed (the
``bool``-is-not-an-``int`` subtlety, most of all). The document's typed getters import these to *read*;
:func:`invalid_field_reasons` uses them to *validate*. The optional-scalar key groups
(:data:`OPTIONAL_INT_CORE_KEYS` and its siblings) are the single roster both this validation and the
document's null-normalization walk.
"""

from typing import Any, Final

from .lock_reasons import LockReason, LockReasonKind
from .migrations import current_block_version
from .plugins import PluginRegistry

OPTIONAL_INT_CORE_KEYS: Final = ("original_size", "current_size")
"""Common-core optional integer scalars ([[field-schema#deferred-items]]): absent (or JSON ``null``)
reads as ``None``, a present non-int coerces to ``None`` for display **and** locks the document
(:attr:`~LockReasonKind.INVALID_FIELD`) -- absent is not ``0``."""

OPTIONAL_INT_BLOCK_KEYS: Final = ("original_duration", "current_duration", "advertised_duration", "images_count")
"""The active plugin block's shared optional integer scalars, same absent/malformed contract as
:data:`OPTIONAL_INT_CORE_KEYS`."""

OPTIONAL_INT_USER_KEYS: Final = ("rating",)
"""The active block's **per-user** optional integer scalars ([[field-schema#per-user-shared]]); ``0`` is
a genuine rating (ratings may be negative), so *unrated* must read as ``None``, never ``0``."""

OPTIONAL_STR_CORE_KEYS: Final = ("released",)
"""Common-core optional string scalars: absent (or JSON ``null``) reads as ``None``; a present
non-string is malformed -> ``None`` and locks ([[field-schema#deferred-items]])."""

INVALID_AUTHORS_MESSAGE: Final = (
    "authors: contains an entry this build cannot read -- each must be a name string or a "
    "{name, url} record ([[field-schema#authors]])"
)
"""The :attr:`~LockReasonKind.INVALID_FIELD` message for a present ``authors`` the getter cannot read
cleanly -- a non-list, or a list with an entry it would skip ([[field-schema#authors]])."""


def optional_int(value: Any) -> int | None:
    """One optional integer scalar's read value ([[field-schema#deferred-items]]): the stored ``int``
    (``bool`` excluded, an ``int`` subclass), or ``None`` when the key is absent, JSON ``null``, or a
    malformed non-int. Absent and malformed both display as ``None``; only *malformed* additionally
    locks the document (:func:`invalid_field_reasons`)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def optional_str(value: Any) -> str | None:
    """One optional string scalar's read value: the stored string, or ``None`` when the key is absent,
    JSON ``null``, or a malformed non-string (which also locks). Unlike an integer field there is
    nothing further to coerce -- a stored string is already its own value."""
    return value if isinstance(value, str) else None


def is_author_record(entry: Any) -> bool:
    """Whether ``entry`` is a valid author record: a dict with a string ``name`` ([[field-schema#authors]])."""
    return isinstance(entry, dict) and isinstance(entry.get("name"), str)


def newer_block_format_reason(active_key: str, block_version: int | None, plugins: PluginRegistry) -> LockReason | None:
    """The :attr:`~LockReasonKind.NEWER_BLOCK_FORMAT` reason when the **active** block's own
    ``format_version`` is newer than its plugin understands ([[plugins#plugin-blocks]], the per-block
    refinement of :attr:`~rehuco_core.RehuDocument.lock_reasons`'s ``NEWER_FORMAT`` check).

    Only computed when a plugin is installed for the active key -- an uninstalled type's block has no
    ``current_block_version`` to compare against, and is handled by the fallback-editor path instead
    ([[plugins#fallback-editor]]). The active block is never restamped by migration when its plugin is
    absent, so the version passed here is whatever the block actually carries.

    :param active_key: the active block's key.
    :param block_version: the active block's coerced ``format_version`` (``0`` when absent/malformed,
        ``None`` when there is no active block at all); ``None`` is read as ``0``.
    :param plugins: the plugins installed here, for resolution and the plugin's current block version.
    :returns: the reason naming the block and its versions, or ``None`` when it is at or below what the
        plugin understands, or no plugin is installed for the active key.
    """
    if plugins.resolve(active_key) is None:
        return None
    head = current_block_version(active_key)
    version = block_version or 0
    if version <= head:
        return None
    return LockReason(
        LockReasonKind.NEWER_BLOCK_FORMAT,
        f"The {active_key!r} block's format_version {version} is newer than the installed plugin understands ({head}).",
    )


def invalid_field_reasons(
    core: dict[str, Any], active_block: dict[str, Any], active_user_map: dict[str, Any]
) -> list[LockReason]:
    """The :attr:`~LockReasonKind.INVALID_FIELD` reasons for owned fields present-but-uncoercible
    ([[data-model#write-integrity]]).

    An owned field that is merely **absent** reads as a clean default and is fine to save. One that is
    **present** but whose stored value the getter has to coerce lossily is not: writing the coerced
    default back would quietly replace a malformed value the user may yet recover by hand. Each such
    field contributes one reason naming the key.

    ``authors`` ([[field-schema#authors]], the seam #92 set up) and the optional scalars
    ([[field-schema#deferred-items]]) are checked: ``authors``'s getter skips an entry that is neither a
    name string nor a ``{name, url}`` record, and a non-list value entirely; an optional scalar's getter
    coerces a present-but-wrong-typed value to ``None`` (:func:`invalid_scalar_reasons`). Both are the
    "present but the getter had to coerce" condition. A merely *absent* scalar -- or a JSON ``null``,
    already normalized to absent at construction -- is a clean ``None`` and never locks. The
    ``format_version`` stamp deliberately never does (see
    :attr:`~rehuco_core.RehuDocument.lock_reasons`).

    :param core: the core block's fields.
    :param active_block: the active plugin block's fields.
    :param active_user_map: this document's own per-user submap, as stored.
    :returns: the invalid-field reasons, in a stable order.
    """
    reasons: list[LockReason] = []
    if "authors" in core:
        value = core["authors"]
        clean = isinstance(value, list) and all(isinstance(entry, str) or is_author_record(entry) for entry in value)
        if not clean:
            reasons.append(LockReason(LockReasonKind.INVALID_FIELD, INVALID_AUTHORS_MESSAGE))
    reasons.extend(invalid_scalar_reasons(core, active_block, active_user_map))
    return reasons


def invalid_scalar_reasons(
    core: dict[str, Any], active_block: dict[str, Any], active_user_map: dict[str, Any]
) -> list[LockReason]:
    """One :attr:`~LockReasonKind.INVALID_FIELD` per optional scalar that is **present but malformed**
    ([[field-schema#deferred-items]], the #92 ``authors`` precedent extended to the scalars).

    A scalar that is absent -- or a JSON ``null``, already stripped to absent at construction -- reads as
    a clean ``None`` and does not lock. One that is *present* with a value the getter must coerce away (a
    string where a whole number belongs, a non-string where the date belongs) does, so an edit can never
    save the coerced ``None`` over the malformed-but-recoverable original ([[data-model#write-integrity]]).

    :param core: the core block's fields.
    :param active_block: the active plugin block's fields.
    :param active_user_map: this document's own per-user submap, as stored.
    :returns: the invalid-scalar reasons, core before shared-block before per-user, in key order.
    """
    reasons: list[LockReason] = []
    int_sources = (
        (core, OPTIONAL_INT_CORE_KEYS),
        (active_block, OPTIONAL_INT_BLOCK_KEYS),
        (active_user_map, OPTIONAL_INT_USER_KEYS),
    )
    for block, keys in int_sources:
        for key in keys:
            value = block.get(key)
            if value is not None and optional_int(value) is None:
                reasons.append(LockReason(LockReasonKind.INVALID_FIELD, invalid_scalar_message(key, "a whole number")))
    for key in OPTIONAL_STR_CORE_KEYS:
        value = core.get(key)
        if value is not None and not isinstance(value, str):
            reasons.append(LockReason(LockReasonKind.INVALID_FIELD, invalid_scalar_message(key, "a date string")))
    return reasons


def invalid_scalar_message(key: str, expected: str) -> str:
    """The :attr:`~LockReasonKind.INVALID_FIELD` message for a present-but-malformed optional scalar."""
    return f"{key}: present but not {expected} ([[field-schema#deferred-items]])."
