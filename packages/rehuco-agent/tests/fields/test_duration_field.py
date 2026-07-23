"""Tests for DurationField: the formatted viewer and the DurationEdit-backed editor binding."""

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import DurationEdit

from fields.field_testers import DurationFieldTester as DurationField


def test_duration_field_viewer_shows_and_tracks_the_formatted_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the formatted duration and re-renders when the model changes.

    **Test steps:**

    * build an ``original_duration`` viewer over a model seeded ``0``
    * verify the label starts empty
    * change ``model.original_duration`` and verify the label updates live, formatted
    """
    field = DurationField("original_duration")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.original_duration = 8100
    assert viewer.text() == "2h 15m"


def test_duration_field_editor_is_a_duration_edit_seeded_from_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor is a ``DurationEdit`` seeded with the model's current value.

    **Test steps:**

    * seed the model with a duration, then build the ``original_duration`` editor
    * verify the editor is a ``DurationEdit`` already holding that value
    """
    model.original_duration = 5400
    field = DurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DurationEdit)
    qtbot.addWidget(editor)

    assert editor.value == 5400


def test_duration_field_editor_writes_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Changing the editor's value writes through to the model.

    **Test steps:**

    * build the editor
    * set the editor's ``value``
    * verify ``model.original_duration`` follows
    """
    field = DurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DurationEdit)
    qtbot.addWidget(editor)

    editor.value = 3600

    assert model.original_duration == 3600


def test_duration_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor.

    **Test steps:**

    * build the editor
    * change ``model.original_duration`` directly (as another surface would)
    * verify the editor's ``value`` follows
    """
    field = DurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DurationEdit)
    qtbot.addWidget(editor)

    model.original_duration = 120

    assert editor.value == 120


def test_duration_field_editor_and_viewer_stay_live_together(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``original_duration`` field and model
    * set the editor's value
    * verify the viewer reflects it, formatted
    """
    field = DurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, DurationEdit)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.value = 5400

    assert model.original_duration == 5400
    assert viewer.text() == "1h 30m"
