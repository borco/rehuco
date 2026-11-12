"""A root's layouts and fallbacks, edited: the one editor the Roots view's edit mode, the default root layouts on the
New Root Presets settings page and the Add Roots dialog's *New layout…* share ([[mounts-and-storage#rehuroot]], #578,
#637)."""

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from rehuco_core import (
    ANY_TYPE,
    DEFAULT_PLUGIN_REGISTRY,
    KEEP_NAME,
    PLACEHOLDERS,
    Layouts,
    grouped_layouts,
    layout_placeholders,
    layout_rows,
    layout_template_problem,
)

from ..settings.root_layout_templates_settings import REFUSED_TEMPLATES, shared_root_layout_templates_settings
from .root_layouts_editor_ui import Ui_RootLayoutsEditor


class RootLayoutsEditor(QWidget):
    """Two tables: the **layouts**, path templates per type, a type repeating and the order of the rows the order they
    are offered in (#638) -- the type picked from ``*`` and the installed types,
    or typed, the template picked from ``*`` and the Root Layout Templates the type accepts, or typed -- and the
    **fallbacks**, a text per placeholder, one fixed row for each placeholder a template may use (#637).

    **A template invalid for its row's type is flagged, never refused**: its cell is coloured, with the reason as its
    tooltip, and it is saved as typed, as the Locations pages do. ``*`` is checked against the four placeholders every
    type has, since it stands for any of them.

    What a caller shows is set with :meth:`set_values`, which says nothing; every edit after that is announced by
    :attr:`edited`, once.

    :param parent: optional Qt parent; what a ``.ui`` promotes the widget with.
    """

    edited = Signal()
    """Emitted once per edit of either table -- a row added, retyped or deleted, or a Reset."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootLayoutsEditor()
        self.__ui.setupUi(self)
        self.__filling = False
        layouts, fallbacks = self.__ui.layouts_editor, self.__ui.fallbacks_editor
        layouts.set_titles("Type", "Path template")
        layouts.allow_repeated_keys()
        layouts.set_key_choices((ANY_TYPE, *DEFAULT_PLUGIN_REGISTRY.main_keys))
        layouts.set_value_choices(RootLayoutsEditor.__template_choices)
        layouts.set_value_problem(RootLayoutsEditor.__template_problem)
        fallbacks.set_titles("Placeholder", "When empty")
        fallbacks.set_fixed_keys(PLACEHOLDERS)
        layouts.values_changed.connect(self.__on_edited)
        fallbacks.values_changed.connect(self.__on_edited)

    @property
    def layouts(self) -> dict[str, tuple[str, ...]]:
        """The layouts as the table makes them: a type's templates together, in row order; a row with no type or no
        template, or an exact repeat of an earlier row, is left out (#638)."""
        return grouped_layouts(self.__ui.layouts_editor.rows)

    @property
    def fallbacks(self) -> dict[str, str]:
        """The fallbacks as the table makes them, on the same rule."""
        return self.__ui.fallbacks_editor.mapping

    def set_values(self, layouts: Layouts, fallbacks: Mapping[str, str]) -> None:
        """Show these maps, announcing nothing.

        :param layouts: the layouts.
        :param fallbacks: the fallbacks.
        """
        self.__filling = True
        try:
            self.__ui.layouts_editor.rows = layout_rows(layouts)
            self.__ui.fallbacks_editor.mapping = fallbacks
        finally:
            self.__filling = False

    @staticmethod
    def __template_choices(main_key: str) -> tuple[str, ...]:
        """What the Path template drop-down offers a type: ``*``, then the library's templates the type accepts.

        :param main_key: the row's type, or ``*``.
        :returns: the templates, in the order the library holds them.
        """
        placeholders = layout_placeholders(main_key, DEFAULT_PLUGIN_REGISTRY)
        library = shared_root_layout_templates_settings().templates
        return (
            KEEP_NAME,
            *(
                template
                for template in library
                if template not in REFUSED_TEMPLATES and not layout_template_problem(template, placeholders)
            ),
        )

    @staticmethod
    def __template_problem(main_key: str, template: str) -> str:
        """Why a type's template cannot be used, or ``""``.

        :param main_key: the row's type, or ``*``.
        :param template: the template as written.
        :returns: the problem the Locations grammar finds, if any.
        """
        return layout_template_problem(template, layout_placeholders(main_key, DEFAULT_PLUGIN_REGISTRY))

    def __on_edited(self) -> None:
        """Pass an edit on, unless it is :meth:`set_values` filling the tables."""
        if not self.__filling:
            self.edited.emit()
