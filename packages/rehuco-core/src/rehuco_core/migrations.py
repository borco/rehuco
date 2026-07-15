"""Read-time format migrations: bring an older ``.rehu`` payload up to the current layout
([[data-model#schema-version]]).

Migrations run **in memory, on load** ([[data-model#rehu-format]]): the payload is upgraded *and*
restamped there and then, so nothing downstream ever handles a half-migrated document and
`RehuDocument`'s accessors only have to understand the current shape. The **file** is untouched until
something saves it -- opening an old file never rewrites it -- and because the payload is already
consistent, `RehuDocument.save` is a plain dump that carries the new layout and its stamp to disk
together.

**Nobody invokes a migration.** `RehuDocument` upgrades whatever payload it is handed, so every reader
past that boundary sees the current layout and no caller decides, or can forget, to migrate. The steps
are therefore private: this module's whole surface is :func:`migrate_rehu_data`.

**A foreign format is never a step here** ([[data-model#schema-version]]). Reading a `.tc`
([[acquisition-tooling#tc-to-rehu]]) -- or a `.dpdml` later ([[daz3d-personal-database#import-needs]]) --
is an *import*, not a migration: it renames files, deletes originals, and mints the resource's UUID and
timestamps, so it must stay a deliberate, confirmed act. Running it the way this module runs (unasked, on
every load) would rewrite a user's files merely because they opened one. Everything here is safe to run
unasked precisely because it does none of that. The tell is that such a payload could never be *routed*
to anyway: this chain dispatches on a `.rehu` version, and a foreign file has none -- which is also why a
`.tc` is not "format v0".

The payload's version is **resolved once**, and the chain dispatches on that number -- each step named
for the transition it performs (``__v1_to_v2``) and run when the version is below its target. A step
never re-derives "is this mine?" from the payload's shape, so a future migration whose change leaves no
shape marker at all (renaming a field *inside* ``core``, say) dispatches exactly like the ones that do.

Resolving the version is **not** the same as reading :data:`FORMAT_VERSION_KEY`, because a stamp is not
guaranteed to be there or to be sane. Every payload that passes through here leaves stamped, and the
`.tc` mapping stamps what it builds ([[acquisition-tooling#tc-to-rehu]]), so an unstamped payload
(**v0**) came from before stamping or from outside rehuco. v0 names no layout of its own, so it is the
one case where the payload's shape is read, to say which layout it actually has; see ``RehuMigrator``.
"""

from typing import Any, Final

from rehuco_core.plugins import CORE_BLOCK_KEY

FORMAT_VERSION_KEY: Final = "format_version"
"""The file-wide schema-version key ([[data-model#schema-version]]); the one top-level key that is not a
block, since it describes the file's own layout rather than holding fields."""

CURRENT_FORMAT_VERSION: Final = 2
"""The file-wide ``format_version`` this build understands, and stamps onto every payload it reads
([[data-model#schema-version]]).

- **v2** nests the common fields under the ``core`` block ([[data-model#rehu-format]]).
- **v1** kept them at the top level (:data:`V1_COMMON_FIELD_KEYS`).
- **v0** is the absence of a stamp -- a gap rather than a layout of its own. No payload leaves this
  module unstamped, and the `.tc` mapping stamps what it builds ([[acquisition-tooling#tc-to-rehu]]), so
  v0 means a payload from outside rehuco, or from before stamping. ``RehuMigrator`` infers such a
  payload's layout from its shape, and never dispatches on ``0`` -- there is no "v0 layout" to upgrade
  *from*.
"""

