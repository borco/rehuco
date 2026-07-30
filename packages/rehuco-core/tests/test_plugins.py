"""Tests for plugin identity and block schema: declared key lists, declared field names, and the registry
that indexes them."""

import pytest
from rehuco_core import (
    BUILTIN_PLUGINS,
    COLLECTION_PLUGIN,
    CORE_FIELD_NAMES,
    CORE_PLUGIN,
    DEFAULT_PLUGIN_REGISTRY,
    REFERENCE_IMAGES_FIELD_NAMES,
    REFERENCE_IMAGES_PLUGIN,
    RESOURCE_FIELD_NAMES,
    TUTORIAL_FIELD_NAMES,
    TUTORIAL_PLUGIN,
    PluginRegistry,
    PluginSpec,
)


def test_the_first_declared_key_is_the_main_one_and_the_rest_are_aliases() -> None:
    """A plugin declares its keys rather than deriving them; the first is main, the rest alias it
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a spec with a main key and two aliases
    * verify ``key`` is the first and ``aliases`` is the remainder
    """
    spec = PluginSpec(("daz3d", "Daz3D", "daz"))
    assert spec.key == "daz3d"
    assert spec.aliases == ("Daz3D", "daz")


def test_a_single_key_plugin_has_no_aliases() -> None:
    """A plugin needs only a main key; aliases are optional.

    **Test steps:**

    * construct a spec with one key
    * verify it is the main key and there are no aliases
    """
    spec = PluginSpec(("audiopack",))
    assert spec.key == "audiopack"
    assert spec.aliases == ()


def test_a_plugin_must_declare_at_least_one_key() -> None:
    """An identity-less plugin is rejected at construction rather than yielding an empty block key.

    **Test steps:**

    * construct a spec with no keys
    * verify it raises
    """
    with pytest.raises(ValueError, match="at least one key"):
        PluginSpec(())


def test_a_plugin_may_not_declare_an_empty_key() -> None:
    """A ``""`` key -- main or alias -- is rejected at construction: an empty ``type`` means *typeless*,
    a document with no active block at all (#166), so no plugin can claim that spelling.

    Left declarable, a ``""``-keyed plugin would make ``resolve("")`` succeed and re-open the read paths
    the empty-active-key guards close -- migrating a typeless document's ``""`` payload as though it were
    the plugin's own block.

    **Test steps:**

    * construct a spec whose main key is empty, and one hiding ``""`` among its aliases
    * verify both raise
    """
    with pytest.raises(ValueError, match="empty key"):
        PluginSpec(("",))
    with pytest.raises(ValueError, match="empty key"):
        PluginSpec(("tutorial", ""))


def test_a_plugin_may_not_declare_the_same_key_twice() -> None:
    """A duplicate inside one declaration is a typo, not an alias.

    **Test steps:**

    * construct a spec repeating a key
    * verify it raises
    """
    with pytest.raises(ValueError, match="duplicate key"):
        PluginSpec(("tutorial", "tutorial"))


def test_a_plugin_declares_no_field_names_by_default() -> None:
    """Declaring fields is optional: a plugin that names none declares none
    ([[field-schema#resource-types]], #195).

    Identity comes first -- a type is declarable before its field set is decided, which is exactly
    `~rehuco_core.COLLECTION_PLUGIN`'s position ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a spec declaring only keys
    * verify its field names are empty
    """
    assert not PluginSpec(("audiopack",)).field_names


def test_a_plugin_may_not_declare_an_empty_or_repeated_field_name() -> None:
    """A field-name list gets the same two checks the key list gets: a blank name names nothing and a
    repeat says nothing the first did not (#195).

    **Test steps:**

    * construct a spec whose declaration hides a ``""`` among its field names
    * construct one repeating a field name
    * verify both raise
    """
    with pytest.raises(ValueError, match="empty field name"):
        PluginSpec(("tutorial",), field_names=("level", ""))
    with pytest.raises(ValueError, match="duplicate field name"):
        PluginSpec(("tutorial",), field_names=("level", "level"))


