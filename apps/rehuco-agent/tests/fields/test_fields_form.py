"""Tests for FieldsForm: composing an ordered field list into a 3-column viewer or editor grid."""

from dataclasses import replace
from typing import Final, override

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, LABEL_COLUMN, MISC_COLUMN, FieldsForm

from fields.field_testers import TextFieldTester as TextField


# region Sample classes
class MiscField(TextField):
    """A sample field that contributes a misc-column widget (a ``QToolButton``)."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), misc=QToolButton())


class VerticalField(TextField):
    """A sample field whose viewer and editor bundles request a vertical (full-width) row."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), vertical=True)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), vertical=True)


class FillField(TextField):
    """A sample field whose viewer and editor bundles request a space-filling row (``fill=True``)."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), vertical=True, fill=True)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), vertical=True, fill=True)


class VerticalMiscField(VerticalField):
    """A vertical sample field that also contributes a misc widget (to test the shared top line)."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), misc=QToolButton())


class EmptyField(TextField):
    """A sample field whose viewer and editor bundles are entirely empty (all widgets ``None``)."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), label=None, viewer=None)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), label=None, editor=None, misc=None)


class LabellessField(TextField):
    """A sample field that contributes content but no label (label column stays empty)."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), label=None)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), label=None)


class ContentlessField(TextField):
    """A sample field that contributes a label but no viewer/editor (content column stays empty)."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), viewer=None)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), editor=None)


class VerticalContentlessField(VerticalField):
    """A vertical sample field with a label but no content (its full-width body is ``None``)."""

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return replace(super().make_viewer(binding), viewer=None)


class HeaderPinnedEditor(QLineEdit):
    """A sample editor with a fixed :attr:`header_height` (the ``HeaderPinned`` contract), standing in
    for the real dynamic-height editors (``PathEditor``, ``ChoiceCheckBoxes``) in layout-only tests.
    """

    def __init__(self, header_height: int) -> None:
        super().__init__()
        self.__header_height: Final = header_height

    @property
    def header_height(self) -> int:
        """This editor's fixed, test-controlled first-line height."""
        return self.__header_height


HEADER_HEIGHT: Final = 40
"""Taller than a plain label/tool button's sizeHint, so pinned rows get a non-zero top margin."""


class HeaderPinnedField(TextField):
    """A sample field whose editor implements ``HeaderPinned`` (a fixed :data:`HEADER_HEIGHT`)."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), editor=HeaderPinnedEditor(HEADER_HEIGHT))


class HeaderPinnedMiscField(HeaderPinnedField):
    """A ``HeaderPinned`` sample field that also contributes a misc-column widget."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), misc=QToolButton())


TALL_MISC_HEIGHT: Final = HEADER_HEIGHT + 20
"""Taller than :data:`HEADER_HEIGHT` itself -- the #104 scenario (`ExpandToggleButton`, at its
natural size, next to `PathEditor`'s short current-name line)."""


class TallToolButton(QToolButton):
    """A ``QToolButton`` whose own ``sizeHint`` is fixed to :data:`TALL_MISC_HEIGHT` -- standing in
    for a real icon-sized misc control (``setFixedSize`` alone wouldn't do: it constrains the
    *rendered* size, not ``sizeHint()``, which is what :meth:`FieldsForm.__add_header_pinned_row`
    actually reads).
    """

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(TALL_MISC_HEIGHT, TALL_MISC_HEIGHT)


class HeaderPinnedTallMiscField(HeaderPinnedField):
    """A ``HeaderPinned`` sample field whose misc-column widget is taller than ``header_height``."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), misc=TallToolButton())


class HeaderPinnedLabellessField(HeaderPinnedField):
    """A ``HeaderPinned`` sample field with no label (its row has no label to pin)."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), label=None)


# endregion


