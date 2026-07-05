"""Tests for the field toolkit's public entry points: build_document_form and DOCUMENT_FIELD_SPECS."""

from PySide6.QtWidgets import QFormLayout
from pytestqt.qtbot import QtBot
from rehuco_agent.fields import build_document_form
from rehuco_agent.rehu_document_model import RehuDocumentModel


def form_labels(layout: QFormLayout) -> list[str]:
    """Return the label-column text of every row in a `QFormLayout`, top to bottom.

    :param layout: the form layout to read.
    :returns: each row's label text, in order.
    """
    return [
        layout.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text()  # type: ignore[attr-defined]
        for row in range(layout.rowCount())
    ]


def test_build_document_form_uses_the_configured_field_list(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """build_document_form composes the title/publisher/url text fields, in order.

    **Test steps:**

    * build the document form's editor
    * verify it has the three configured rows in order
    """
    widget = build_document_form().make_editor(model)
    qtbot.addWidget(widget)

    layout = widget.layout()
    assert isinstance(layout, QFormLayout)
    assert form_labels(layout) == ["Title", "Publisher", "Url"]
