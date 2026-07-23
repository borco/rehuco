"""Tests for TypeField: the type combo editor, the colored viewer badge, and their live binding (#83)."""

from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.type_field import NO_TYPE_LABEL
from rehuco_agent.fields.widgets import SingleChoiceComboBox, TypeBadge

from fields.field_testers import TypeFieldTester as TypeField

CHOICES = ("", "tutorial", "reference_images")
COLORS = {"tutorial": "#111111", "reference_images": "#222222"}


def colors_for(type_key: str) -> tuple[str | None, str | None]:
    """A test type-to-``(background, text)`` resolver; background from the map, text left to the palette."""
    return COLORS.get(type_key), None


def test_type_field_without_a_color_resolver_builds_no_viewer(model: RehuDocumentModel) -> None:
    """With no ``colors_for``, the type field is **editor-only** -- its viewer bundle is all-``None`` so
    the assembler drops it.

    **Test steps:**

    * build a type field with no color resolver, then its viewer bundle
    * verify it contributes no label and no viewer widget
    """
    field = TypeField("resource_type", "Type", CHOICES)
    bundle = field.make_viewer(model.bind(field))

    assert bundle.label is None
    assert bundle.viewer is None


def test_type_field_viewer_shows_a_colored_badge_of_the_current_type(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With a ``colors_for``, the viewer shows a right-aligned badge painted with the plugin's color and
    labelled with the current type ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * seed the model's type and build the badge viewer over a color resolver
    * verify the badge shows the title-cased type and carries the resolved color in its stylesheet
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES, colors_for)
    container = field.make_viewer(model.bind(field)).viewer
    assert container is not None
    qtbot.addWidget(container)

    badge = container.findChild(TypeBadge)
    assert badge is not None
    assert badge.text() == "Tutorial"
    assert "#111111" in badge.styleSheet()


def test_type_field_viewer_badge_follows_a_type_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer badge re-labels and re-colors live when the type changes ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build the badge viewer over a tutorial model
    * switch the model's type
    * verify the badge follows -- new label and new color
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES, colors_for)
    container = field.make_viewer(model.bind(field)).viewer
    assert container is not None
    qtbot.addWidget(container)
    badge = container.findChild(TypeBadge)
    assert badge is not None

    model.resource_type = "reference_images"
    assert badge.text() == "Reference Images"
    assert "#222222" in badge.styleSheet()


def test_type_field_viewer_badge_is_hidden_for_an_empty_type(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A type-less document shows no badge -- the badge hides itself ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * switch the model to the empty type, then build the badge viewer
    * verify the badge is hidden
    """
    model.resource_type = ""
    field = TypeField("resource_type", "Type", CHOICES, colors_for)
    container = field.make_viewer(model.bind(field)).viewer
    assert container is not None
    qtbot.addWidget(container)

    badge = container.findChild(TypeBadge)
    assert badge is not None
    assert badge.isHidden()


def test_type_field_editor_is_a_combo_of_the_offered_types_seeded_from_the_model(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor is a combo listing the offered types, labels title-cased (the empty type shown as the
    placeholder), seeded to the model's current type.

    **Test steps:**

    * seed the model's type
    * build the editor over the offered choices
    * verify the items carry the type keys with readable labels, and the current selection is the model's type
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceComboBox)
    qtbot.addWidget(editor)

    assert [editor.itemData(i) for i in range(editor.count())] == ["", "tutorial", "reference_images"]
    assert [editor.itemText(i) for i in range(editor.count())] == [NO_TYPE_LABEL, "Tutorial", "Reference Images"]
    assert editor.value == "tutorial"


def test_choosing_a_type_switches_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Selecting a type in the combo drives the model's ``resource_type`` -- the switch that arms the
    block persistence invariant ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build the editor over a tutorial model
    * select ``reference_images`` in the combo
    * verify the model's type followed and the model is now dirty
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceComboBox)
    qtbot.addWidget(editor)

    editor.setCurrentIndex(editor.findData("reference_images"))

    assert model.resource_type == "reference_images"
    assert model.dirty is True


def test_editor_follows_an_external_type_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A type change from elsewhere updates the combo under the echo guard (live "both").

    **Test steps:**

    * build the editor over a tutorial model
    * set ``model.resource_type`` directly (as another surface would)
    * verify the combo's selection follows
    """
    model.resource_type = "tutorial"
    field = TypeField("resource_type", "Type", CHOICES)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SingleChoiceComboBox)
    qtbot.addWidget(editor)

    model.resource_type = "reference_images"

    assert editor.value == "reference_images"