def vertical_container(grid: QGridLayout, row: int) -> QVBoxLayout:
    """Return the inner ``QVBoxLayout`` of a full-width vertical row at ``row``.

    :param grid: the grid to read.
    :param row: the row index whose spanning container to read.
    :returns: the container widget's vertical layout.
    """
    container = widget_at(grid, row, LABEL_COLUMN)
    assert container is not None
    layout = container.layout()
    assert isinstance(layout, QVBoxLayout)
    return layout


def descendant_widgets(layout: QLayout) -> list[QWidget]:
    """Return every widget nested under ``layout``, recursing into child layouts, in visual order.

    :param layout: the layout to walk.
    :returns: the flattened widget list, top to bottom.
    """
    widgets: list[QWidget] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        child_widget = item.widget()
        child_layout = item.layout()
        if child_widget is not None:
            widgets.append(child_widget)
        elif child_layout is not None:
            widgets.extend(descendant_widgets(child_layout))
    return widgets


def widget_at(grid: QGridLayout, row: int, column: int) -> QWidget | None:
    """Return the widget at a grid cell, or ``None`` if the cell is empty.

    :param grid: the grid to read.
    :param row: the row index.
    :param column: the column index.
    :returns: the cell's widget, or ``None``.
    """
    item = grid.itemAtPosition(row, column)
    return item.widget() if item is not None else None


def sole_grid_widget(grids: dict[FieldsTab, QWidget]) -> QWidget:
    """Return the single tab's grid widget from a ``{tab: grid}`` mapping (these tests use one tab).

    :param grids: the mapping returned by ``FieldsForm.make_viewer``/``make_editor``.
    :returns: the sole grid widget.
    """
    assert len(grids) == 1
    return next(iter(grids.values()))


def grid_of(widget: QWidget) -> QGridLayout:
    """Return a form widget's grid layout.

    :param widget: the form widget built by ``FieldsForm``.
    :returns: its ``QGridLayout``.
    """
    layout = widget.layout()
    assert isinstance(layout, QGridLayout)
    return layout


def pin_top_margin(cell: QWidget) -> int:
    """Read a pinned-row cell's top margin (its wrapping container's ``QVBoxLayout`` top margin).

    :param cell: the grid cell widget (the pin-to-top container).
    :returns: the container layout's top content margin, in pixels.
    """
    layout = cell.layout()
    assert isinstance(layout, QVBoxLayout)
    return layout.contentsMargins().top()


def label_texts(grid: QGridLayout) -> list[str]:
    """Return the label-column text of every row, top to bottom.

    :param grid: the grid to read.
    :returns: each row's label text, in order.
    """
    texts: list[str] = []
    for row in range(grid.rowCount()):
        label = widget_at(grid, row, LABEL_COLUMN)
        if isinstance(label, QLabel):
            texts.append(label.text())
    return texts


