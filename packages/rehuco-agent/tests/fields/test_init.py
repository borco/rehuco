"""Tests for the document form composition: build_document_form over MODEL_AGNOSTIC_FIELD_SPECS.

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
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import LABEL_COLUMN
from rehuco_agent.fields.widgets.learning_paths_table_model import LearningPathsTableModel
from rehuco_agent.fields.widgets.memberships_editor import LearningPathsEditor
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_core import RehuDocument, current_block_version


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


def test_build_document_form_leads_with_type_then_location_then_the_record_fields(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """build_document_form leads the main editor tab with the editor-only ``type`` selector, then
    ``location``, then the record fields in declaration order, and puts the Markdown ``description`` on
    its own editor tab.

    **Test steps:**

    * build the document form's editor grids for the model
    * verify the main editor tab leads with ``Type`` then ``Location`` then the configured rows in order
    * verify the description lands on its own editor tab
    """
    grids = build_document_form(model, NameSuggestionModel(model)).make_editor(model)
    main = grids[EDITOR_MAIN_TAB]
    description = grids[EDITOR_DESCRIPTION_TAB]
    qtbot.addWidget(main)
    qtbot.addWidget(description)

    assert form_labels(main) == [
        "Type",
        "Location",
        "Title",
        "Authors",
        "Released",
        "Publisher",
        "Collections",
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
        "Learning Paths",
    ]
    # the description editor carries no row label -- its own dock tab ("Description") already names it
    assert not form_labels(description)


def test_build_document_form_puts_the_record_list_rows_where_tc4_had_them(qtbot: QtBot) -> None:
    """The two record lists sit where tc4's layout had them ([[field-schema#tc4-viewer-layout]], #189):
    ``collections`` in the header group after the publisher, ``learning_paths`` last, after the tag
    lists.

    **Test steps:**

    * build the viewer over a model carrying a collection and an owned learning path
    * verify each row sits where tc4 put it and renders ``Title [index]``
    """
    model = RehuDocumentModel(
        RehuDocument(
            {
                "type": "Tutorial",
                "tutorial": {
                    "collections": [{"title": "Sculpting Series", "index": 2}],
                    "users": {"admin": {"learning_paths": [{"title": "My Order", "index": 7, "ref": 1}]}},
                },
            }
        )
    )
    viewer = build_document_form(model, NameSuggestionModel(model)).make_viewer(model)[VIEWER_TAB]
    qtbot.addWidget(viewer)

    labels = form_labels(viewer)
    assert labels[labels.index("Collections") - 1] == "Publisher"
    assert labels[labels.index("Learning Paths") - 1] == "Extra Tags"
    texts = {label.text() for label in viewer.findChildren(QLabel)}
    assert "Sculpting Series [2]" in texts
    assert "My Order [7]" in texts


def test_build_document_form_trails_unknown_fields_after_the_record_fields(qtbot: QtBot) -> None:
    """A live-block key the model doesn't recognize is composed as a trailing `UnknownField`.

    **Test steps:**

    * build the form over a model whose Tutorial block carries an unrecognized ``mystery`` key
    * verify the main editor's last row is the unknown field, after the last record field
      (``Learning Paths``)
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "tutorial": {"mystery": 1}}))
    main = build_document_form(model, NameSuggestionModel(model)).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(main)

    labels = form_labels(main)
    assert labels[-2:] == ["Learning Paths", "Mystery"]


def test_build_document_form_hands_the_learning_paths_editor_the_document_and_settings_identities(
    qtbot: QtBot,
) -> None:
    """The table edits as the identity the document was **opened** under, and reparents a deleted-but-
    subscribed path to the **configured** unknown identity -- ``unknown`` is a setting, not a reserved
    name ([[field-schema#learning-path-ownership]], #235).

    **Test steps:**

    * configure a non-default unknown identity, and open a document as ``curator``
    * build the editor over ``curator``'s subscribed-to path, and delete it
    * verify the record moved to the configured identity, its slot and subscriber untouched
    """
    shared_identity_settings().unknown_username = "orphaned"
    model = RehuDocumentModel(
        RehuDocument(
            {
                "type": "Tutorial",
                # stamped current: an unversioned block would run the ref-minting migration on load,
                # renumbering the very subscription this test needs left alone
                "tutorial": {
                    "format_version": current_block_version("tutorial"),
                    "users": {
                        "curator": {"learning_paths": [{"title": "Mine", "index": 1, "ref": 1}]},
                        "foo": {"learning_paths": [{"ref": 1}]},
                    },
                },
            },
            username="curator",
        )
    )
    main = build_document_form(model, NameSuggestionModel(model)).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(main)
    editor = main.findChild(LearningPathsEditor)
    assert editor is not None
    table_model = editor.model
    assert isinstance(table_model, LearningPathsTableModel)

    # the one row is ``curator``'s own -- deletable exactly because the form bound the document's identity
    table_model.delete(0)

    assert model.learning_paths == {
        "orphaned": [{"title": "Mine", "index": 1, "ref": 1}],
        "foo": [{"ref": 1}],
    }
