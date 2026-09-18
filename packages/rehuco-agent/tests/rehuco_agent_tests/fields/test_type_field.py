"""Tests for TypeField: the type radio-group editor (#83, #309, #310)."""

from PySide6.QtWidgets import QRadioButton
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.type_field import NO_TYPE_LABEL
from rehuco_agent.fields.widgets import SingleChoiceRadioButtons

from rehuco_agent_tests.fields.field_testers import TypeFieldTester as TypeField

CHOICES = ("", "tutorial", "reference_images")


def buttons(editor: SingleChoiceRadioButtons) -> dict[str, QRadioButton]:
    """The editor's radio buttons keyed by their label.

    :param editor: the editor to inspect.
    :returns: a ``label -> QRadioButton`` map.
    """
    return {button.text(): button for button in editor.findChildren(QRadioButton)}


def test_type_field_builds_no_viewer(model: RehuDocumentModel) -> None:
    """`TypeField` is editor-only (#309): its viewer bundle is all-``None`` so the assembler drops it --
    the colored badge it used to show now lives on `DocumentWidget`'s own toolbar, driven from the model
    directly.

    **Test steps:**

    * build a type field, then its viewer bundle
    * verify it contributes no label and no viewer widget
    """
    field = TypeField("resource_type", "Type", CHOICES)
    bundle = field.make_viewer(model.bind(field))

    assert bundle.label is None
    assert bundle.viewer is None


def test_type_field_editor_is_a_radio_group_of_the_offered_types_seeded_from_the_model(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor is a radio group over the offered types, labels title-cased (the empty type shown as
    the placeholder), seeded to the model's current type.

    **Test steps:**

    * seed the model's type
    * build the editor over the offered choices
    * verify one button per type with readable labels, all enabled, and the checked one is the model's type
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceRadioButtons)
    qtbot.addWidget(editor)

    group = buttons(editor)
    assert set(group) == {NO_TYPE_LABEL, "Tutorial", "Reference Images"}
    assert all(button.isEnabled() for button in group.values())
    assert group["Tutorial"].isChecked() is True
    assert editor.value == "tutorial"


def test_choosing_a_type_switches_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Checking a button in the radio group drives the model's ``resource_type`` -- the switch that
    arms the block persistence invariant ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build the editor over a tutorial model
    * check ``reference_images``'s button
    * verify the model's type followed and the model is now dirty
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceRadioButtons)
    qtbot.addWidget(editor)

    buttons(editor)["Reference Images"].setChecked(True)

    assert model.resource_type == "reference_images"
    assert model.dirty is True


def test_editor_follows_an_external_type_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A type change from elsewhere updates the radio group under the echo guard (live "both").

    **Test steps:**

    * build the editor over a tutorial model
    * set ``model.resource_type`` directly (as another surface would)
    * verify the radio group's checked button follows
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceRadioButtons)
    qtbot.addWidget(editor)

    model.resource_type = "reference_images"

    assert editor.value == "reference_images"


def test_a_type_naming_no_installed_plugin_is_shown_but_disabled(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The current type is still offered, checked, when the caller marks it disabled -- the document's
    type shows in full even when it names no installed plugin, but it is not re-pickable (#310).

    **Test steps:**

    * seed the model to a type outside the field's regular choices
    * build the editor with that type included in the choices and passed as disabled
    * verify its button is checked yet disabled, while the offered choices stay enabled
    """
    model.resource_type = "retired_type"
    field = TypeField("resource_type", "Type", ("retired_type", *CHOICES), ("retired_type",))
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceRadioButtons)
    qtbot.addWidget(editor)

    group = buttons(editor)
    assert group["Retired Type"].isChecked() is True
    assert group["Retired Type"].isEnabled() is False
    assert group["Tutorial"].isEnabled() is True
