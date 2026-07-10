"""Composes an ordered field list into a viewer or editor 3-column grid ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Any, Final

from PySide6.QtWidgets import QGridLayout, QWidget

from rehuco_agent.fields.field import Field, FieldModel

LABEL_COLUMN: Final = 0
MISC_COLUMN: Final = 1
CONTENT_COLUMN: Final = 2


class FieldsForm:
    """Builds a viewer or editor form from an ordered list of fields ([[plugins#field-toolkit]]).

    Rows are laid out in a 3-column `QGridLayout` -- **label** | **misc** | **content** -- so a field
    can place an extra control (the ``path`` field's expand toggle, the ``misc`` slot of its
    :class:`~rehuco_agent.fields.field.FieldEditorWidgets`) in the middle column between its label and
    its editor. The label and misc columns take their preferred width and don't grow; the content
    column takes the remaining width.

    :param fields: the fields to lay out, in display order.
    """

    def __init__(self, fields: Sequence[Field[Any]]) -> None:
        self.__fields: Final = tuple(fields)

    def make_viewer(self, model: FieldModel) -> QWidget:
        """Build a form of read-only viewer rows bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a widget whose grid holds one label -> viewer row per field, in order (the misc
            column stays empty in the viewer).
        """
        # FIXME(#26 stage 2): collapses every field into one grid, ignoring each bundle's tab --
        # replace with tab-grouped assembly returning one grid per FieldsTab.
        widget = QWidget()
        grid = self.__make_grid(widget)
        for row, field in enumerate(self.__fields):
            widgets = field.make_viewer(model.bind(field))
            if widgets.label is not None:
                grid.addWidget(widgets.label, row, LABEL_COLUMN)
            if widgets.viewer is not None:
                grid.addWidget(widgets.viewer, row, CONTENT_COLUMN)
        return widget

    def make_editor(self, model: FieldModel) -> QWidget:
        """Build a form of editor rows bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a widget whose grid holds one label | misc | editor row per field, in order.
        """
        # FIXME(#26 stage 2): collapses every field into one grid, ignoring each bundle's tab --
        # replace with tab-grouped assembly returning one grid per FieldsTab.
        widget = QWidget()
        grid = self.__make_grid(widget)
        for row, field in enumerate(self.__fields):
            widgets = field.make_editor(model.bind(field))
            if widgets.label is not None:
                grid.addWidget(widgets.label, row, LABEL_COLUMN)
            if widgets.misc is not None:
                grid.addWidget(widgets.misc, row, MISC_COLUMN)
            if widgets.editor is not None:
                grid.addWidget(widgets.editor, row, CONTENT_COLUMN)
        return widget

    @staticmethod
    def __make_grid(widget: QWidget) -> QGridLayout:
        """Install a 3-column grid on ``widget`` with the label/misc columns fixed and content stretching.

        :param widget: the widget to install the grid on.
        :returns: the installed grid layout.
        """
        grid = QGridLayout(widget)
        grid.setColumnStretch(LABEL_COLUMN, 0)
        grid.setColumnStretch(MISC_COLUMN, 0)
        grid.setColumnStretch(CONTENT_COLUMN, 1)
        return grid
