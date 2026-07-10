"""Tests for FieldsForm: composing an ordered field list into a 3-column viewer or editor grid."""

from dataclasses import replace
from typing import override

from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QToolButton, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import FieldBinding, FieldEditorWidgets
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, LABEL_COLUMN, MISC_COLUMN, FieldsForm

from fields.field_testers import TextFieldTester as TextField


# region Sample classes
class MiscField(TextField):
    """A sample field that contributes a misc-column widget (a ``QToolButton``)."""

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        return replace(super().make_editor(binding), misc=QToolButton())


# endregion


def widget_at(grid: QGridLayout, row: int, column: int) -> QWidget | None:
    """Return the widget at a grid cell, or ``None`` if the cell is empty.

    :param grid: the grid to read.
    :param row: the row index.
    :param column: the column index.
    :returns: the cell's widget, or ``None``.
    """
    item = grid.itemAtPosition(row, column)
    return item.widget() if item is not None else None


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
    widget = FieldsForm([TextField("title")]).make_viewer(model)
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
    widget = form.make_viewer(model)
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
    widget = form.make_editor(model)
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
    widget = form.make_editor(model)
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
    widget = form.make_viewer(model)
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    assert widget_at(grid, 0, MISC_COLUMN) is None
