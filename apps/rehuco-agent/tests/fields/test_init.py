"""Tests for the document form composition: build_document_form over MODEL_AGNOSTIC_FIELD_SPECS.

(These cover ``documents.document_fields``; the file keeps its historical location under ``tests/fields``.)
"""

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import (
    EDITOR_DESCRIPTION_TAB,
    EDITOR_MAIN_TAB,
    build_document_form,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import LABEL_COLUMN
from rehuco_core import RehuDocument


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
        cell = item.widget() if item is not None else None
        label = cell if isinstance(cell, QLabel) else cell.findChild(QLabel) if cell is not None else None
        if label is not None:
            texts.append(label.text())
    return texts


def test_build_document_form_leads_with_location_then_the_record_fields_with_description_on_its_own_tab(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """build_document_form leads the main editor tab with ``location``, then the record fields in
    declaration order, and puts the Markdown ``description`` on its own editor tab.

    **Test steps:**

    * build the document form's editor grids for the model
    * verify the main editor tab leads with ``Location`` then the configured rows in declaration order
    * verify the description lands on its own editor tab
    """
    grids = build_document_form(model).make_editor(model)
    main = grids[EDITOR_MAIN_TAB]
    description = grids[EDITOR_DESCRIPTION_TAB]
    qtbot.addWidget(main)
    qtbot.addWidget(description)

    assert form_labels(main) == [
        "Location",
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
    # the description editor carries no row label -- its own dock tab ("Description") already names it
    assert not form_labels(description)


@mark.xfail(run=False, reason="per-user model plumbing (RehuDocumentModel onto the users-map accessors) is #99")
def test_build_document_form_trails_unknown_fields_after_the_record_fields(qtbot: QtBot) -> None:
    """A live-block key the model doesn't recognize is composed as a trailing `UnknownField`.

    **Test steps:**

    * build the form over a model whose Tutorial block carries an unrecognized ``mystery`` key
    * verify the main editor's last row is the unknown field, after the last record field (``Extra Tags``)
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "tutorial": {"mystery": 1}}))
    main = build_document_form(model).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(main)

    labels = form_labels(main)
    assert labels[-2:] == ["Extra Tags", "Mystery"]
