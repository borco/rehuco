"""Tests for plugin identity: declared key lists and the registry that indexes them."""

import pytest
from rehuco_core import (
    BUILTIN_PLUGINS,
    CORE_PLUGIN,
    DEFAULT_PLUGIN_REGISTRY,
    REFERENCE_IMAGES_PLUGIN,
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


def test_a_plugin_may_not_declare_the_same_key_twice() -> None:
    """A duplicate inside one declaration is a typo, not an alias.

    **Test steps:**

    * construct a spec repeating a key
    * verify it raises
    """
    with pytest.raises(ValueError, match="duplicate key"):
        PluginSpec(("tutorial", "tutorial"))


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

    ``core`` is deliberately absent too, alongside ``daz3d`` -- it is parked past milestone C, so it
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
