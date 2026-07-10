"""Tests for BooleanField: Yes/No viewer, the ``complete`` warning colour, and the live editor binding."""

from PySide6.QtWidgets import QCheckBox, QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from fields.field_testers import BooleanFieldTester as BooleanField


def test_boolean_field_viewer_shows_and_tracks_yes_no(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows Yes/No and re-renders when the model changes.

    **Test steps:**

    * build an ``online`` viewer over a model seeded ``False``
    * verify the label starts at ``"No"``
    * flip ``model.online`` and verify the label updates live to ``"Yes"``
    """
    field = BooleanField("online")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == "No"

    model.online = True
    assert viewer.text() == "Yes"


def test_complete_viewer_warns_only_when_false(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The ``complete`` viewer flags the warning state when false, and clears it when true (§17.4).

    **Test steps:**

    * build a ``complete`` viewer over a model seeded ``True`` (its import default)
    * verify it starts unflagged, then flips to warning when ``complete`` goes false, and back
    """
    field = BooleanField("complete")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.property("warning") is False

    model.complete = False
    assert viewer.property("warning") is True

    model.complete = True
    assert viewer.property("warning") is False


def test_non_warning_viewer_never_flags_warning(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A non-``complete`` boolean viewer never enters the warning state, even when false.

    **Test steps:**

    * build a ``keep`` viewer (not a warning field) over a model seeded ``False``
    * verify it is unflagged, and stays unflagged when toggled true then false
    """
    field = BooleanField("keep")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.property("warning") is False
    model.keep = True
    assert viewer.property("warning") is False
    model.keep = False
    assert viewer.property("warning") is False


def test_boolean_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Toggling the checkbox writes through to the model.

    **Test steps:**

    * build the ``complete`` editor (a ``QCheckBox``), seeded checked from the model
    * uncheck it and verify ``model.complete`` follows
    """
    field = BooleanField("complete")
    checkbox = field.make_editor(model.bind(field)).editor
    assert isinstance(checkbox, QCheckBox)
    qtbot.addWidget(checkbox)
    assert checkbox.isChecked() is True

    checkbox.setChecked(False)
    assert model.complete is False


def test_boolean_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``favorite`` field and model
    * toggle the editor on
    * verify the viewer reflects it and the editor still holds the value once (no echo loop)
    """
    field = BooleanField("favorite")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, QCheckBox)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.setChecked(True)

    assert model.favorite is True
    assert viewer.text() == "Yes"
    assert editor.isChecked() is True


def test_boolean_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the ``complete`` editor (seeded checked)
    * set ``model.complete`` false directly (as another surface would)
    * verify the checkbox follows
    """
    field = BooleanField("complete")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QCheckBox)
    qtbot.addWidget(editor)

    model.complete = False
    assert editor.isChecked() is False
