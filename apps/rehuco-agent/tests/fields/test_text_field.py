"""Tests for TextField: label default, and the live viewer/editor binding."""

from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.rehu_document_model import RehuDocumentModel


def test_text_field_viewer_shows_and_tracks_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the initial value and re-renders when the model changes.

    **Test steps:**

    * build a title viewer over a model seeded with ``"Foo"``
    * verify the label starts at ``"Foo"``
    * change ``model.title`` and verify the label updates live (the "both" path)
    """
    field = TextField("title")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.text() == "Foo"

    model.title = "Changed"
    assert viewer.text() == "Changed"


def test_text_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the line edit writes through to the model.

    **Test steps:**

    * build the title editor (a single ``QLineEdit``)
    * set its text and verify ``model.title`` follows
    """
    field = TextField("title")
    editors = field.make_editors(model.bind(field))
    assert len(editors) == 1
    line_edit = editors[0]
    qtbot.addWidget(line_edit)
    assert isinstance(line_edit, QLineEdit)

    line_edit.setText("Typed")
    assert model.title == "Typed"


def test_text_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same model and field
    * type in the editor
    * verify the viewer reflects it and the editor still holds the value once (no echo loop)
    """
    field = TextField("title")
    editor = field.make_editors(model.bind(field))[0]
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    assert isinstance(editor, QLineEdit)
    assert isinstance(viewer, QLabel)

    editor.setText("Live")

    assert model.title == "Live"
    assert viewer.text() == "Live"
    assert editor.text() == "Live"


def test_text_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the title editor
    * change ``model.title`` directly (as another surface would)
    * verify the editor text follows
    """
    field = TextField("title")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QLineEdit)

    model.title = "External"
    assert editor.text() == "External"
