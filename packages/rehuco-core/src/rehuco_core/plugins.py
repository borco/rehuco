"""Plugin identity: what a plugin *is*, and how this build knows one exists ([[plugins#core-vs-plugin]]).

A plugin is identified by a **declared key list**, not by a name transformed at runtime: the first entry
is the **main key** and every later entry is an **alias** the reader accepts and the writer normalizes
away ([[plugins#plugin-blocks]]). This is the non-GUI half of a plugin -- the layer agent and node alike
load -- and for now it holds identity plus its own block's format version ([[plugins#plugin-blocks]]); a plugin's
block *schema*, hooks, and rendering are added to
this layer as later slices need them.

A resource ``type``'s value **is** its active block's key ([[plugins#plugin-blocks]]), so one key list
serves both: it resolves a legacy ``type`` spelling and the legacy block key it named, because they are
the same token. That identity is what lets `RehuDocument` classify a block active-or-inactive with no registry
at all once a document is normalized -- including for a type whose plugin nobody here has installed.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final


@dataclass(frozen=True)
class PluginSpec:
    """One plugin's identity -- its declared key list -- plus the version of its own block layout this
    build understands ([[plugins#core-vs-plugin]], [[plugins#plugin-blocks]]).

    :param keys: the main key first, then any aliases. Must be non-empty.
    :param current_block_version: the block ``format_version`` this plugin's declared
        :attr:`block_migrations` bring a block up to. ``0`` (the default) means this plugin has not
        defined a versioned block layout yet -- its fields simply live in the block, unowned by any
        schema ([[field-schema#per-user-shared]]): unlike the file-wide v0, this is not a gap predating
        versioning, it is a real, currently-current layout for a plugin that has never needed a second one.
    :param block_migrations: ``(target, step)`` pairs bringing a block from below ``target`` up to it, each
        ``step`` mutating the block's own fields in place -- the per-plugin dispatch table
        :func:`~rehuco_core.migrations.migrate_block_data` walks ([[data-model#schema-version]]'s
        dispatch rule, applied per block). Empty by default: a plugin at ``current_block_version == 0``
        needs none.
    :raises ValueError: if ``keys`` is empty or holds a duplicate, two migrations target the same
        version, or a migration targets a version past ``current_block_version``.
    """

    keys: tuple[str, ...]
    current_block_version: int = 0
    block_migrations: tuple[tuple[int, Callable[[dict[str, Any]], None]], ...] = ()

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("a plugin must declare at least one key")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError(f"duplicate key in plugin declaration: {self.keys}")
        targets = [target for target, _ in self.block_migrations]
        if len(set(targets)) != len(targets):
            raise ValueError(f"duplicate block migration target in plugin declaration: {self.keys}")
        if any(target > self.current_block_version for target in targets):
            raise ValueError(
                f"block migration target above current_block_version {self.current_block_version} "
                f"in plugin declaration: {self.keys}"
            )

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


FORMAT_VERSION_KEY: Final = "format_version"
"""The file-wide schema-version key ([[data-model#schema-version]]); the one reserved key that
describes the file's own layout rather than holding fields."""

CORE_PLUGIN: Final = PluginSpec(("core",))
"""The common core's own identity ([[data-model#rehu-format]]) -- descriptive only, **never registered**.

The core's fields live in a block like any plugin's, which is what lets a ``.rehu`` be read as nothing
but ``format_version`` plus a map of keyed blocks -- so enumerating plugin blocks is "every block that
isn't this one", with no list of common field names to keep in step.

Its name is reserved by :data:`RESERVED_KEYS`, unconditionally -- not by occupying a slot in
:data:`DEFAULT_PLUGIN_REGISTRY`, which :class:`PluginRegistry` now refuses to build for *any* spec
declaring a reserved key, this one included. So this constant's job is purely to describe the core
block -- :data:`CORE_BLOCK_KEY` reads its spelling from here -- not to defend its name.

Reserved, not a candidate: no document is ever ``type: "core"``, so unlike every other block the core is
never active or inactive ([[plugins#plugin-blocks]]) -- it is simply always there."""

CORE_BLOCK_KEY: Final = CORE_PLUGIN.key
"""The common core's block key ([[data-model#rehu-format]]); spelled once, here."""

RESERVED_KEYS: Final = frozenset({FORMAT_VERSION_KEY, CORE_BLOCK_KEY})
"""The two top-level ``.rehu`` keys that are not plugin blocks ([[data-model#rehu-format]]): the file's
own version stamp, and the common core's block. The single source of truth :class:`PluginRegistry` (no
plugin may declare one) and ``RehuDocument`` (no document may misuse one as a block) both check against
-- previously two separate facts that happened to agree, which is how ``core`` came to be protected only
contingently on :data:`CORE_PLUGIN` being present in a given registry's specs."""

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

BUILTIN_PLUGINS: Final = (TUTORIAL_PLUGIN, REFERENCE_IMAGES_PLUGIN, COLLECTION_PLUGIN)
"""The declarations this build ships. Deliberately **excludes** :data:`CORE_PLUGIN`: the core block is
protected by :data:`RESERVED_KEYS` unconditionally now, not by occupying a registry slot -- registering
it would fail the very check that protects it.

Also deliberately **not** every key the specs name: ``daz3d`` ([[plugins#daz3d-plugin]]) is parked past
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
    :raises ValueError: if a declaration claims a key in :data:`RESERVED_KEYS`, or two declarations claim
        the same key or alias.
    """

    def __init__(self, specs: Iterable[PluginSpec] = ()) -> None:
        self.__specs: Final = tuple(specs)
        index: dict[str, PluginSpec] = {}
        for spec in self.__specs:
            for name in spec.keys:
                if name in RESERVED_KEYS:
                    raise ValueError(f"key {name!r} is reserved and cannot be declared by a plugin")
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