def test_columns_are_fixed_label_and_misc_with_stretching_content(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The label and misc columns take preferred width (no stretch); the content column stretches.

    **Test steps:**

    * build any form and read its grid
    * verify column stretch is 0/0/1 for label/misc/content
    """
    widget = sole_grid_widget(FieldsForm([TextField("title")]).make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert grid.columnStretch(LABEL_COLUMN) == 0
    assert grid.columnStretch(MISC_COLUMN) == 0
    assert grid.columnStretch(CONTENT_COLUMN) == 1


def test_plain_grid_gets_a_trailing_stretch_row(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A grid with no filling row gets a trailing stretch row so its fields keep their natural height.

    **Test steps:**

    * build a viewer form of two plain fields (none filling)
    * verify the row past the last field has stretch 1 while the field rows have none
    """
    widget = sole_grid_widget(FieldsForm([TextField("title"), TextField("publisher")]).make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert grid.rowStretch(0) == 0
    assert grid.rowStretch(1) == 0
    assert grid.rowStretch(2) == 1


def test_a_filling_row_takes_the_stretch_and_there_is_no_trailing_row(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A ``fill`` row is given the stretch (owns the slack); no trailing stretch row is added.

    **Test steps:**

    * build an editor form whose second field fills (``fill=True``)
    * verify that row carries the stretch and no other row (including the trailing index) does
    """
    widget = sole_grid_widget(FieldsForm([TextField("title"), FillField("publisher")]).make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    # only the two field rows exist -- no trailing stretch row was appended (rowCount stays 2)
    assert grid.rowCount() == 2
    assert grid.rowStretch(0) == 0
    assert grid.rowStretch(1) == 1


def test_a_vertical_non_filling_row_still_gets_the_trailing_stretch(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A vertical row that doesn't fill (e.g. the fixed-height image strip) counts as a plain row.

    **Test steps:**

    * build a viewer form whose second field is vertical but not filling
    * verify the trailing stretch row is still added (the vertical row keeps its natural height)
    """
    widget = sole_grid_widget(FieldsForm([TextField("title"), VerticalField("publisher")]).make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert grid.rowStretch(0) == 0
    assert grid.rowStretch(1) == 0
    assert grid.rowStretch(2) == 1


def test_viewer_lays_out_label_and_viewer_rows_in_order(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """make_viewer places each field's label in the label column and viewer in the content column, in order.

    **Test steps:**

    * build a viewer form over title and publisher
    * verify the label column holds both labels in order and the content column holds their viewers
    """
    form = FieldsForm([TextField("title"), TextField("publisher")])
    widget = sole_grid_widget(form.make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert label_texts(grid) == ["Title", "Publisher"]
    assert widget_at(grid, 0, CONTENT_COLUMN) is not None
    assert widget_at(grid, 0, MISC_COLUMN) is None


def test_editor_places_the_editor_in_the_content_column(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """make_editor places a field's editor in the content column with its label in the label column.

    **Test steps:**

    * build an editor form over the title field
    * verify the label is in the label column and a ``QLineEdit`` is in the content column
    """
    form = FieldsForm([TextField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert label_texts(grid) == ["Title"]
    assert isinstance(widget_at(grid, 0, CONTENT_COLUMN), QLineEdit)


def test_editor_places_a_misc_widget_in_the_misc_column(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A field's ``FieldEditorWidgets.misc`` widget lands in the misc column, between label and editor.

    **Test steps:**

    * build an editor form over a field that contributes a misc widget
    * verify the misc column holds it and the editor is still in the content column
    """
    form = FieldsForm([MiscField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert isinstance(widget_at(grid, 0, MISC_COLUMN), QToolButton)
    assert isinstance(widget_at(grid, 0, CONTENT_COLUMN), QLineEdit)


def test_viewer_never_populates_the_misc_column(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer leaves the misc column empty even for a field that has a misc widget.

    **Test steps:**

    * build a viewer form over a misc-contributing field
    * verify the misc column is empty (misc is an editor-only concern)
    """
    form = FieldsForm([MiscField("title")])
    widget = sole_grid_widget(form.make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert widget_at(grid, 0, MISC_COLUMN) is None


def test_vertical_viewer_row_stacks_label_over_viewer_full_width(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A vertical viewer bundle spans all columns, stacking its label above the viewer.

    **Test steps:**

    * build a viewer form over a vertical field
    * verify one container spans all three columns and stacks label then viewer
    """
    form = FieldsForm([VerticalField("title")])
    widget = sole_grid_widget(form.make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    container = widget_at(grid, 0, LABEL_COLUMN)
    assert widget_at(grid, 0, MISC_COLUMN) is container
    assert widget_at(grid, 0, CONTENT_COLUMN) is container
    stacked = descendant_widgets(vertical_container(grid, 0))
    assert len(stacked) == 2
    assert isinstance(stacked[0], QLabel)
    assert stacked[0].text() == "Title"


def test_vertical_editor_row_stacks_label_over_editor_full_width(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A vertical editor bundle spans all columns, stacking its label above the editor.

    **Test steps:**

    * build an editor form over a vertical field
    * verify the spanning container stacks label then editor
    """
    form = FieldsForm([VerticalField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    stacked = descendant_widgets(vertical_container(grid, 0))
    assert isinstance(stacked[0], QLabel)
    assert isinstance(stacked[1], QLineEdit)


def test_vertical_editor_row_keeps_misc_on_the_top_line(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A vertical editor's misc control shares the top line with the label, above the full-width editor.

    **Test steps:**

    * build an editor form over a vertical field that also contributes a misc widget
    * verify label and misc precede the editor in the stacked order
    """
    form = FieldsForm([VerticalMiscField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    stacked = descendant_widgets(vertical_container(grid, 0))
    assert isinstance(stacked[0], QLabel)
    assert isinstance(stacked[1], QToolButton)
    assert isinstance(stacked[2], QLineEdit)


def test_a_field_with_no_widgets_contributes_no_tab(model: RehuDocumentModel) -> None:
    """A field whose viewer/editor bundle is all ``None`` produces no row, so its tab is absent.

    **Test steps:**

    * build viewer and editor forms over a single all-empty field
    * verify both mappings are empty (the empty tab cascades away)
    """
    form = FieldsForm([EmptyField("title")])

    assert not form.make_viewer(model)
    assert not form.make_editor(model)


def test_label_column_stays_empty_for_a_labelless_field(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A field with content but no label leaves the label column empty while still placing content.

    **Test steps:**

    * build viewer and editor forms over a label-less field
    * verify the label column is empty and the content column is populated in each
    """
    for grids in (
        FieldsForm([LabellessField("title")]).make_viewer(model),
        FieldsForm([LabellessField("title")]).make_editor(model),
    ):
        widget = sole_grid_widget(grids)
        qtbot.addWidget(widget)
        grid = grid_of(widget)
        assert widget_at(grid, 0, LABEL_COLUMN) is None
        assert widget_at(grid, 0, CONTENT_COLUMN) is not None


def test_content_column_stays_empty_for_a_contentless_field(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A field with a label but no viewer/editor leaves the content column empty while placing the label.

    **Test steps:**

    * build viewer and editor forms over a content-less field
    * verify the label column is populated and the content column is empty in each
    """
    for grids in (
        FieldsForm([ContentlessField("title")]).make_viewer(model),
        FieldsForm([ContentlessField("title")]).make_editor(model),
    ):
        widget = sole_grid_widget(grids)
        qtbot.addWidget(widget)
        grid = grid_of(widget)
        assert isinstance(widget_at(grid, 0, LABEL_COLUMN), QLabel)
        assert widget_at(grid, 0, CONTENT_COLUMN) is None


def test_vertical_row_omits_missing_content(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A vertical bundle with no content stacks only its label (the body widget is skipped).

    **Test steps:**

    * build a viewer form over a vertical field whose content is ``None``
    * verify the spanning container holds only the label
    """
    form = FieldsForm([VerticalContentlessField("title")])
    widget = sole_grid_widget(form.make_viewer(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    stacked = descendant_widgets(vertical_container(grid, 0))
    assert len(stacked) == 1
    assert isinstance(stacked[0], QLabel)


def test_header_pinned_editor_row_wraps_label_misc_and_editor_each_in_a_pin_container(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A ``HeaderPinned`` editor's row wraps its label, misc, and editor each in their own container,
    instead of placing them directly in the grid cell -- so the grid can't stretch/re-center them.

    **Test steps:**

    * build an editor form over a ``HeaderPinned`` field that also contributes a misc widget
    * verify each column holds a plain container (not the label/misc/editor itself)
    * verify the label/misc/editor are still reachable as descendants, in the expected type
    """
    form = FieldsForm([HeaderPinnedMiscField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    label_cell = widget_at(grid, 0, LABEL_COLUMN)
    misc_cell = widget_at(grid, 0, MISC_COLUMN)
    editor_cell = widget_at(grid, 0, CONTENT_COLUMN)
    assert label_cell is not None and not isinstance(label_cell, QLabel)
    assert misc_cell is not None and not isinstance(misc_cell, QToolButton)
    assert editor_cell is not None and not isinstance(editor_cell, HeaderPinnedEditor)

    assert isinstance(label_cell.findChild(QLabel), QLabel)
    assert isinstance(misc_cell.findChild(QToolButton), QToolButton)
    assert isinstance(editor_cell.findChild(HeaderPinnedEditor), HeaderPinnedEditor)


def test_header_pinned_editor_row_gives_label_and_misc_a_centering_top_margin(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The label, misc, and editor containers each get a fixed top margin sized to look centered
    against a shared reference -- here ``header_height`` (the editor's own first line), since it's
    taller than the plain label/tool button, so the editor's own container gets none.

    **Test steps:**

    * build an editor form over a ``HeaderPinned`` field with a misc widget
    * verify each container's top margin matches ``(header_height - widget height) // 2``
    * verify the editor's own container is unmoved (``header_height`` is the tallest of the three)
    """
    form = FieldsForm([HeaderPinnedMiscField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    label_cell = widget_at(grid, 0, LABEL_COLUMN)
    misc_cell = widget_at(grid, 0, MISC_COLUMN)
    editor_cell = widget_at(grid, 0, CONTENT_COLUMN)
    assert label_cell is not None and misc_cell is not None and editor_cell is not None
    label = label_cell.findChild(QLabel)
    misc = misc_cell.findChild(QToolButton)
    assert label is not None and misc is not None

    assert pin_top_margin(label_cell) == (HEADER_HEIGHT - label.sizeHint().height()) // 2
    assert pin_top_margin(misc_cell) == (HEADER_HEIGHT - misc.sizeHint().height()) // 2
    assert pin_top_margin(editor_cell) == 0


def test_header_pinned_editor_row_shifts_label_and_editor_down_for_a_tall_misc(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """When the misc control is *taller* than the editor's ``header_height`` (#104's
    `ExpandToggleButton`, at its natural size, next to `PathEditor`'s short current-name line) --
    the reference becomes the misc control's own height, so the label *and* the editor's first line
    both shift down to center against it, instead of the editor staying pinned flush at the top and
    the misc control hanging below the text baseline.

    **Test steps:**

    * build an editor form over a ``HeaderPinned`` field whose misc widget is taller than
      ``header_height``
    * verify the misc container is unmoved (it's now the tallest of the three) and the label/editor
      containers both get a matching positive top margin, centering them against it
    """
    form = FieldsForm([HeaderPinnedTallMiscField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    label_cell = widget_at(grid, 0, LABEL_COLUMN)
    misc_cell = widget_at(grid, 0, MISC_COLUMN)
    editor_cell = widget_at(grid, 0, CONTENT_COLUMN)
    assert label_cell is not None and misc_cell is not None and editor_cell is not None
    label = label_cell.findChild(QLabel)
    misc = misc_cell.findChild(QToolButton)
    assert label is not None and misc is not None

    misc_height = misc.sizeHint().height()
    assert misc_height > HEADER_HEIGHT
    assert pin_top_margin(misc_cell) == 0
    assert pin_top_margin(label_cell) == (misc_height - label.sizeHint().height()) // 2
    assert pin_top_margin(editor_cell) == (misc_height - HEADER_HEIGHT) // 2


def test_header_pinned_editor_row_without_a_label_still_pins_the_editor(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A ``HeaderPinned`` row with no label leaves the label column empty and still pins the editor
    (the label-less branch of the pinned-row builder).

    **Test steps:**

    * build an editor form over a label-less ``HeaderPinned`` field
    * verify the label column is empty and the editor is still reachable, pinned, in the content column
    """
    form = FieldsForm([HeaderPinnedLabellessField("title")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert widget_at(grid, 0, LABEL_COLUMN) is None
    editor_cell = widget_at(grid, 0, CONTENT_COLUMN)
    assert editor_cell is not None
    assert isinstance(editor_cell.findChild(HeaderPinnedEditor), HeaderPinnedEditor)
