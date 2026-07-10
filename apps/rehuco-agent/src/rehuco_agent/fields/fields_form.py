"""Composes an ordered field list into per-tab viewer or editor 3-column grids ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Any, Final

from PySide6.QtWidgets import QGridLayout, QWidget

from rehuco_agent.fields.field import Field, FieldEditorWidgets, FieldModel, FieldsTab, FieldViewerWidgets

LABEL_COLUMN: Final = 0
MISC_COLUMN: Final = 1
CONTENT_COLUMN: Final = 2


class FieldsForm:
    """Builds a viewer or editor form from an ordered list of fields ([[plugins#field-toolkit]]).

    Fields are **grouped by their `FieldsTab`**: each factory returns one 3-column `QGridLayout`
    widget per tab (``{tab: grid}``), which the owner (`DocumentWidget`) hosts as one dock per tab.
    Rows are laid out **label** | **misc** | **content** -- a field can place an extra control (the
    ``path`` field's expand toggle, the ``misc`` slot of its
    :class:`~rehuco_agent.fields.field.FieldEditorWidgets`) in the middle column. The label and misc
    columns take their preferred width and don't grow; the content column takes the remaining width.

    Emptiness cascades: a field whose row widgets are all ``None`` contributes no row, and a tab that
    ends up with no rows is absent from the returned mapping (so no empty dock is built).

    :param fields: the fields to lay out, in display order.
    """

    def __init__(self, fields: Sequence[Field[Any]]) -> None:
        self.__fields: Final = tuple(fields)

    def make_viewer(self, model: FieldModel) -> dict[FieldsTab, QWidget]:
        """Build the read-only viewer grids, one per tab, bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a ``{tab: grid widget}`` mapping, in first-seen tab order; each grid holds one
            label -> viewer row per field on that tab (the misc column stays empty in the viewer).
        """
        by_tab: dict[FieldsTab, list[FieldViewerWidgets]] = {}
        for field in self.__fields:
            bundle = field.make_viewer(model.bind(field))
            if bundle.label is None and bundle.viewer is None:
                continue
            by_tab.setdefault(bundle.tab, []).append(bundle)

        grids: dict[FieldsTab, QWidget] = {}
        for tab, bundles in by_tab.items():
            widget = QWidget()
            grid = self.__make_grid(widget)
            for row, bundle in enumerate(bundles):
                if bundle.label is not None:
                    grid.addWidget(bundle.label, row, LABEL_COLUMN)
                if bundle.viewer is not None:
                    grid.addWidget(bundle.viewer, row, CONTENT_COLUMN)
            grids[tab] = widget
        return grids

    def make_editor(self, model: FieldModel) -> dict[FieldsTab, QWidget]:
        """Build the editor grids, one per tab, bound to the model.

        :param model: the reactive view-model each field resolves its binding against.
        :returns: a ``{tab: grid widget}`` mapping, in first-seen tab order; each grid holds one
            label | misc | editor row per field on that tab.
        """
        by_tab: dict[FieldsTab, list[FieldEditorWidgets]] = {}
        for field in self.__fields:
            bundle = field.make_editor(model.bind(field))
            if bundle.label is None and bundle.misc is None and bundle.editor is None:
                continue
            by_tab.setdefault(bundle.tab, []).append(bundle)

        grids: dict[FieldsTab, QWidget] = {}
        for tab, bundles in by_tab.items():
            widget = QWidget()
            grid = self.__make_grid(widget)
            for row, bundle in enumerate(bundles):
                if bundle.label is not None:
                    grid.addWidget(bundle.label, row, LABEL_COLUMN)
                if bundle.misc is not None:
                    grid.addWidget(bundle.misc, row, MISC_COLUMN)
                if bundle.editor is not None:
                    grid.addWidget(bundle.editor, row, CONTENT_COLUMN)
            grids[tab] = widget
        return grids

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
