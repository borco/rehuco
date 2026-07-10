"""Tests for ImagesField: the lightbox strip viewer and the curation editor binding."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QListView
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import ImageSelector, ImageStrip

from fields.field_testers import ImagesFieldTester as ImagesField

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png"), Path("/fake/info02.gif")]


def make_field() -> ImagesField:
    """Build an ``ImagesField`` bound to the fixed :data:`PATHS` screenshot set.

    :returns: the field, named after the model's ``hidden_images`` binding.
    """
    return ImagesField("hidden_images", image_files=lambda: PATHS)


def test_viewer_is_an_image_strip(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is an ``ImageStrip``.

    **Test steps:**

    * build the viewer over a model
    * verify it is an ``ImageStrip``
    """
    field = make_field()
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, ImageStrip)
    qtbot.addWidget(viewer)


def test_editor_seeds_the_selector_with_all_images_checked_except_hidden(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor is an ``ImageSelector`` listing every screenshot, unchecking the hidden ones.

    **Test steps:**

    * seed ``model.hidden_images`` with the middle screenshot
    * build the editor
    * verify all three rows exist with only the hidden one unchecked
    """
    model.hidden_images = ["info01.png"]
    field = make_field()
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    view = editor.findChild(QListView)
    assert isinstance(view, QListView)
    list_model = view.model()
    assert isinstance(list_model, QStandardItemModel)
    assert [list_model.item(row).checkState() for row in range(list_model.rowCount())] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
        Qt.CheckState.Checked,
    ]


def test_editor_toggle_writes_hidden_images_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Unchecking a row in the editor writes the new hidden list through to the model.

    **Test steps:**

    * build the editor with nothing hidden
    * uncheck the first row
    * verify ``model.hidden_images`` follows
    """
    field = make_field()
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    view = editor.findChild(QListView)
    assert isinstance(view, QListView)
    list_model = view.model()
    assert isinstance(list_model, QStandardItemModel)
    list_model.item(0).setCheckState(Qt.CheckState.Unchecked)

    assert model.hidden_images == ["info00.jpg"]


def test_editor_follows_an_external_hidden_images_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A hidden-list change from elsewhere reseeds the editor's check states.

    **Test steps:**

    * build the editor with nothing hidden
    * set ``model.hidden_images`` directly (as a revert would)
    * verify the matching row is now unchecked
    """
    field = make_field()
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    model.hidden_images = ["info02.gif"]

    assert editor.hidden_filenames() == ["info02.gif"]
