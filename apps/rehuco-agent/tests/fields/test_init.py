"""Tests for the document form composition: build_document_form over DOCUMENT_FIELD_SPECS.

(These cover ``documents.document_fields``; the file keeps its historical location under ``tests/fields``.)
"""

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import (
    EDITOR_DESCRIPTION_TAB,
    EDITOR_MAIN_TAB,
    VIEWER_TAB,
    build_document_form,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import LABEL_COLUMN
from rehuco_agent.fields.text_field import TextField


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


def test_build_document_form_puts_record_fields_on_the_main_editor_and_description_on_its_own_tab(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """build_document_form composes the record fields on the main editor tab, in declaration order, and
    the Markdown ``description`` on its own editor tab.

    The special ``location`` field is not part of ``DOCUMENT_FIELD_SPECS`` (its owner threads it in as
    a leading field), so it does not appear here.

    **Test steps:**

    * build the document form's editor grids with no leading fields
    * verify the main editor tab has the configured rows in declaration order
    * verify the description lands on its own editor tab
    """
    grids = build_document_form().make_editor(model)
    main = grids[EDITOR_MAIN_TAB]
    description = grids[EDITOR_DESCRIPTION_TAB]
    qtbot.addWidget(main)
    qtbot.addWidget(description)

    assert form_labels(main) == [
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


def test_build_document_form_places_leading_fields_first(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Leading fields are laid out before the record fields on the main editor tab, in order.

    **Test steps:**

    * build the form with a leading text field on the main editor tab
    * verify its label comes before the first record field's label
    """
    leading = TextField("location", viewer_tab=VIEWER_TAB, editor_tab=EDITOR_MAIN_TAB)
    main = build_document_form(leading_fields=[leading]).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(main)

    labels = form_labels(main)
    assert labels[0] == "Location"
    assert labels[1] == "Title"
