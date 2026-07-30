"""The plugins this build ships, and the immutable index over them ([[plugins#core-vs-plugin]])."""

from collections.abc import Iterable, Iterator
from typing import Final

from ..rehu_format import CORE_BLOCK_KEY, RESERVED_KEYS
from .plugin_spec import PluginSpec

CORE_FIELD_NAMES: Final = (
    "title",
    "publisher",
    "url",
    "authors",
    "released",
    "description",
    "hidden_images",
    "advertised_tags",
    "extra_tags",
    "created",
    "updated",
    "original_size",
    "current_size",
)
"""The **common core** tier ([[field-schema#resource-types]]): the fields every resource type has, whatever
its plugin. Declared by :data:`CORE_PLUGIN`, so a surface composing a type's fields asks the core
declaration and the type's own, and gets the union (#195).

``title``/``publisher``/``url`` are the **primary source's** ([[field-schema#sources]]), which the core
block stores under one ``sources`` list rather than three keys -- these name the *fields* a form composes
and a browser column reads, which is not always the key a block stores them under
(:attr:`~rehuco_core.PluginSpec.field_names`)."""

RESOURCE_FIELD_NAMES: Final = (
    "rating",
    "complete",
    "online",
    "keep",
    "favorite",
    "collections",
    "learning_paths",
)
"""The **resource** tier ([[field-schema#resource-types]]): the fields Tutorial and ReferenceImages share,
spliced into both declarations below. A :data:`COLLECTION_PLUGIN` declares none of them -- a series node
is not something rated, kept, or filed under a learning path.

``complete`` is here rather than with the durations because it means *the item has all its parts* -- every
video of a tutorial, every image of a reference pack ([[field-schema#boolean-flags]]) -- which both types
have. ``viewed``/``todo`` are the ones that don't: see :data:`TUTORIAL_FIELD_NAMES`.

Shared by being named in two declarations, not by a third tier the registry knows about: a tier is an
observation about what the types happen to have in common ([[field-schema#resource-types]] draws it), and
one plugin dropping a field must not be a change to another's schema."""

TUTORIAL_FIELD_NAMES: Final = (
    "viewed",
    "todo",
    "advertised_duration",
    "original_duration",
    "current_duration",
    "level",
)
"""The **Tutorial-only** tier ([[field-schema#resource-types]]): the progress flags, the three durations
([[field-schema#duration-size]]) and the multi-choice ``level``.

``viewed`` and ``todo`` are progress through timed material -- watched it, queued to watch it -- which a
reference-image pack has no notion of; you consult one, you don't get through it. They sat on both types
until #195, and a ``reference_images`` block that still carries them is stripped by that chain's v3 step
(:mod:`~rehuco_core.migrations.reference_images.v3_drop_progress_flags`)."""

REFERENCE_IMAGES_FIELD_NAMES: Final = ("advertised_count", "current_count")
"""The **ReferenceImages-only** tier ([[field-schema#resource-types]]): the image count, as the claimed/
measured pair it splits into (#198) -- what the pack says it holds, and what counting its archives finds
([[data-model#resource-scoping]]). Deliberately **no** duration -- which is the point of declaring per type
at all, since the value that leaked as `720` in tc4 now has nowhere to land.

There is no ``original_count`` third: the durations split three ways because a tutorial shrinks as it is
watched, while a reference pack does not lose images ([[field-schema#duration-size]])."""

CORE_PLUGIN: Final = PluginSpec((CORE_BLOCK_KEY,), field_names=CORE_FIELD_NAMES)
"""The common core's own identity ([[data-model#rehu-format]]) -- descriptive only, **never registered**.

The core's fields live in a block like any plugin's, which is what lets a ``.rehu`` be read as nothing but
``format_version`` plus a map of keyed blocks. Its name is reserved by
:data:`~rehuco_core.RESERVED_KEYS` unconditionally -- not by occupying a slot in
:data:`DEFAULT_PLUGIN_REGISTRY`, which :class:`PluginRegistry` refuses to build for *any* spec declaring a
reserved key, this one included. So this constant's job is purely descriptive; it lives here (not in the
grammar leaf) because it *is* a ``PluginSpec``, and the grammar leaf spells the core key without one to
stay import-cycle-free.

Descriptive is not idle, though: it is where :data:`CORE_FIELD_NAMES` is declared from (#195), which is
what lets "the fields this type shows" be one question -- the core's declaration plus the type's own --
rather than a common list in one layer and a per-type list in another."""

TUTORIAL_PLUGIN: Final = PluginSpec(
    ("tutorial", "Tutorial"),
    color="#1E88E5",
    field_names=(*RESOURCE_FIELD_NAMES, *TUTORIAL_FIELD_NAMES),
)
"""The tutorial plugin ([[plugins#tutorial-plugin]]); ``Tutorial`` is tc4's capitalized spelling
([[acquisition-tooling#tc-to-rehu]]), carried as an alias. Badge color: Blue 600. Declares the shared
resource fields plus its own durations and ``level`` ([[field-schema#resource-types]])."""

REFERENCE_IMAGES_PLUGIN: Final = PluginSpec(
    ("reference_images", "ReferenceImages", "refimages"),
    color="#8E24AA",
    field_names=(*RESOURCE_FIELD_NAMES, *REFERENCE_IMAGES_FIELD_NAMES),
)
"""The reference-images plugin ([[plugins#refimages-plugin]]); ``ReferenceImages`` is tc4's spelling and
``refimages`` an earlier shorthand this document's own examples once used -- both aliases now. Badge
color: Purple 600. Declares the shared resource fields plus the ``advertised_count``/``current_count``
pair, and no duration ([[field-schema#resource-types]])."""

COLLECTION_PLUGIN: Final = PluginSpec(("collection", "Collection"), color="#00897B")
"""The collection type ([[field-schema#resource-types]]). Declared for its identity alone: a Collection
carries none of the resource fields -- it declares **no** field names, so it composes the common core and
nothing else -- and its block is normally absent. Its ``type`` still normalizes like any other, and a file
that does carry a ``collection:`` block round-trips as a block rather than as a stray unknown key. Badge
color: Teal 600. Which fields the type eventually gains is deferred until a real collection is in hand
([[field-schema#deferred-items]]); an empty declaration is the honest statement of that, not a stub."""

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

    def field_names(self, name: str) -> tuple[str, ...]:
        """The field names a type declares ([[field-schema#resource-types]], #195).

        The plugin's own :attr:`PluginSpec.field_names` when ``name`` names an installed plugin (a main key
        or alias), else the **empty tuple** -- a type whose plugin isn't installed here declares nothing,
        so a surface composing its fields composes only the common core and every key in its block reaches
        the generic fallback ([[plugins#fallback-editor]]). That is the same answer an installed plugin
        declaring no fields gives (a Collection), and deliberately so: both mean "this build knows of no
        field of this type", and both leave the block's payload visible rather than silently unrendered.

        :param name: a main key or alias, as spelled on disk.
        :returns: the type's declared field names, or ``()`` when unclaimed.
        """
        spec = self.__index.get(name)
        return spec.field_names if spec is not None else ()

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
