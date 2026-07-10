"""Tests for TextListField: deduplicated comma-joined viewer, tag-entry editor, and the echo guard."""

from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.text_list_field import TextListField


def test_text_list_field_viewer_shows_and_tracks_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the comma-joined list and re-renders when the model changes.

    **Test steps:**

    * build an ``authors`` viewer over a model seeded empty
    * verify the label starts empty
    * set ``model.authors`` and verify the label joins it, comma-separated
    """
    field = TextListField("authors")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.wordWrap() is True
    assert viewer.text() == ""

    model.authors = ["Alice", "Bob"]
    assert viewer.text() == "Alice, Bob"


def test_text_list_field_viewer_deduplicates_for_display(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer deduplicates, order-preserving, without mutating the underlying value (§17.4).

    **Test steps:**

    * set a model list with a repeated entry
    * build the viewer over it
    * verify the label shows each entry once, in first-seen order
    """
    model.authors = ["Alice", "Bob", "Alice"]
    field = TextListField("authors")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.text() == "Alice, Bob"
    assert model.authors == ["Alice", "Bob", "Alice"]


def test_text_list_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Typing comma-separated text in the editor writes the parsed, trimmed list through to the model.

    **Test steps:**

    * build the ``authors`` editor (a single ``QLineEdit``)
    * type ``"Alice, Bob , "``
    * verify ``model.authors`` holds the trimmed list, dropping the trailing empty entry
    """
    field = TextListField("authors")
    # pylint: disable=duplicate-code
    editors = field.make_editors(model.bind(field))
    assert len(editors) == 1
    line_edit = editors[0]
    qtbot.addWidget(line_edit)
    assert isinstance(line_edit, QLineEdit)
    # pylint: enable=duplicate-code

    line_edit.setText("Alice, Bob , ")
    assert model.authors == ["Alice", "Bob"]


def test_text_list_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same ``authors`` field and model
    * type in the editor
    * verify the viewer reflects it and the editor still holds the typed text once (no echo loop)
    """
    field = TextListField("authors")
    # pylint: disable=duplicate-code
    editor = field.make_editors(model.bind(field))[0]
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    assert isinstance(editor, QLineEdit)
    assert isinstance(viewer, QLabel)
    # pylint: enable=duplicate-code

    editor.setText("Alice, Bob")

    assert model.authors == ["Alice", "Bob"]
    assert viewer.text() == "Alice, Bob"
    assert editor.text() == "Alice, Bob"


def test_text_list_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the ``authors`` editor
    * change ``model.authors`` directly (as another surface would)
    * verify the editor text follows, comma-joined
    """
    field = TextListField("authors")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QLineEdit)

    model.authors = ["Carol", "Dave"]
    assert editor.text() == "Carol, Dave"


def test_text_list_field_editor_preserves_the_cursor_when_typing_mid_string(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Typing in the middle of the text doesn't teleport the cursor to the end (echo guard, cf. #35).

    **Test steps:**

    * build the ``authors`` editor and seed it with a two-name value
    * place the cursor mid-string and type one character there
    * verify the character landed at the cursor and the cursor advanced by one (not to the end)
    """
    field = TextListField("authors")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, QLineEdit)
    editor.setText("Alice, Bob")
    editor.setCursorPosition(5)

    qtbot.keyClicks(editor, "x")

    assert editor.text() == "Alicex, Bob"
    assert editor.cursorPosition() == 6
