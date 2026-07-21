"""One plugin's identity -- its declared key list ([[plugins#core-vs-plugin]], [[plugins#plugin-blocks]]).

A plugin is identified by a **declared key list**, not by a name transformed at runtime: the first entry
is the **main key** and every later entry is an **alias** the reader accepts and the writer normalizes
away ([[plugins#plugin-blocks]]). A resource ``type``'s value **is** its active block's key, so one key
list serves both -- it resolves a legacy ``type`` spelling and the legacy block key it named, because they
are the same token.

**Identity only.** A plugin describes *what it is now*, never how its block was laid out in an older
build. That history -- the per-block ``format_version`` chain and the steps that climb it -- lives
entirely in :mod:`rehuco_core.migrations`, keyed by this identity's main key. The migration layer knows
about plugins; a plugin knows nothing about migrations ([[plugins#plugin-blocks]]).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginSpec:
    """One plugin's identity -- its declared key list ([[plugins#core-vs-plugin]], [[plugins#plugin-blocks]]).

    A plugin may also **declare its own badge colors** ([[plugins#plugin-blocks]], #83): plain hex strings
    (no Qt), so they stay core/non-GUI and travel with the declaration from whatever source provides the
    plugin -- built-in today, an external plugin package later. The agent's type badge
    (:class:`~rehuco_agent.fields.widgets.type_badge.TypeBadge`) paints with them; a node ignores them.
    Kept here rather than derived in the agent so a plugin owns how it presents, wherever it comes from.
    Either color is **optional**: an undeclared background falls back to the theme's selection background
    and an undeclared text to the theme's selection text (the badge resolves ``None`` against the live
    palette), so a plugin that declares nothing still gets a sensible, theme-consistent badge.

    :param keys: the main key first, then any aliases. Must be non-empty.
    :param color: the plugin's fixed badge background color (a hex string), or ``None`` to use the
        theme's selection background.
    :param text_color: the plugin's fixed badge text color (a hex string), or ``None`` to use the
        theme's selection text color.
    :raises ValueError: if ``keys`` is empty or holds a duplicate.
    """

    keys: tuple[str, ...]
    color: str | None = None
    text_color: str | None = None

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("a plugin must declare at least one key")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError(f"duplicate key in plugin declaration: {self.keys}")

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
