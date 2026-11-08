"""The default root layouts, edited on the Root Catalog settings page: their names, and the maps of the one selected
([[appendices.settings-pages#category-groups]], #578)."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtWidgets import QWidget

from ..root_catalog_settings import RootLayout
from .default_root_layouts_editor_ui import Ui_DefaultRootLayoutsEditor

NO_PRESET_SELECTED: Final = "Select a preset to edit its layouts and fallbacks."
"""What the heading over the maps says while no preset is selected."""

UNNAMED_PRESET: Final = "Unnamed preset"
"""What the heading calls a selected preset with no name."""


class DefaultRootLayoutsEditor(QWidget):
    """The list of layout names above the layouts and fallbacks of the one selected, which follow the selection.

    **A** :class:`~.settings_frame_filter.ValueControl`: its value is every layout, names and maps together, so the
    settings dialog snapshots, compares and restores the frame holding it with no per-page wiring -- the tables inside,
    whose content changes with the selection alone, are never read on their own.

    :param parent: optional Qt parent; what a ``.ui`` promotes the widget with.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_DefaultRootLayoutsEditor()
        self.__ui.setupUi(self)
        self.__ui.names_editor.current_index_changed.connect(self.__show_current)
        self.__ui.maps_editor.edited.connect(self.__on_maps_edited)
        self.__ui.names_editor.layout_model.dataChanged.connect(self.__show_heading)
        self.__show_current()

    @property
    def layouts(self) -> tuple[RootLayout, ...]:
        """Every layout, in order, as edited."""
        return self.__ui.names_editor.layout_model.entries

    @layouts.setter
    def layouts(self, layouts: Sequence[RootLayout]) -> None:
        editor = self.__ui.names_editor
        row = editor.current_index
        editor.layout_model.set_entries(layouts)
        editor.set_current_index(min(max(row, 0), len(layouts) - 1))
        self.__show_current()

    def settings_value(self) -> object:
        """Every layout, for the frame snapshot -- the `ValueControl` half of the seam."""
        return self.layouts

    def set_settings_value(self, value: object) -> None:
        """Write a snapshotted value back.

        :param value: the layouts, as :meth:`settings_value` returned them.
        """
        if isinstance(value, tuple):
            self.layouts = value

    def __show_current(self) -> None:
        """Show the selected layout's maps, or empty, disabled tables when none is selected."""
        row = self.__ui.names_editor.current_index
        entries = self.layouts
        maps = self.__ui.maps_editor
        if 0 <= row < len(entries):
            maps.set_values(entries[row].layouts, entries[row].fallbacks)
            maps.setEnabled(True)
        else:
            maps.set_values({}, {})
            maps.setEnabled(False)
        self.__show_heading()

    def __show_heading(self) -> None:
        """Name the selected preset over its maps -- again when it is renamed -- or say none is selected."""
        row = self.__ui.names_editor.current_index
        entries = self.layouts
        if 0 <= row < len(entries):
            self.__ui.selected_label.setText(f"{entries[row].label or UNNAMED_PRESET}:")
        else:
            self.__ui.selected_label.setText(NO_PRESET_SELECTED)

    def __on_maps_edited(self) -> None:
        """Keep the selected layout's maps as the tables now make them."""
        row = self.__ui.names_editor.current_index
        if 0 <= row < len(self.layouts):
            maps = self.__ui.maps_editor
            self.__ui.names_editor.layout_model.set_maps(row, maps.layouts, maps.fallbacks)
