"""Tests for the document form composition: build_document_form over DOCUMENT_FIELD_SPECS.

(These cover ``documents.document_fields``; the file keeps its historical location under ``tests/fields``.)
"""

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, VIEWER_TAB, build_document_form
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import FieldsTab
from rehuco_agent.fields.fields_form import LABEL_COLUMN
from rehuco_agent.fields.text_field import TextField


def sole_grid_widget(grids: dict[FieldsTab, QWidget]) -> QWidget:
    """Return the single tab's grid widget (the document form uses one editor tab).

    :param grids: the ``{tab: grid}`` mapping from ``FieldsForm.make_editor``.
    :returns: the sole grid widget.
    """
    assert len(grids) == 1
    return next(iter(grids.values()))


def form_labels(widget: QWidget) -> list[str]:
    """Return the label-column text of every row in a form's grid, top to bottom.

    :param widget: the form grid widget built by ``build_document_form``.
    :returns: each row's label text, in order.
    """
    layout = widget.layout()
    assert isinstance(layout, QGridLayout)
    texts: list[str] = []
    for row in range(layout.rowCount()):
        item = layout.itemAtPosition(row, LABEL_COLUMN)
        label = item.widget() if item is not None else None
        if isinstance(label, QLabel):
            texts.append(label.text())
    return texts


def test_build_document_form_uses_the_configured_field_list(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """build_document_form composes the configured record fields -- text, flags, rating, level, tags -- in order.

    The special ``location`` field is not part of ``DOCUMENT_FIELD_SPECS`` (its owner threads it in as
    a leading field), so it does not appear here.

    **Test steps:**

    * build the document form's editor with no leading fields
    * verify it has the configured rows in declaration order
    """
    widget = sole_grid_widget(build_document_form().make_editor(model))
    qtbot.addWidget(widget)

    assert form_labels(widget) == [
        "Title",
        "Authors",
        "Released",
        "Publisher",
        "Url",
        "Advertised Duration",
        "Original Duration",
        "Current Duration",
        "Original Size",
        "Current Size",
        "Complete",
        "Online",
        "Viewed",
        "Todo",
        "Keep",
        "Favorite",
        "Rating",
        "Level",
        "Advertised Tags",
        "Extra Tags",
    ]


def test_build_document_form_places_leading_fields_first(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Leading fields are laid out before the record fields, in order.

    The leading field shares the record fields' editor tab, so they land in the same grid.

    **Test steps:**

    * build the form with a leading text field on the main editor tab
    * verify its label comes before the first record field's label
    """
    leading = TextField("location", viewer_tab=VIEWER_TAB, editor_tab=EDITOR_MAIN_TAB)
    widget = sole_grid_widget(build_document_form(leading_fields=[leading]).make_editor(model))
    qtbot.addWidget(widget)

    labels = form_labels(widget)
    assert labels[0] == "Location"
    assert labels[1] == "Title"
