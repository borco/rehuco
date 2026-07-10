"""Tests for MultipleChoiceField: the comma-joined viewer, the checkbox editor, and the live binding."""

from PySide6.QtWidgets import QCheckBox, QLabel, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.multiple_choice_field import MultipleChoiceField

CHOICES = ("beginner", "intermediate", "advanced", "any")


def test_multiple_choice_field_viewer_shows_and_tracks_selected_values(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer joins the selected values, in ``choices`` order, and re-renders live.

    **Test steps:**

    * build a ``level`` viewer over a model seeded with two out-of-order values
    * verify the label joins them in ``choices`` order
    * change ``model.level`` and verify the label follows
    """
    model.level = ["advanced", "beginner"]
    field = MultipleChoiceField("level", choices=CHOICES)
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.wordWrap() is True
    assert viewer.text() == "beginner, advanced"

    model.level = ["any"]
    assert viewer.text() == "any"


def test_multiple_choice_field_viewer_shows_nothing_when_empty(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An empty selection renders an empty label.

    **Test steps:**

    * build the viewer over a model seeded with no ``level`` values
    * verify the label is empty
    """
    field = MultipleChoiceField("level", choices=CHOICES)
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, QLabel)
    assert viewer.text() == ""


def test_multiple_choice_field_editor_has_one_checkbox_per_choice(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor holds one checkbox per ``choices`` entry, checked from the model's current selection.

    **Test steps:**

    * seed ``model.level`` with one of four choices
    * build the editor and verify it returns a single container with four checkboxes
    * verify only the seeded choice's checkbox starts checked
    """
    model.level = ["intermediate"]
    field = MultipleChoiceField("level", choices=CHOICES)
    editors = field.make_editors(model.bind(field))
    assert len(editors) == 1
    container = editors[0]
    qtbot.addWidget(container)
    assert isinstance(container, QWidget)

    checkboxes = container.findChildren(QCheckBox)
    assert len(checkboxes) == 4
    checked = {checkbox.text() for checkbox in checkboxes if checkbox.isChecked()}
    assert checked == {"intermediate"}


def test_multiple_choice_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Checking/unchecking boxes writes the updated selection through to the model, in ``choices`` order.

    **Test steps:**

    * build the editor over an empty ``level``
    * check ``advanced`` then ``beginner``
    * verify ``model.level`` holds both, ordered by ``choices`` rather than click order
    * uncheck ``advanced`` and verify it drops out
    """
    field = MultipleChoiceField("level", choices=CHOICES)
    container = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(container)
    checkboxes = {checkbox.text(): checkbox for checkbox in container.findChildren(QCheckBox)}

    checkboxes["advanced"].setChecked(True)
    checkboxes["beginner"].setChecked(True)
    assert model.level == ["beginner", "advanced"]

    checkboxes["advanced"].setChecked(False)
    assert model.level == ["beginner"]


def test_multiple_choice_field_editor_and_viewer_echo_without_a_feedback_loop(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same ``level`` field and model
    * check one box in the editor
    * verify the viewer reflects it and the checkbox is still checked (no echo loop)
    """
    field = MultipleChoiceField("level", choices=CHOICES)
    binding = model.bind(field)
    container = field.make_editors(binding)[0]
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(container)
    qtbot.addWidget(viewer)
    checkboxes = {checkbox.text(): checkbox for checkbox in container.findChildren(QCheckBox)}

    checkboxes["any"].setChecked(True)

    assert model.level == ["any"]
    assert isinstance(viewer, QLabel)
    assert viewer.text() == "any"
    assert checkboxes["any"].isChecked() is True


def test_multiple_choice_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the checkboxes under the echo guard.

    **Test steps:**

    * build the editor over an empty ``level``
    * set ``model.level`` directly (as another surface would)
    * verify the matching checkboxes follow, and the rest stay unchecked
    """
    field = MultipleChoiceField("level", choices=CHOICES)
    container = field.make_editors(model.bind(field))[0]
    qtbot.addWidget(container)
    checkboxes = {checkbox.text(): checkbox for checkbox in container.findChildren(QCheckBox)}

    model.level = ["beginner", "any"]

    assert checkboxes["beginner"].isChecked() is True
    assert checkboxes["any"].isChecked() is True
    assert checkboxes["intermediate"].isChecked() is False
    assert checkboxes["advanced"].isChecked() is False