def test_the_builtin_declarations_carry_the_specs_field_tiers() -> None:
    """Each shipped plugin declares the tier the field schema assigns it
    ([[field-schema#resource-types]], #195).

    The decision this records: a type's field list is authored in its **plugin declaration**, beside the
    identity it belongs to, rather than in whichever surface renders it -- schema extension is
    plugin-owned ([[plugins#core-vs-plugin]]). The tiers themselves are only how the declarations are
    composed: Tutorial and ReferenceImages share the resource fields by both naming them, so one
    dropping a field is not a change to the other's schema.

    **Test steps:**

    * verify Tutorial declares the shared resource fields plus the durations and ``level``
    * verify ReferenceImages declares the shared resource fields plus its count pair and no duration
    * verify Collection declares nothing, and the core declares the common tier
    """
    assert TUTORIAL_PLUGIN.field_names == (*RESOURCE_FIELD_NAMES, *TUTORIAL_FIELD_NAMES)
    assert REFERENCE_IMAGES_PLUGIN.field_names == (*RESOURCE_FIELD_NAMES, *REFERENCE_IMAGES_FIELD_NAMES)
    assert not [name for name in TUTORIAL_PLUGIN.field_names if name.endswith("_count")]
    assert not [name for name in REFERENCE_IMAGES_PLUGIN.field_names if name.endswith("_duration")]
    assert "level" not in REFERENCE_IMAGES_PLUGIN.field_names

    assert not COLLECTION_PLUGIN.field_names
    assert CORE_PLUGIN.field_names == CORE_FIELD_NAMES


def test_field_names_resolves_a_types_declaration_and_is_empty_for_an_unclaimed_one() -> None:
    """The registry answers "which fields does this type declare" for any spelling, and answers
    **nothing** for a type whose plugin isn't installed here (#195).

    The empty answer is the load-bearing one: it is what makes a not-installed type compose the common
    core alone while every key in its block reaches the agent's generic fallback
    ([[plugins#fallback-editor]]) rather than being silently unrendered.

    **Test steps:**

    * verify a main key and an alias both resolve to the plugin's declared fields
    * verify an unclaimed name resolves to an empty tuple
    """
    registry = PluginRegistry([TUTORIAL_PLUGIN, REFERENCE_IMAGES_PLUGIN])

    assert registry.field_names("tutorial") == TUTORIAL_PLUGIN.field_names
    assert registry.field_names("Tutorial") == TUTORIAL_PLUGIN.field_names
    assert registry.field_names("refimages") == REFERENCE_IMAGES_PLUGIN.field_names
    assert registry.field_names("daz3d") == ()
    assert registry.field_names("") == ()


def test_resolve_finds_a_plugin_by_its_main_key_or_any_alias() -> None:
    """The registry indexes every declared spelling ([[plugins#core-vs-plugin]]).

    **Test steps:**

    * verify the main key resolves to the plugin
    * verify each alias resolves to the same plugin
    * verify an unclaimed name resolves to nothing
    """
    registry = PluginRegistry([REFERENCE_IMAGES_PLUGIN])
    assert registry.resolve("reference_images") is REFERENCE_IMAGES_PLUGIN
    assert registry.resolve("ReferenceImages") is REFERENCE_IMAGES_PLUGIN
    assert registry.resolve("refimages") is REFERENCE_IMAGES_PLUGIN
    assert registry.resolve("audiopack") is None


def test_main_key_normalizes_an_alias_and_passes_an_unclaimed_name_through() -> None:
    """Normalization folds aliases onto the main key, and leaves an uninstalled plugin's key **verbatim**
    ([[plugins#plugin-blocks]]).

    Passing an unclaimed name through unchanged is the point: it is what gives a type whose plugin isn't
    installed here a well-defined block key, so classification never depends on installed-ness.

    **Test steps:**

    * verify an alias normalizes to the main key
    * verify the main key is already normal
    * verify an unclaimed name is returned unchanged
    """
    registry = PluginRegistry([REFERENCE_IMAGES_PLUGIN])
    assert registry.main_key("refimages") == "reference_images"
    assert registry.main_key("reference_images") == "reference_images"
    assert registry.main_key("audiopack") == "audiopack"


def test_main_keys_lists_each_plugins_main_spelling_in_declaration_order() -> None:
    """``main_keys`` reports every plugin's main key, aliases omitted, in declaration order
    ([[plugins#plugin-blocks]]).

    The identity half of a type selector's offer list: aliases are left out because they normalize to
    the main key on write, so a selector offers only the spelling a switch would store; declaration
    order is kept so the offer list is stable and predictable.

    **Test steps:**

    * build a registry over two plugins, one with aliases
    * verify only the main keys are reported, in the order the plugins were declared
    """
    registry = PluginRegistry([TUTORIAL_PLUGIN, REFERENCE_IMAGES_PLUGIN])

    assert registry.main_keys == ("tutorial", "reference_images")


def test_main_keys_is_empty_for_an_empty_registry() -> None:
    """An empty registry offers no main keys ([[plugins#plugin-blocks]]).

    **Test steps:**

    * verify a registry declaring no plugins reports an empty ``main_keys``
    """
    assert not PluginRegistry().main_keys


