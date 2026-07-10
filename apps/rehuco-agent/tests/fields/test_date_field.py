"""Tests for DateField: the stored-string viewer and the DateEdit-backed editor binding."""

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import DateEdit

from fields.field_testers import DateFieldTester as DateField


def test_date_field_viewer_shows_and_tracks_the_stored_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the stored ISO-prefix string as-is and re-renders on a model change.

    **Test steps:**

    * build a ``released`` viewer over a model seeded empty
    * verify the label starts empty
    * change ``model.released`` and verify the label updates live
    """
    field = DateField("released")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.released = "2025-03"
    assert viewer.text() == "2025-03"


def test_date_field_editor_is_a_date_edit_seeded_from_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor is a ``DateEdit`` seeded with the model's current value.

    **Test steps:**

    * seed the model with a date, then build the ``released`` editor
    * verify the editor is a ``DateEdit`` already holding that value
    """
    model.released = "2025-03"
    field = DateField("released")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DateEdit)
    qtbot.addWidget(editor)

    assert editor.value == "2025-03"


def test_date_field_editor_writes_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Changing the editor's value writes through to the model.

    **Test steps:**

    * build the editor
    * set the editor's ``value``
    * verify ``model.released`` follows
    """
    field = DateField("released")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DateEdit)
    qtbot.addWidget(editor)

    editor.value = "2026-10-20"

    assert model.released == "2026-10-20"


def test_date_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor.

    **Test steps:**

    * build the editor
    * change ``model.released`` directly (as another surface would)
    * verify the editor's ``value`` follows
    """
    field = DateField("released")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, DateEdit)
    qtbot.addWidget(editor)

    model.released = "2025-03-08"

    assert editor.value == "2025-03-08"


def test_date_field_editor_and_viewer_stay_live_together(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``released`` field and model
    * set the editor's value
    * verify the viewer reflects it
    """
    field = DateField("released")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, DateEdit)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.value = "2026"

    assert model.released == "2026"
    assert viewer.text() == "2026"
