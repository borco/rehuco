"""What New Table Browser can start a browser from: the plain one, and one per type that contributes columns (#400)."""

from dataclasses import dataclass
from typing import Final

from rehuco_core import DEFAULT_PLUGIN_REGISTRY, CatalogField, PluginRegistry, catalog_type_fields

from ..fields.type_field import type_label
from .catalog_table_model import DEFAULT_HIDDEN, TYPE_COLUMNS, CatalogColumn
from .filter_line import format_token

DEFAULT_PRESET_LABEL: Final = "Default"
"""The plain preset's menu entry."""

DEFAULT_BROWSER_NAME: Final = "Browser"
"""What a browser made from the plain preset -- or from no preset at all -- is called."""


@dataclass(frozen=True, slots=True)
class BrowserPreset:
    """What a new table browser starts as. Only its start: the browser is then an ordinary one, renamed, cloned and
    edited like any other, and remembers no preset.

    :param label: the menu entry.
    :param name: the new browser's name.
    :param hidden: the columns its header starts with hidden.
    :param filter: its filter line's text.
    """

    label: str
    name: str
    hidden: frozenset[CatalogColumn]
    filter: str = ""


DEFAULT_PRESET: Final = BrowserPreset(DEFAULT_PRESET_LABEL, DEFAULT_BROWSER_NAME, DEFAULT_HIDDEN)
"""The common columns, every resource -- what a plain New Table Browser makes."""


def browser_presets(plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY) -> tuple[BrowserPreset, ...]:
    """Every preset New Table Browser offers: :data:`DEFAULT_PRESET`, then one per installed type that contributes
    columns (:func:`~rehuco_core.catalog_type_fields`), in the plugins' order.

    A typed preset shows its type's columns, hides every other type's -- and whatever the plain browser hides -- and
    puts a ``type:`` token on the line. Built from what each plugin declares, so a type that gains a column is offered
    without a change here, and one that contributes none is not.

    :param plugins: the plugins installed here.
    :returns: the presets, in menu order.
    """
    every_type_column = frozenset(TYPE_COLUMNS.values())
    typed = []
    for key in plugins.main_keys:
        shown = frozenset(TYPE_COLUMNS[field] for field in catalog_type_fields(key, plugins))
        if shown:
            label = type_label(key)
            typed.append(
                BrowserPreset(
                    f"{label} Columns",
                    label,
                    (DEFAULT_HIDDEN | every_type_column) - shown,
                    format_token(CatalogField.TYPE.value, key),
                )
            )
    return (DEFAULT_PRESET, *typed)
