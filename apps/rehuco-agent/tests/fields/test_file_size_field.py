"""Tests for FileSizeField: the formatted viewer and the FileSizeEdit-backed editor binding."""

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.file_size_field import FileSizeField
from rehuco_agent.fields.widgets import FileSizeEdit


def test_file_size_field_viewer_shows_and_tracks_the_formatted_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the formatted size and re-renders when the model changes.

    **Test steps:**

    * build an ``original_size`` viewer over a model seeded ``0``
    * verify the label starts empty
    * change ``model.original_size`` and verify the label updates live, formatted
    """
    field = FileSizeField("original_size")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.text() == ""

    model.original_size = 5368709120
    assert viewer.text() == "5.0G"


def test_file_size_field_editor_is_a_file_size_edit_seeded_from_the_model(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """``make_editors`` returns exactly one ``FileSizeEdit``, seeded with the model's current value.

    **Test steps:**

    * seed the model with a size, then build the ``original_size`` editor
    * verify there is exactly one editor, a ``FileSizeEdit``, already holding that value
    """
    model.original_size = 5368709120
    field = FileSizeField("original_size")
    editors = field.make_editors(model.bind(field))
    qtbot.addWidget(editors[0])

    assert len(editors) == 1
    assert isinstance(editors[0], FileSizeEdit)
    assert editors[0].value == 5368709120


def test_file_size_field_editor_writes_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Changing the editor's value writes through to the model.

    **Test steps:**

    * build the editor
    * set the editor's ``value``
    * verify ``model.original_size`` follows
    """
    field = FileSizeField("original_size")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, FileSizeEdit)

    editor.value = 1073741824

    assert model.original_size == 1073741824


def test_file_size_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor.

    **Test steps:**

    * build the editor
    * change ``model.original_size`` directly (as another surface would)
    * verify the editor's ``value`` follows
    """
    field = FileSizeField("original_size")
    editor = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, FileSizeEdit)

    model.original_size = 2048

    assert editor.value == 2048


def test_file_size_field_editor_and_viewer_stay_live_together(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``original_size`` field and model
    * set the editor's value
    * verify the viewer reflects it, formatted
    """
    field = FileSizeField("original_size")
    editor = field.make_editors(model.bind(field))[0]
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    assert isinstance(editor, FileSizeEdit)
    assert isinstance(viewer, QLabel)

    editor.value = 1073741824

    assert model.original_size == 1073741824
    assert viewer.text() == "1.0G"
