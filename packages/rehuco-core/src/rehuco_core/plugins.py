"""Plugin identity: what a plugin *is*, and how this build knows one exists ([[plugins#core-vs-plugin]]).

A plugin is identified by a **declared key list**, not by a name transformed at runtime: the first entry
is the **main key** and every later entry is an **alias** the reader accepts and the writer normalizes
away ([[plugins#plugin-blocks]]). This is the non-GUI half of a plugin -- the layer agent and node alike
load -- and for now it holds identity alone; a plugin's block schema, hooks, and rendering are added to
this layer as later slices need them.

A resource ``type``'s value **is** its active block's key ([[plugins#plugin-blocks]]), so one key list
serves both: it resolves a legacy ``type`` spelling and the legacy block key it named, because they are
the same token. That identity is what lets `RehuDocument` classify a block active-or-inactive with no registry
at all once a document is normalized -- including for a type whose plugin nobody here has installed.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class PluginSpec:
    """One plugin's identity -- its declared key list ([[plugins#core-vs-plugin]]).

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


CORE_PLUGIN: Final = PluginSpec(("core",))
"""The common core's own identity ([[data-model#rehu-format]]).

The core's fields live in a block like any plugin's, which is what lets a ``.rehu`` be read as nothing
but ``format_version`` plus a map of keyed blocks -- so enumerating plugin blocks is "every block that
isn't this one", with no list of common field names to keep in step.

Declaring it here **reserves the name**: :class:`PluginRegistry` already refuses two declarations
claiming one spelling, so a plugin that tries to call itself ``core`` fails when the registry is built,
with no rule of its own.

Reserved, not a candidate: no document is ever ``type: "core"``, so unlike every other block the core is
never active or inactive ([[plugins#plugin-blocks]]) -- it is simply always there."""

CORE_BLOCK_KEY: Final = CORE_PLUGIN.key
"""The common core's block key ([[data-model#rehu-format]]); spelled once, here."""

TUTORIAL_PLUGIN: Final = PluginSpec(("tutorial", "Tutorial"))
"""The tutorial plugin ([[plugins#tutorial-plugin]]); ``Tutorial`` is tc4's capitalized spelling
([[acquisition-tooling#tc-to-rehu]]), carried as an alias."""

REFERENCE_IMAGES_PLUGIN: Final = PluginSpec(("reference_images", "ReferenceImages", "refimages"))
"""The reference-images plugin ([[plugins#refimages-plugin]]); ``ReferenceImages`` is tc4's spelling and
``refimages`` an earlier shorthand this document's own examples once used -- both aliases now."""

COLLECTION_PLUGIN: Final = PluginSpec(("collection", "Collection"))
"""The collection type ([[field-schema#resource-types]]). Declared for its identity alone: a Collection
carries none of the resource fields, so its block is normally absent -- but its ``type`` still normalizes
like any other, and a file that does carry a ``collection:`` block round-trips as a block rather than as
a stray unknown key."""

BUILTIN_PLUGINS: Final = (CORE_PLUGIN, TUTORIAL_PLUGIN, REFERENCE_IMAGES_PLUGIN, COLLECTION_PLUGIN)
"""The declarations this build ships -- :data:`CORE_PLUGIN` plus the real plugins.

Deliberately **not** every key the specs name: ``daz3d`` ([[plugins#daz3d-plugin]]) is parked past
milestone C and has no declaration here, so a ``daz3d:`` block exercises the not-installed path for real
rather than hypothetically."""


class PluginRegistry:
    """The set of plugins this build knows about -- an immutable index over declared key lists
    ([[plugins#core-vs-plugin]]).

    Answers only *identity* questions ("is this key a plugin I have, and what is its main spelling"),
    never active-or-inactive ones: which block is active follows from the document's ``type``, not from what is
    installed ([[plugins#plugin-blocks]]). Immutable by construction, so "installed here" is a value a
    caller passes rather than global state a caller mutates.

    :param specs: the plugin declarations to index.
    :raises ValueError: if two declarations claim the same key or alias.
    """

    def __init__(self, specs: Iterable[PluginSpec] = ()) -> None:
        self.__specs: Final = tuple(specs)
        index: dict[str, PluginSpec] = {}
        for spec in self.__specs:
            for name in spec.keys:
                if name in index:
                    raise ValueError(f"key {name!r} is claimed by two plugins")
                index[name] = spec
        self.__index: Final = index

    def __iter__(self) -> Iterator[PluginSpec]:
        return iter(self.__specs)

    def __contains__(self, name: object) -> bool:
        return name in self.__index

    def resolve(self, name: str) -> PluginSpec | None:
        """Find the plugin a key or alias names.

        :param name: a main key or an alias, as spelled on disk.
        :returns: the plugin, or ``None`` when no installed plugin claims ``name``.
        """
        return self.__index.get(name)

    def main_key(self, name: str) -> str:
        """Normalize a key or alias to its plugin's main spelling.

        An unclaimed ``name`` is returned **verbatim**, which is the whole point: a type whose plugin
        isn't installed here still has a well-defined block key ([[plugins#plugin-blocks]]), so
        active/inactive classification never depends on installed-ness.

        :param name: a main key or an alias, as spelled on disk.
        :returns: the plugin's main key, or ``name`` itself when unclaimed.
        """
        spec = self.__index.get(name)
        return spec.key if spec is not None else name


DEFAULT_PLUGIN_REGISTRY: Final = PluginRegistry(BUILTIN_PLUGINS)
"""The registry `RehuDocument` uses when a caller passes none -- this build's shipped plugins."""
