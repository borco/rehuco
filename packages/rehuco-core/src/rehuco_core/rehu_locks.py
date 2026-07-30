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

OPTIONAL_INT_BLOCK_KEYS: Final = ("original_duration", "current_duration", "advertised_duration", "current_count")
"""The active plugin block's shared optional integer scalars, same absent/malformed contract as
:data:`OPTIONAL_INT_CORE_KEYS`."""

OPTIONAL_INT_USER_KEYS: Final = ("rating",)
"""The active block's **per-user** optional integer scalars ([[field-schema#per-user-shared]]); ``0`` is
a genuine rating (ratings may be negative), so *unrated* must read as ``None``, never ``0``."""

OPTIONAL_STR_CORE_KEYS: Final = ("released",)
"""Common-core optional string scalars: absent (or JSON ``null``) reads as ``None``; a present
non-string is malformed -> ``None`` and locks ([[field-schema#deferred-items]])."""

OPTIONAL_STR_BLOCK_KEYS: Final = ("advertised_count",)
"""The active plugin block's shared optional string scalars, same absent/malformed contract as
:data:`OPTIONAL_STR_CORE_KEYS`.

``advertised_count`` is a **string** where its measured counterpart ``current_count`` is an integer: the
pack's own claim may be open-ended (``500+``), and a listing saying "500+ images" claims less than one
saying "500", so storing it as a number would silently strengthen it ([[field-schema#field-types]])."""

REQUIRED_STR_CORE_KEYS: Final = ("id", "description", "created", "updated")
"""Common-core **required** string fields ([[field-schema#field-types]]): absent reads as ``""``; a
present non-string -- JSON ``null`` included -- reads as ``""`` **and** locks, the same
present-but-uncoercible rule ``type`` follows. ``type`` is checked apart from this roster only because
its role earns its own message (:data:`INVALID_TYPE_MESSAGE`); ``released`` is *optional*, so it reads
``None`` rather than ``""`` (:data:`OPTIONAL_STR_CORE_KEYS`)."""

REQUIRED_STR_SOURCE_KEYS: Final = ("title", "publisher", "url")
"""The **primary** source's required string fields ([[field-schema#sources]]), same contract as
:data:`REQUIRED_STR_CORE_KEYS`. Only the primary entry is checked because only the primary entry is
read: a non-primary source's fields reach no getter, so nothing coerces them and no edit can write a
coerced default over them."""

STR_LIST_CORE_KEYS: Final = ("advertised_tags", "extra_tags", "hidden_images")
"""Common-core plain-string lists ([[field-schema#field-types]], [[data-model#image-meanings]]): absent
reads as ``[]``; a non-list, or a list carrying an entry that is not a string, reads as its string
entries alone and locks -- ``authors``'s skip-the-entry-and-lock rule ([[field-schema#authors]]) applied
to the lists whose entries are bare strings."""

INVALID_TYPE_MESSAGE: Final = (
    "type: present but not a string -- the resource type names the active plugin block, so this "
    "document reads as typeless ([[field-schema#resource-types]])."
)
"""The :attr:`~LockReasonKind.INVALID_FIELD` message for a present non-string ``core.type``. The most
load-bearing core field there is: it selects the active block, seeds the session's claim set, and orders
serialization, so a value the getter cannot read leaves *all three* wrong -- and unlike a malformed
scalar, coercing it to a clean default (typeless) discards the one clue to what the file was."""

INVALID_SOURCES_MESSAGE: Final = (
    "sources: present but not a list -- the primary source's title/publisher/url are read from its "
    "entries, so this document reads as source-less ([[field-schema#sources]])."
)
"""The :attr:`~LockReasonKind.INVALID_FIELD` message for a present non-list ``sources``. Only the
*container's* type is checked: a non-dict **entry** is skipped by primary resolution but survives every
save verbatim (the setters append beside it, never over it), so no coerced default can replace it and
the write-integrity rule has nothing to guard -- whereas a non-list container unhooks all three primary
strings at once while a title edit would try to append to it."""