def test_a_plugin_declares_optional_badge_colors_defaulting_to_none() -> None:
    """A plugin may declare its own badge background and text colors, each defaulting to ``None`` --
    "use the theme's selection color" ([[plugins#plugin-blocks]], #83).

    The colors travel with the declaration, so a plugin from any source owns how its badge looks; an
    undeclared color leaves the badge to the theme.

    **Test steps:**

    * verify a plugin declaring colors carries them
    * verify a plugin declaring none reports ``None`` for both
    """
    spec = PluginSpec(("tutorial",), color="#1E88E5", text_color="#FFFFFF")
    assert (spec.color, spec.text_color) == ("#1E88E5", "#FFFFFF")

    bare = PluginSpec(("tutorial",))
    assert (bare.color, bare.text_color) == (None, None)


def test_registry_colors_resolve_a_plugins_colors_and_none_for_an_unclaimed_type() -> None:
    """``color``/``text_color`` return the plugin's declared colors for an installed type (main key or
    alias) and ``None`` for an uninstalled one ([[plugins#plugin-blocks]], #83).

    The same installed-independence :meth:`main_key` keeps: a not-installed type still resolves to a
    well-defined answer (here ``None`` -- fall back to the theme's selection color).

    **Test steps:**

    * build a registry over a plugin declaring a background but no text color, with an alias
    * verify its main key and alias both resolve to the declared background and a ``None`` text
    * verify an unclaimed type resolves to ``None`` for both
    """
    registry = PluginRegistry([PluginSpec(("reference_images", "ReferenceImages"), color="#8E24AA")])

    assert registry.color("reference_images") == "#8E24AA"
    assert registry.color("ReferenceImages") == "#8E24AA"
    assert registry.text_color("reference_images") is None
    assert registry.color("audiopack") is None
    assert registry.text_color("audiopack") is None


def test_two_plugins_may_not_claim_the_same_spelling() -> None:
    """A key collision between plugins is ambiguous, so the registry refuses to be built.

    **Test steps:**

    * declare a second plugin whose alias is another's main key
    * verify constructing a registry over both raises
    """
    impostor = PluginSpec(("audiopack", "tutorial"))
    with pytest.raises(ValueError, match="claimed by two plugins"):
        PluginRegistry([PluginSpec(("tutorial",)), impostor])


def test_the_default_registry_ships_the_builtin_plugins() -> None:
    """The default registry is this build's shipped set ([[plugins#core-vs-plugin]]).

    ``core`` is deliberately absent too, alongside ``daz3d`` -- it is future work, so it
    exercises the not-installed path for real, while ``core`` is never registered at all
    (:data:`~rehuco_core.plugins.RESERVED_KEYS` protects it unconditionally instead).

    **Test steps:**

    * verify the default registry holds exactly the builtins
    * verify the shipped keys are claimed, and neither ``core`` nor ``daz3d`` is
    """
    assert tuple(DEFAULT_PLUGIN_REGISTRY) == BUILTIN_PLUGINS
    assert [spec.key for spec in DEFAULT_PLUGIN_REGISTRY] == ["tutorial", "reference_images", "collection"]
    assert "core" not in DEFAULT_PLUGIN_REGISTRY
    assert "daz3d" not in DEFAULT_PLUGIN_REGISTRY


def test_no_plugin_can_claim_the_core_block_key() -> None:
    """``core`` is reserved **unconditionally** ([[data-model#rehu-format]]) -- not because
    :data:`~rehuco_core.CORE_PLUGIN` happens to occupy a registry slot (it never does; see
    :data:`BUILTIN_PLUGINS`), but because :data:`~rehuco_core.plugins.RESERVED_KEYS` forbids any spec
    from declaring it. This is the case that used to pass for the wrong (contingent) reason: a registry
    that omits ``CORE_PLUGIN`` entirely still refuses an impostor.

    **Test steps:**

    * declare a plugin whose main key is ``core``, and one that merely aliases it
    * verify building a registry with either alongside the builtins (which do **not** include
      ``CORE_PLUGIN``) raises
    * verify registering ``CORE_PLUGIN`` itself raises too -- its job is purely descriptive now
    """
    for impostor in (PluginSpec(("core",)), PluginSpec(("impostor", "core"))):
        with pytest.raises(ValueError, match="reserved"):
            PluginRegistry([*BUILTIN_PLUGINS, impostor])
    with pytest.raises(ValueError, match="reserved"):
        PluginRegistry([CORE_PLUGIN])


def test_no_plugin_can_claim_the_format_version_key() -> None:
    """``format_version`` is reserved too ([[data-model#rehu-format]]) -- previously unprotected: a
    plugin declaring it succeeded before this check existed, since it is not a plugin and nothing
    refused a claimant.

    **Test steps:**

    * declare a plugin whose main key is ``format_version``
    * verify building a registry with it alongside the builtins raises
    """
    with pytest.raises(ValueError, match="reserved"):
        PluginRegistry([*BUILTIN_PLUGINS, PluginSpec(("format_version",))])
