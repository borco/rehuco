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

    :param keys: the main key first, then any aliases. Must be non-empty.
    :raises ValueError: if ``keys`` is empty or holds a duplicate.
    """

    keys: tuple[str, ...]

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