V1_COMMON_FIELD_KEYS: Final = frozenset(
    {
        "type",
        "id",
        "sources",
        "authors",
        "released",
        "created",
        "updated",
        "description",
        "advertised_tags",
        "extra_tags",
        "original_size",
        "current_size",
        "hidden_images",
    }
)
"""The common-core keys **format version 1 kept at the top level**, before they moved into the ``core``
block ([[data-model#rehu-format]]).

A frozen historical fact, not a live list: it describes a layout this build only ever *reads*, so the
v1 -> v2 step is its only consumer and a newly-added common field never belongs here.

That it can be frozen is the whole argument for the ``core`` block. While the common fields sat at the
top level they had to be recognized **by name** to tell them from plugin blocks, so this list had to
track every one of them forever -- and a field missing from it would silently read as a plugin block. A
common field added by a *newer* build was worse still: unknown by name, object-valued, and therefore
indistinguishable from an uninstalled plugin's block. Nesting the core under its own key replaces the
whole list with one reserved name ([[plugins#core-vs-plugin]])."""


def stamped_version(data: dict[str, Any]) -> int | None:
    """Read a payload's ``format_version`` stamp defensively ([[data-model#schema-version]]).

    The one place that decides whether a stamp is usable, since two callers need that judgement and must
    not disagree about it: this module, to pick which migrations to run, and `RehuDocument`, to report
    what a file says. A ``bool`` is malformed despite being an ``int`` subclass.

    ``None`` means the payload does not usably say -- absent or malformed, which are the same thing to a
    reader and are both **v0** ([[data-model#schema-version]]). Callers decide what to do about not
    knowing: the migrator reads the payload's shape, while `RehuDocument.format_version` reports ``0``.

    :param data: the parsed JSON object.
    :returns: the stamped version, or ``None`` when it is absent or malformed.
    """
    stamp = data.get(FORMAT_VERSION_KEY)
    return stamp if isinstance(stamp, int) and not isinstance(stamp, bool) else None


def migrate_rehu_data(data: dict[str, Any]) -> None:
    """Bring a parsed ``.rehu`` payload up to :data:`CURRENT_FORMAT_VERSION`, in place.

    :param data: the parsed JSON object; mutated to the current layout.
    """
    RehuMigrator(data).migrate()


