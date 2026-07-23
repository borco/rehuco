"""The plugins this build ships, and the immutable index over them ([[plugins#core-vs-plugin]])."""

from collections.abc import Iterable, Iterator
from typing import Final

from ..rehu_format import CORE_BLOCK_KEY, RESERVED_KEYS
from .plugin_spec import PluginSpec

CORE_PLUGIN: Final = PluginSpec((CORE_BLOCK_KEY,))
"""The common core's own identity ([[data-model#rehu-format]]) -- descriptive only, **never registered**.

The core's fields live in a block like any plugin's, which is what lets a ``.rehu`` be read as nothing but
``format_version`` plus a map of keyed blocks. Its name is reserved by
:data:`~rehuco_core.RESERVED_KEYS` unconditionally -- not by occupying a slot in
:data:`DEFAULT_PLUGIN_REGISTRY`, which :class:`PluginRegistry` refuses to build for *any* spec declaring a
reserved key, this one included. So this constant's job is purely descriptive; it lives here (not in the
grammar leaf) because it *is* a ``PluginSpec``, and the grammar leaf spells the core key without one to
stay import-cycle-free."""

TUTORIAL_PLUGIN: Final = PluginSpec(("tutorial", "Tutorial"), color="#1E88E5")
"""The tutorial plugin ([[plugins#tutorial-plugin]]); ``Tutorial`` is tc4's capitalized spelling
([[acquisition-tooling#tc-to-rehu]]), carried as an alias. Badge color: Blue 600."""

REFERENCE_IMAGES_PLUGIN: Final = PluginSpec(("reference_images", "ReferenceImages", "refimages"), color="#8E24AA")
"""The reference-images plugin ([[plugins#refimages-plugin]]); ``ReferenceImages`` is tc4's spelling and
``refimages`` an earlier shorthand this document's own examples once used -- both aliases now. Badge
color: Purple 600."""

COLLECTION_PLUGIN: Final = PluginSpec(("collection", "Collection"), color="#00897B")
"""The collection type ([[field-schema#resource-types]]). Declared for its identity alone: a Collection
carries none of the resource fields, so its block is normally absent -- but its ``type`` still normalizes
like any other, and a file that does carry a ``collection:`` block round-trips as a block rather than as
a stray unknown key. Badge color: Teal 600."""

BUILTIN_PLUGINS: Final = (TUTORIAL_PLUGIN, REFERENCE_IMAGES_PLUGIN, COLLECTION_PLUGIN)
"""The declarations this build ships. Deliberately **excludes** :data:`~rehuco_core.CORE_PLUGIN`: the core
block is protected by :data:`~rehuco_core.RESERVED_KEYS` unconditionally, not by occupying a registry slot
-- registering it would fail the very check that protects it.

Also deliberately **not** every key the specs name: ``daz3d`` ([[plugins#daz3d-plugin]]) is future work
and has no declaration here, so a ``daz3d:`` block exercises the not-installed path for real
rather than hypothetically."""


class PluginRegistry:
    """The set of plugins this build knows about -- an immutable index over declared key lists
    ([[plugins#core-vs-plugin]]).

    Answers only *identity* questions ("is this key a plugin I have, and what is its main spelling"),
    never active-or-inactive ones: which block is active follows from the document's ``type``, not from
    what is installed ([[plugins#plugin-blocks]]). Immutable by construction, so "installed here" is a
    value a caller passes rather than global state a caller mutates.

    :param specs: the plugin declarations to index.
    :raises ValueError: if a declaration claims a key in :data:`~rehuco_core.RESERVED_KEYS`, or two
        declarations claim the same key or alias.
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

    @property
    def main_keys(self) -> tuple[str, ...]:
        """Every installed plugin's main key ([[plugins#plugin-blocks]]), in declaration order.

        The identity half of "which types can a document be" -- a caller building a type selector pairs
        these with the block keys a specific document already carries (a not-installed type still names a
        block, [[plugins#plugin-blocks]]), so both an installed type and a resurrectable foreign one are
        offerable. Aliases are omitted: they normalize to their main key on write, so a selector offers
        only the spelling the file would actually store.

        :returns: the main keys, in the order the plugins were declared.
        """
        return tuple(spec.key for spec in self.__specs)

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

    def color(self, name: str) -> str | None:
        """The badge **background** color a type declares ([[plugins#plugin-blocks]], #83).

        The plugin's own declared :attr:`PluginSpec.color` when ``name`` names an installed plugin (a main
        key or alias), else ``None`` -- an uninstalled type, like a plugin that declares no background,
        leaves the badge to fall back to the theme's selection background
        (:class:`~rehuco_agent.fields.widgets.type_badge.TypeBadge`). The same installed-independence
        :meth:`main_key` keeps: an uninstalled type still resolves to a well-defined answer.

        :param name: a main key or alias, as spelled on disk.
        :returns: the plugin's declared background color, or ``None`` to use the theme's selection background.
        """
        spec = self.__index.get(name)
        return spec.color if spec is not None else None

    def text_color(self, name: str) -> str | None:
        """The badge **text** color a type declares ([[plugins#plugin-blocks]], #83) -- the text sibling
        of :meth:`color`.

        The plugin's own declared :attr:`PluginSpec.text_color` when ``name`` names an installed plugin,
        else ``None`` -- leaving the badge to fall back to the theme's selection text color.

        :param name: a main key or alias, as spelled on disk.
        :returns: the plugin's declared text color, or ``None`` to use the theme's selection text.
        """
        spec = self.__index.get(name)
        return spec.text_color if spec is not None else None


DEFAULT_PLUGIN_REGISTRY: Final = PluginRegistry(BUILTIN_PLUGINS)
"""The registry `RehuDocument` uses when a caller passes none -- this build's shipped plugins."""
