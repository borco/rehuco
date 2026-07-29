"""One plugin's identity and block schema -- its declared key list and the field names its block carries
([[plugins#core-vs-plugin]], [[plugins#plugin-blocks]], [[field-schema#resource-types]]).

A plugin is identified by a **declared key list**, not by a name transformed at runtime: the first entry
is the **main key** and every later entry is an **alias** the reader accepts and the writer normalizes
away ([[plugins#plugin-blocks]]). A resource ``type``'s value **is** its active block's key, so one key
list serves both -- it resolves a legacy ``type`` spelling and the legacy block key it named, because they
are the same token.

**The present tense only.** A plugin describes *what it is now*, never how its block was laid out in an
older build. That history -- the per-block ``format_version`` chain and the steps that climb it -- lives
entirely in :mod:`rehuco_core.migrations`, keyed by this identity's main key. The migration layer knows
about plugins; a plugin knows nothing about migrations ([[plugins#plugin-blocks]]).

**Schema extension is plugin-owned** ([[plugins#core-vs-plugin]]'s table), so a type's field list is
declared *here*, beside the identity it belongs to, rather than in whichever surface renders it (#195).
Names only, no widget types: a node reads the same declaration to know a block's shape, and mapping a
name to a toolkit widget is the agent's job ([[plugins#field-toolkit]]) -- the same split the badge
colors already take, where core carries plain strings and only the agent turns them into Qt.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginSpec:
    """One plugin's identity and block schema -- its declared key list and the field names its block
    carries ([[plugins#core-vs-plugin]], [[plugins#plugin-blocks]]).

    A plugin may also **declare its own badge colors** ([[plugins#plugin-blocks]], #83): plain hex strings
    (no Qt), so they stay core/non-GUI and travel with the declaration from whatever source provides the
    plugin -- built-in today, an external plugin package later. The agent's type badge
    (:class:`~rehuco_agent.fields.widgets.type_badge.TypeBadge`) paints with them; a node ignores them.
    Kept here rather than derived in the agent so a plugin owns how it presents, wherever it comes from.
    Either color is **optional**: an undeclared background falls back to the theme's selection background
    and an undeclared text to the theme's selection text (the badge resolves ``None`` against the live
    palette), so a plugin that declares nothing still gets a sensible, theme-consistent badge.

    A plugin also **declares the field names its block carries** (#195). This is the schema half of the
    declaration: which fields belong to this type, so a Tutorial does not show a ReferenceImages field
    and the other way round ([[field-schema#resource-types]]'s tiers). It is a **set**, not a layout --
    where a type's *ordered* field list is authored stays open ([[appendices.open-questions#still-open]]),
    and the tuple's order carries no meaning today. A field name absent from every declaration is not
    refused anywhere: an unclaimed key in a block is payload the reader carries verbatim and the agent
    surfaces through its generic fallback ([[plugins#fallback-editor]]), which is also what a type whose
    plugin is not installed here falls back to -- it declares nothing, so it recognizes nothing.

    :param keys: the main key first, then any aliases. Must be non-empty.
    :param field_names: the field names this plugin's block declares; empty when the type carries no
        fields of its own (a Collection, [[field-schema#resource-types]]).
    :param color: the plugin's fixed badge background color (a hex string), or ``None`` to use the
        theme's selection background.
    :param text_color: the plugin's fixed badge text color (a hex string), or ``None`` to use the
        theme's selection text color.
    :raises ValueError: if ``keys`` is empty, holds a duplicate, or holds an empty string -- an empty
        ``type`` means *typeless*, a document with no active block at all (#166), so ``""`` is not a
        spelling any plugin can claim; or if ``field_names`` holds a duplicate or an empty string.
    """

    keys: tuple[str, ...]
    color: str | None = None
    text_color: str | None = None
    field_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("a plugin must declare at least one key")
        if not all(self.keys):
            raise ValueError(f"empty key in plugin declaration: {self.keys}")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError(f"duplicate key in plugin declaration: {self.keys}")
        # the same two checks the key list gets: a declaration is a set of names, so a blank one names
        # nothing and a repeat says nothing the first said not
        if not all(self.field_names):
            raise ValueError(f"empty field name in plugin declaration: {self.field_names}")
        if len(set(self.field_names)) != len(self.field_names):
            raise ValueError(f"duplicate field name in plugin declaration: {self.field_names}")

    @property
    def key(self) -> str:
        """The **main** key: the block key this plugin's fields are stored under, and the normalized
        spelling of the ``type`` that names it ([[plugins#plugin-blocks]])."""
        return self.keys[0]

    @property
    def aliases(self) -> tuple[str, ...]:
        """The accepted-on-read, rewritten-on-write spellings of :attr:`key` -- a rename/migration path
        for free ([[plugins#plugin-blocks]])."""
        return self.keys[1:]