class RehuMigrator:  # pylint: disable=too-few-public-methods
    """Applies every layout migration a parsed ``.rehu`` payload still needs
    ([[data-model#schema-version]]).

    One public method is the intended shape, not an accident: :meth:`migrate` is the whole contract, and
    the steps behind it are private because *which* of them a payload needs is this class's judgement,
    not a caller's. The class exists to give those steps somewhere to live -- they share ``__data`` and
    must not be module-level privates -- rather than to offer an API.

    Steps run **oldest first**, each named for the transition it performs and leaving the payload one
    version newer -- add the next one to :meth:`migrate` in order, rather than teaching an existing step
    about a second shape.

    :param data: the parsed JSON object; mutated in place.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self.__data: Final = data

    def migrate(self) -> None:
        """Upgrade the payload to :data:`CURRENT_FORMAT_VERSION`, running each step it still needs.

        The only thing a caller ever invokes here -- and in practice not even that, since
        `RehuDocument` migrates whatever it is handed ([[data-model#schema-version]]). The steps are
        deliberately not part of this class's surface: which of them a payload needs is this method's
        judgement, made from :meth:`__resolved_version`, and never a caller's to second-guess.

        **Leaves the payload wholly consistent -- layout *and* stamp.** Restamping is not `save`'s job to
        finish later: ``data`` is public and is the document's source of truth, so a payload whose layout
        and stamp disagree is simply wrong, and wrong in a way that escapes the moment anything
        serializes it without going through `RehuDocument.save` (a node reply, an export, a test). It
        also means the version the stamp reports is always the version the payload actually has, so
        re-running this is a no-op rather than a second migration.

        **Chaining:** one ``if`` per step, in version order; add the next as::

            if version < 3:
                self.__v2_to_v3()
                version = 3

        ``version`` tracks what the payload *is* as the steps advance it, which is what
        :meth:`__stamp` then records -- so advancing it is load-bearing, not bookkeeping. A payload
        several versions old satisfies every remaining guard and walks them all in order, because each
        guard tests against that step's **target** rather than a running cursor.

        A step could instead *return* its new version (``version = self.__v1_to_v2()``), which reads more
        neatly but hides the target behind the call: a step returning the wrong number would leave the
        dispatch here looking correct. Keeping the target next to its guard makes a mismatch visible on
        adjacent lines. Should this grow to several steps, the shape that removes the repetition
        altogether is a table of ``(target, step)`` pairs, where ``version = target`` is derived rather
        than typed.
        """
        version = self.__resolved_version()
        if version < 2:
            self.__v1_to_v2()
            version = 2
        self.__data[FORMAT_VERSION_KEY] = version

    def __resolved_version(self) -> int:
        """Resolve which **layout** this payload has ([[data-model#schema-version]]).

        Deliberately not the same question as `RehuDocument.format_version`, which reports what the
        payload *claims*, verbatim. This one answers what it *is*, so it never returns ``0``: v0 means
        "unstamped", which names no layout at all, and a payload always has some layout.

        The stamp is authoritative whenever it holds a usable ``int``. A missing or malformed one is v0 --
        malformed is not trusted: a `.rehu` is untrusted input, and a malformed value of a field this
        build owns reads as its default rather than being believed ([[data-model#write-integrity]]) --
        the same rule `RehuDocument.format_version` follows.

        **An unstamped payload is the flat v1 layout, and that is a deduction rather than a guess.**
        Saving has stamped since v1 -- there has never been a build that wrote a `.rehu` without a
        version -- so a payload with no stamp predates stamping, and therefore predates every layout
        after the first.

        The payload's *shape* is deliberately not consulted, and in particular a ``core`` block is **not**
        read as evidence of v2. The two facts contradict each other: ``core`` arrived with v2, and every
        v2 build stamps, so a payload carrying one without a stamp is not a v2 document -- it is a broken
        one, and no build produced it. Treating it as v2 would launder that. It costs nothing to say so
        either: :meth:`__v1_to_v2` declines a payload that already has a ``core`` block, so a
        contradictory payload is carried verbatim rather than mangled by a step that does not fit it.

        :returns: the layout's version -- never ``0``, since that is the absence of a stamp rather than a
            layout to upgrade from.
        """
        stamp = stamped_version(self.__data)
        return stamp if stamp is not None else 1

    def __v1_to_v2(self) -> None:
        """**v1 -> v2**: move the top-level common fields into the ``core`` block
        ([[data-model#rehu-format]]).

        **The v1 recognition rule is applied once, here, and then never again.** In v1 a plugin block was
        "a top-level object-valued key that isn't a known common field", so the two are separated using
        exactly that rule: a key in :data:`V1_COMMON_FIELD_KEYS` moves into ``core``, and everything else
        stays at the top level as a block. That rule's ambiguity -- an object-valued key v1 didn't know
        was common is indistinguishable from a plugin block -- is inherited only by files that predate
        the fix, which is the best any migration can do, and is why the ambiguity cannot recur in v2.

        **Declines a payload that already has a ``core`` block**, which is a precondition of the
        transformation rather than a version check: this step *creates* ``core``, so it has nothing
        coherent to do with a payload that has one already, and doing it anyway loses data -- the
        rebuild below would drop a v1-named top-level block on the floor, since the ``core`` key it
        would be folded into is already taken. Such a payload is self-contradictory (``core`` implies
        v2, v2 implies a stamp, a stamp means this step never runs), so it is left exactly as it is:
        carried verbatim, which is what an unrecognized payload is owed.

        A flat payload with nothing to move -- a brand-new, empty document -- simply gains no block.
        """
        if CORE_BLOCK_KEY in self.__data:
            return
        moved = {key: value for key, value in self.__data.items() if key in V1_COMMON_FIELD_KEYS}
        if not moved:
            return
        for key in moved:
            del self.__data[key]
        self.__data[CORE_BLOCK_KEY] = moved
