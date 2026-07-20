"""Composes an ordered field list into per-tab viewer or editor 3-column grids ([[plugins#field-toolkit]])."""

from collections.abc import Sequence
from typing import Any, Final

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from rehuco_agent.fields.field import (
    Field,
    FieldEditorWidgets,
    FieldModel,
    FieldsTab,
    FieldViewerWidgets,
    HeaderPinned,
)

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

    A bundle may instead request a **vertical** row (``vertical=True``): it spans the whole grid width
    and stacks its widgets in an inner ``QVBoxLayout`` -- the label (and the editor's optional
    ``misc``) on top, the viewer/editor full-width below -- which reads better for prose (the Markdown
    ``description``).

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
                if bundle.vertical:
                    self.__add_vertical_row(grid, row, (bundle.label,), bundle.viewer)
                    continue
                if bundle.label is not None:
                    grid.addWidget(bundle.label, row, LABEL_COLUMN)
                if bundle.viewer is not None:
                    grid.addWidget(bundle.viewer, row, CONTENT_COLUMN)
            self.__distribute_vertical_space(grid, bundles)
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
                if bundle.vertical:
                    self.__add_vertical_row(grid, row, (bundle.label, bundle.misc), bundle.editor)
                    continue
                if isinstance(bundle.editor, HeaderPinned):
                    self.__add_header_pinned_row(
                        grid, row, bundle.label, bundle.misc, bundle.editor, bundle.editor.header_height
                    )
                    continue
                if bundle.label is not None:
                    grid.addWidget(bundle.label, row, LABEL_COLUMN)
                if bundle.misc is not None:
                    grid.addWidget(bundle.misc, row, MISC_COLUMN)
                if bundle.editor is not None:
                    grid.addWidget(bundle.editor, row, CONTENT_COLUMN)
            self.__distribute_vertical_space(grid, bundles)
            grids[tab] = widget
        return grids

    @staticmethod
    def __add_vertical_row(
        grid: QGridLayout,
        row: int,
        header: tuple[QWidget | None, ...],
        content: QWidget | None,
    ) -> None:
        """Add a full-width vertical row: the ``header`` widgets on a top line, ``content`` stacked below.

        The row spans all three grid columns. Its widgets are stacked in an inner ``QVBoxLayout``; the
        header widgets (label, and the editor's optional ``misc``) share the top line via a
        ``QHBoxLayout`` when more than one is present. ``None`` slots are skipped.

        :param grid: the grid to add the row to.
        :param row: the grid row index.
        :param header: the top-line widgets (label, optional misc), in order.
        :param content: the full-width body widget (viewer or editor) placed below the header.
        """
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        top = [widget for widget in header if widget is not None]
        if len(top) == 1:
            column.addWidget(top[0])
        elif top:
            line = QHBoxLayout()
            for widget in top:
                line.addWidget(widget)
            line.addStretch()
            column.addLayout(line)
        if content is not None:
            column.addWidget(content)
        grid.addWidget(container, row, LABEL_COLUMN, 1, CONTENT_COLUMN - LABEL_COLUMN + 1)

    @staticmethod
    def __add_header_pinned_row(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        grid: QGridLayout,
        row: int,
        label: QWidget | None,
        misc: QWidget | None,
        editor: QWidget,
        header_height: int,
    ) -> None:
        """Add a label | misc | editor row whose label, misc, and the editor's first line are all
        pinned to a shared top-aligned reference instead of re-centering against the row's live
        height ([[plugins#field-toolkit]]'s `HeaderPinned` contract) -- e.g. the ``path`` editor's
        suggestions panel or a `multi_choice` checkbox `FlowLayout`, both of which grow well past
        their first line.

        Each widget is wrapped in its own top-pinned container (:meth:`__pin_to_top`), so none of
        them is stretched by the grid to the row's full height. The reference is whichever of
        ``header_height``/``label``/``misc`` is tallest -- usually ``header_height`` (the editor's own
        first line), but a misc control can be taller (#104's `ExpandToggleButton`, at its natural,
        un-shrunk size) -- and each of the three gets a fixed top margin sized to *look* centered
        against that shared reference, reproducing the plain-fill appearance when the editor is at its
        natural (single-line) height, but as a fixed offset that can't drift when the editor grows.
        Since none of the three inputs change with ``expanded``, the whole group's relative alignment
        stays fixed regardless -- only the editor's own growth below its first line moves.

        :param grid: the grid to add the row to.
        :param row: the grid row index.
        :param label: the field's name label, or ``None`` for none.
        :param misc: the optional middle-column control, or ``None`` for none.
        :param editor: the `HeaderPinned` editor.
        :param header_height: ``editor.header_height``, passed in already resolved.
        """
        label_height = label.sizeHint().height() if label is not None else 0
        misc_height = misc.sizeHint().height() if misc is not None else 0
        reference = max(header_height, label_height, misc_height)
        if label is not None:
            grid.addWidget(FieldsForm.__pin_to_top(label, (reference - label_height) // 2), row, LABEL_COLUMN)
        if misc is not None:
            grid.addWidget(FieldsForm.__pin_to_top(misc, (reference - misc_height) // 2), row, MISC_COLUMN)
        grid.addWidget(FieldsForm.__pin_to_top(editor, (reference - header_height) // 2), row, CONTENT_COLUMN)

    @staticmethod
    def __pin_to_top(widget: QWidget, top_margin: int) -> QWidget:
        """Wrap ``widget`` in a container that holds it at its natural height, ``top_margin`` pixels
        below the container's top, with the rest of any leftover space absorbed by a trailing stretch
        -- so a grid cell taller than ``widget`` can't grow or re-center it.

        :param widget: the widget to pin (opaque to this method -- any `QWidget` works).
        :param top_margin: the fixed vertical offset, in pixels.
        :returns: the wrapping container, ready to add to the grid.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, top_margin, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        layout.addStretch()
        return container

    @staticmethod
    def __distribute_vertical_space(
        grid: QGridLayout, bundles: Sequence[FieldViewerWidgets | FieldEditorWidgets]
    ) -> None:
        """Decide which grid row(s) absorb a tab's leftover vertical height.

        Each row a field marks ``fill`` (the prose ``description``, the image *selector* editor) is
        given the stretch, so it grows to take the available space. When **no** row fills, a trailing
        empty stretch row is added instead, so the plain fields keep their natural height and pack at
        the top rather than spreading apart to fill a taller dock. A vertical row that doesn't fill
        (the fixed-height image *strip* in the viewer) is treated as a plain row here.

        :param grid: the grid to set row stretches on.
        :param bundles: the tab's row bundles, in order (index = row; its length is the trailing row).
        """
        fill_rows = [row for row, bundle in enumerate(bundles) if bundle.fill]
        if fill_rows:
            for row in fill_rows:
                grid.setRowStretch(row, 1)
        else:
            grid.setRowStretch(len(bundles), 1)

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