INVALID_AUTHORS_MESSAGE: Final = (
    "authors: contains an entry this build cannot read -- each must be a name string or a "
    "{name, url} record ([[field-schema#authors]])."
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


def coerced_str(value: Any) -> str:
    """One **required** string field's read value ([[field-schema#field-types]]): the stored string, or
    ``""`` when the key is absent, JSON ``null``, or any other non-string.

    The required-string sibling of :func:`optional_str`, and the reason neither getter may say
    ``str(...)``: stringifying reads a ``null`` as the four characters ``None`` and a stray ``123`` as
    ``"123"`` -- text no file carries, which an edit would then save over the malformed-but-recoverable
    original ([[data-model#write-integrity]]). Absent and malformed read alike; only *malformed*
    additionally locks (:func:`invalid_string_reasons`)."""
    return value if isinstance(value, str) else ""


def coerced_str_list(value: Any) -> list[str]:
    """One plain-string list's read value ([[field-schema#field-types]]): the stored list's string
    entries, in order, or ``[]`` when the key is absent or holds a non-list.

    A malformed entry is **skipped** rather than stringified, matching how the ``authors`` getter reads
    a list it cannot fully understand ([[field-schema#authors]]) -- a tag reading ``"None"`` or ``"7"``
    is a value the user never typed, and offering it for editing invites saving it. Skipping (like the
    coercion above) locks the document, so the entry stays recoverable by hand."""
    return [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []


def is_author_record(entry: Any) -> bool:
    """Whether ``entry`` is a valid author record: a dict with a string ``name`` ([[field-schema#authors]])."""
    return isinstance(entry, dict) and isinstance(entry.get("name"), str)


def is_author_entry(entry: Any) -> bool:
    """Whether ``entry`` is one the ``authors`` getter can **read**: a plain name string, or a valid
    author record ([[field-schema#authors]]).

    One predicate for both halves, for the same reason the coercions above live here: skipping an entry
    *is* the lossy read, so the getter
    (:attr:`RehuDocument.authors <rehuco_core.RehuDocument.authors>`) and the
    :attr:`~LockReasonKind.INVALID_FIELD` check (:func:`invalid_field_reasons`) must agree on which
    entries count. Split, a document could read an entry the validator calls malformed -- or the
    reverse, which would let an edit save the shortened list over the original
    ([[data-model#write-integrity]])."""
    return isinstance(entry, str) or is_author_record(entry)


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
    core: dict[str, Any],
    active_block: dict[str, Any],
    active_user_map: dict[str, Any],
    primary_source: dict[str, Any] | None,
) -> list[LockReason]:
    """The :attr:`~LockReasonKind.INVALID_FIELD` reasons for owned fields present-but-uncoercible
    ([[data-model#write-integrity]]).

    An owned field that is merely **absent** reads as a clean default and is fine to save. One that is
    **present** but whose stored value the getter has to coerce lossily is not: writing the coerced
    default back would quietly replace a malformed value the user may yet recover by hand. Each such
    field contributes one reason naming the key.

    ``type`` ([[field-schema#resource-types]]), ``authors`` ([[field-schema#authors]], the seam #92 set
    up), the ``sources`` container ([[field-schema#sources]]), the required strings and string lists
    (:func:`invalid_string_reasons`) and the optional scalars
    ([[field-schema#deferred-items]]) are checked: a non-string ``type`` reads as *typeless*, so it
    names no active block at all; ``authors``'s getter skips an entry that is neither a
    name string nor a ``{name, url}`` record, and a non-list value entirely; an optional scalar's getter
    coerces a present-but-wrong-typed value to ``None`` (:func:`invalid_scalar_reasons`); a required string
    or list reads its empty default, skipping the entries it cannot read; a non-list ``sources`` reads as
    no sources at all, emptying title/publisher/url in one stroke
    (:data:`INVALID_SOURCES_MESSAGE` -- which also says why its *entries* are not checked). All of them are the
    "present but the getter had to coerce" condition. A merely *absent* scalar -- or a JSON ``null``,
    already normalized to absent at construction -- is a clean ``None`` and never locks. The
    ``format_version`` stamp deliberately never does (see
    :attr:`~rehuco_core.RehuDocument.lock_reasons`).

    :param core: the core block's fields.
    :param active_block: the active plugin block's fields.
    :param active_user_map: this document's own per-user submap, as stored.
    :param primary_source: the resolved primary source ([[field-schema#sources]]), whose strings the
        title/publisher/url getters read; ``None`` when the document has no source at all.
    :returns: the invalid-field reasons, in a stable order.
    """
    reasons: list[LockReason] = []
    if "type" in core and not isinstance(core["type"], str):
        reasons.append(LockReason(LockReasonKind.INVALID_FIELD, INVALID_TYPE_MESSAGE))
    if "authors" in core:
        value = core["authors"]
        clean = isinstance(value, list) and all(is_author_entry(entry) for entry in value)
        if not clean:
            reasons.append(LockReason(LockReasonKind.INVALID_FIELD, INVALID_AUTHORS_MESSAGE))
    if "sources" in core and not isinstance(core["sources"], list):
        reasons.append(LockReason(LockReasonKind.INVALID_FIELD, INVALID_SOURCES_MESSAGE))
    reasons.extend(invalid_string_reasons(core, primary_source))
    reasons.extend(invalid_scalar_reasons(core, active_block, active_user_map))
    return reasons


def invalid_string_reasons(core: dict[str, Any], primary_source: dict[str, Any] | None) -> list[LockReason]:
    """One :attr:`~LockReasonKind.INVALID_FIELD` per **required** string or string list that is present
    but not what its getter reads ([[field-schema#field-types]]).

    The string half of :func:`invalid_scalar_reasons`, and the same rule: a field the getter must read
    past -- a ``null`` title, a number among the tags -- locks, so an edit cannot save the coerced ``""``
    (or the shortened list) over the malformed-but-recoverable original ([[data-model#write-integrity]]).
    A ``null`` locks here where it does not for an optional scalar, because the two mean different
    things: ``null`` *is* the absent spelling of a value that may be absent, while for a field whose
    default is ``""`` it is a value nothing wrote deliberately.

    :param core: the core block's fields.
    :param primary_source: the resolved primary source, or ``None`` when there is none.
    :returns: the invalid-string reasons, core scalars before the primary source's before the lists,
        in key order.
    """
    reasons: list[LockReason] = []
    for block, keys in ((core, REQUIRED_STR_CORE_KEYS), (primary_source or {}, REQUIRED_STR_SOURCE_KEYS)):
        for key in keys:
            if key in block and not isinstance(block[key], str):
                reasons.append(LockReason(LockReasonKind.INVALID_FIELD, invalid_string_message(key, "a string")))
    for key in STR_LIST_CORE_KEYS:
        if key in core and coerced_str_list(core[key]) != core[key]:
            reasons.append(LockReason(LockReasonKind.INVALID_FIELD, invalid_string_message(key, "a list of strings")))
    return reasons


def invalid_string_message(key: str, expected: str) -> str:
    """The :attr:`~LockReasonKind.INVALID_FIELD` message for a present-but-malformed required string."""
    return f"{key}: present but not {expected} ([[field-schema#field-types]])."


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
    :returns: the invalid-scalar reasons, the integers first (core before shared-block before per-user)
        then the strings (core before shared-block), in key order.
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
    # each string group names what its keys should have been, since a malformed ``released`` and a
    # malformed ``advertised_count`` are wrong in different ways and the message says which
    str_sources = (
        (core, OPTIONAL_STR_CORE_KEYS, "a date string"),
        (active_block, OPTIONAL_STR_BLOCK_KEYS, "a count string"),
    )
    for block, keys, expected in str_sources:
        for key in keys:
            value = block.get(key)
            if value is not None and not isinstance(value, str):
                reasons.append(LockReason(LockReasonKind.INVALID_FIELD, invalid_scalar_message(key, expected)))
    return reasons


def invalid_scalar_message(key: str, expected: str) -> str:
    """The :attr:`~LockReasonKind.INVALID_FIELD` message for a present-but-malformed optional scalar."""
    return f"{key}: present but not {expected} ([[field-schema#deferred-items]])."
