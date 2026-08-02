"""The one rule two otherwise-unrelated record lists share: how a stored record's **title and position**
are read, and how an editor writes one back ([[field-schema#field-types]]).

A *shape* rule, not a concept. ``collections`` and ``learning_paths`` store different things for
different reasons -- a publisher's series belongs to nobody, a learning path is somebody's -- and they
keep their own types and their own modules ([[field-schema#sources]],
[[field-schema#learning-path-ownership]]). What they genuinely have in common is that each record names
something and says where this resource sits in it, coerced identically; that lives here so neither
module owns the other's reading, and so a third field with the same shape needs no third copy.
"""

from typing import Any, Final

TITLE_KEY: Final = "title"
"""A record's display name -- what it names, and (until identities are minted) what links to it."""

INDEX_KEY: Final = "index"
"""A record's position in the thing it names; absent means none was chosen ([[field-schema#sources]])."""


def titled_index(record: dict[str, Any]) -> tuple[int, str] | None:
    """The ``(index, title)`` pair a stored record renders as, or ``None`` when it has no title to show.

    Coerced defensively ([[data-model#write-integrity]]): a missing or non-integer ``index`` reads as
    ``0`` -- the same *no position chosen* a legacy import writes ([[field-schema#sources]]) -- and a
    record with no usable ``title`` is refused outright, since it has nothing to show and a blank row
    would read as an entry that isn't there. The record itself is never touched.

    Returns the bare pair rather than a value type: each caller wraps it in its own, which is what keeps
    the shared reading from becoming a shared *type*.

    :param record: one stored record.
    :returns: the pair, or ``None`` when the record carries no usable ``title``.
    """
    title = record.get(TITLE_KEY)
    if not isinstance(title, str) or not title.strip():
        return None
    index = record.get(INDEX_KEY)
    return (index if isinstance(index, int) and not isinstance(index, bool) else 0), title


def with_titled_index(record: dict[str, Any], *, title: str | None = None, index: int | None = None) -> dict[str, Any]:
    """``record`` under a new title and/or position, **keeping every other key it carries** (#235).

    The write half of :func:`titled_index`, and the merge rule both record lists' editors are held to: a
    cell writes back into the record its row was built from, changing only the key it owns. Rebuilding
    the record from the two cells a table can show instead would sever a collection's cached ``url`` or a
    learning path's ``ref`` -- and with the ``ref``, every subscription to it
    ([[field-schema#learning-path-ownership]]) -- on an entry nobody meant to touch. That loss is
    *invisible*, which is what makes it the one worth writing a function against.

    A **new record** every time: a document hands its lists out by reference, so mutating one in place
    would move an unsaved document's own state under it ([[data-model#write-integrity]]).

    ``index`` is written even when it is ``0``, rather than dropped as an absent-not-zero optional would
    be: for this key absent and ``0`` are *defined* to be the same value (:func:`titled_index` reads one
    as the other) and the legacy import writes it explicitly (#188), so storing it keeps an edited record
    looking like an imported one instead of minting a second spelling of *no position chosen*.

    :param record: the record to edit.
    :param title: the new title, or ``None`` to leave it as it is.
    :param index: the new position, or ``None`` to leave it as it is.
    :returns: a new record carrying the change and everything else ``record`` had.
    """
    edited = dict(record)
    if title is not None:
        edited[TITLE_KEY] = title
    if index is not None:
        edited[INDEX_KEY] = index
    return edited
