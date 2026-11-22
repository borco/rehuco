"""Tests for New Table Browser's presets: the plain one, and one per type that contributes columns (#400)."""

from rehuco_agent.rehuco.browser_presets import DEFAULT_PRESET, BrowserPreset, browser_presets
from rehuco_agent.rehuco.catalog_table_model import DEFAULT_HIDDEN, TYPE_COLUMNS, CatalogColumn
from rehuco_core import TYPE_FIELD_COLUMNS, PluginRegistry, PluginSpec, catalog_type_fields

DURATIONS = frozenset(
    {
        CatalogColumn.ADVERTISED_DURATION,
        CatalogColumn.ORIGINAL_DURATION,
        CatalogColumn.CURRENT_DURATION,
        CatalogColumn.LEVEL,
    }
)
COUNTS = frozenset({CatalogColumn.ADVERTISED_COUNT, CatalogColumn.CURRENT_COUNT})


def preset_labeled(label: str, presets: tuple[BrowserPreset, ...]) -> BrowserPreset:
    """The preset whose menu entry is ``label``."""
    return next(preset for preset in presets if preset.label == label)


def test_every_type_column_is_a_field_the_cache_stores() -> None:
    """The columns a preset turns a type's fields into are the cache's type-specific fields, in the cache's order --
    all of them but an asset's, which the cache stores before the browser has columns for them (#676, #678).

    **Test steps:**

    * verify :data:`TYPE_COLUMNS` is keyed by the cache fields that are not an asset's, in the cache's order
    """
    asset_fields = set(catalog_type_fields("asset"))

    assert tuple(TYPE_COLUMNS) == tuple(field for field in TYPE_FIELD_COLUMNS if field not in asset_fields)


def test_the_built_in_presets_are_the_default_then_one_per_type_with_columns() -> None:
    """Default first, then Tutorial and Reference Images -- not Collection, which contributes no column, nor Asset,
    whose cached fields have no column yet (#678).

    **Test steps:**

    * build the presets from the built-in plugins
    * verify their labels and names, in order
    """
    presets = browser_presets()

    assert [preset.label for preset in presets] == ["Default", "Tutorial Columns", "Reference Images Columns"]
    assert [preset.name for preset in presets] == ["Browser", "Tutorial", "Reference Images"]


def test_the_default_preset_is_a_plain_browser() -> None:
    """The plain preset hides what a plain browser hides and filters nothing.

    **Test steps:**

    * verify the default preset's hidden columns and filter
    """
    assert DEFAULT_PRESET.hidden == DEFAULT_HIDDEN
    assert not DEFAULT_PRESET.filter


def test_a_typed_preset_shows_its_types_columns_hides_the_others_and_filters_by_type() -> None:
    """Tutorial shows the durations and level, Reference Images the counts; each hides the other's, and the URL.

    **Test steps:**

    * build the presets
    * verify each typed preset's hidden columns and ``type:`` token
    """
    presets = browser_presets()
    tutorial = preset_labeled("Tutorial Columns", presets)
    reference = preset_labeled("Reference Images Columns", presets)

    assert tutorial.hidden == COUNTS | {CatalogColumn.URL, CatalogColumn.ROOT}
    assert tutorial.filter == "type:tutorial"
    assert reference.hidden == DURATIONS | {CatalogColumn.URL, CatalogColumn.ROOT}
    assert reference.filter == "type:reference_images"


def test_a_type_that_gains_a_column_is_offered_without_a_change_here() -> None:
    """A plugin declaring a cached field is offered; one declaring none, or only uncached fields, is not.

    **Test steps:**

    * build the presets from a registry with a type declaring ``current_count``, one declaring nothing and one
      declaring only a field the cache does not store
    * verify only the first is offered, showing its one column
    """
    plugins = PluginRegistry(
        (
            PluginSpec(("comic_pack",), field_names=("rating", "current_count")),
            PluginSpec(("empty",)),
            PluginSpec(("rated",), field_names=("rating",)),
        )
    )

    presets = browser_presets(plugins)

    assert [preset.label for preset in presets] == ["Default", "Comic Pack Columns"]
    comic = presets[1]
    assert CatalogColumn.CURRENT_COUNT not in comic.hidden
    assert comic.hidden == (DEFAULT_HIDDEN | DURATIONS | COUNTS) - {CatalogColumn.CURRENT_COUNT}
    assert comic.filter == "type:comic_pack"


def test_with_no_type_contributing_columns_only_the_default_is_offered() -> None:
    """No plugin with a column leaves the plain preset alone.

    **Test steps:**

    * build the presets from an empty registry
    * verify only the default
    """
    assert browser_presets(PluginRegistry()) == (DEFAULT_PRESET,)
