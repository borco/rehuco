"""Tests for FieldsForm: composing an ordered field list into a viewer or editor layout."""

from PySide6.QtWidgets import QFormLayout, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import FieldsForm
from rehuco_agent.fields.text_field import TextField


def form_labels(layout: QFormLayout) -> list[str]:
    """Return the label-column text of every row in a `QFormLayout`, top to bottom.

    :param layout: the form layout to read.
    :returns: each row's label text, in order.
    """
    return [
        layout.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text()  # type: ignore[attr-defined]
        for row in range(layout.rowCount())
    ]


def test_form_composes_viewer_rows_in_order(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """make_viewer lays out one label -> viewer row per field, in declaration order.

    **Test steps:**

    * build a form over the title and publisher fields
    * build the viewer and read its ``QFormLayout``
    * verify a row per field with the labels in order
    """
    form = FieldsForm([TextField("title"), TextField("publisher")])
    widget = form.make_viewer(model)
    qtbot.addWidget(widget)

    layout = widget.layout()
    assert isinstance(layout, QFormLayout)
    assert form_labels(layout) == ["Title", "Publisher"]


def test_form_composes_editor_rows(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """make_editor lays out each field's editor as a labelled row.

    **Test steps:**

    * build a form over the title field
    * build the editor form and verify it has one labelled row holding a ``QLineEdit``
    """
    form = FieldsForm([TextField("title")])
    widget = form.make_editor(model)
    qtbot.addWidget(widget)

    layout = widget.layout()
    assert isinstance(layout, QFormLayout)
    assert layout.rowCount() == 1
    assert form_labels(layout) == ["Title"]
    field_item = layout.itemAt(0, QFormLayout.ItemRole.FieldRole)
    assert field_item is not None
    assert isinstance(field_item.widget(), QLineEdit)
