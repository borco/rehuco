"""Tests for UnknownField: the provenance-flagged verbatim viewer and the editor's remove action."""

from PySide6.QtWidgets import QLabel, QToolButton, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.unknown_field import PROVENANCE_NEWER_VERSION

from fields.field_testers import UnknownFieldTester as UnknownField


def test_unknown_field_viewer_shows_the_verbatim_value_flagged_by_provenance(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The viewer renders the raw value, flagged (warning property) and provenance-tooltipped.

    **Test steps:**

    * seed an unknown key on the live block and bind an `UnknownField` to it
    * verify the viewer shows the value as text, carries the ``unknown`` flag, and tooltips the provenance
    """
    model.document.set_type_field("mystery", 42)
    field = UnknownField("mystery")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == "42"
    assert viewer.property("unknown") is True
    assert viewer.toolTip() == PROVENANCE_NEWER_VERSION


def test_unknown_field_editor_remove_drops_the_field_and_hides_the_whole_row(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Remove drops the field and hides its whole row on **both** the editor and the viewer.

    The same field instance builds both surfaces, so removing it must hide every widget it placed --
    the editor's label + value + button and the viewer's label + value -- not just the button.

    **Test steps:**

    * seed an unknown key and build both the viewer and the editor from the same field
    * click Remove
    * verify the key is gone, the model is dirty, and every row widget on both surfaces is hidden
    """
    model.document.set_type_field("mystery", 42)
    field = UnknownField(
        "mystery",
        on_remove=lambda: model.remove_unknown_field("mystery"),
        is_present=lambda: "mystery" in model.document.type_fields,
        current_value=lambda: model.document.type_field("mystery"),
    )
    editor = field.make_editor(model.bind(field))
    viewer = field.make_viewer(model.bind(field))
    editor_label, container = editor.label, editor.editor
    viewer_label, viewer_value = viewer.label, viewer.viewer
    assert isinstance(container, QWidget)
    qtbot.addWidget(container)
    remove = container.findChild(QToolButton)
    assert isinstance(remove, QToolButton)

    remove.click()

    assert "mystery" not in model.document.type_fields
    assert model.dirty is True
    assert container.isHidden() is True
    assert editor_label is not None and editor_label.isHidden() is True
    assert viewer_label is not None and viewer_label.isHidden() is True
    assert viewer_value is not None and viewer_value.isHidden() is True


def test_unknown_field_reappears_with_its_value_when_the_block_restores_it(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A reactive field re-shows both rows, with the value re-read, once the key is restored (a revert).

    **Test steps:**

    * build a reactive editor + viewer and remove the field (both rows hide)
    * restore the key in the document and fire ``unknown_fields_changed`` (what ``revert`` does)
    * verify both rows are visible again and the value labels show the restored value
    """
    model.document.set_type_field("mystery", 42)
    field = UnknownField(
        "mystery",
        on_remove=lambda: model.remove_unknown_field("mystery"),
        is_present=lambda: "mystery" in model.document.type_fields,
        current_value=lambda: model.document.type_field("mystery"),
    )
    container = field.make_editor(model.bind(field)).editor
    viewer_value = field.make_viewer(model.bind(field)).viewer
    assert isinstance(container, QWidget)
    assert isinstance(viewer_value, QLabel)
    qtbot.addWidget(container)
    qtbot.addWidget(viewer_value)
    remove = container.findChild(QToolButton)
    assert isinstance(remove, QToolButton)
    remove.click()
    assert container.isHidden() is True

    model.document.set_type_field("mystery", 99)
    model.unknown_fields_changed.emit()

    assert container.isHidden() is False
    assert viewer_value.isHidden() is False
    assert viewer_value.text() == "99"


def test_unknown_field_editor_without_on_remove_has_no_remove_button(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A viewer-only `UnknownField` (no ``on_remove``) builds an editor row with no remove button.

    **Test steps:**

    * seed an unknown key and build the editor with no ``on_remove``
    * verify the row still shows the value but offers no remove button
    """
    model.document.set_type_field("mystery", 42)
    field = UnknownField("mystery")
    container = field.make_editor(model.bind(field)).editor
    assert isinstance(container, QWidget)
    qtbot.addWidget(container)

    assert container.findChild(QToolButton) is None
    label = container.findChild(QLabel)
    assert isinstance(label, QLabel)
    assert label.text() == "42"
