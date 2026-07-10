"""Tests for FieldsForm: composing an ordered field list into a 3-column viewer or editor grid."""

from dataclasses import replace
from typing import override

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
