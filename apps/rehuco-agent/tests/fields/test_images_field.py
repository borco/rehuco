"""Tests for ImagesField: the lightbox strip viewer and the curation editor binding."""

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QTreeView
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import ImageSelector, ImageStrip

from fields.field_testers import ImagesFieldTester as ImagesField

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png"), Path("/fake/info02.gif")]
OTHER_PATHS = [Path("/fake/info00.jpg")]


# region Sample classes
class Emitter(QObject):
    """A minimal signal source standing in for a model's ``image_scanner_changed``."""

    changed = Signal(object)


# endregion


def fake_scanner(mocker: MockerFixture, files: list[Path]) -> object:
    """A minimal ``ImageScanner`` stand-in returning a fixed file list.

    :param mocker: pytest-mock fixture.
    :param files: the fixed file list ``.files()`` reports.
    :returns: the stand-in scanner.
    """
    return mocker.Mock(files=mocker.Mock(return_value=files))


def make_field(mocker: MockerFixture, image_scanner_changed: SignalInstance | None = None) -> ImagesField:
    """Build an ``ImagesField`` bound to the fixed :data:`PATHS` screenshot set.

    :param mocker: pytest-mock fixture.
    :param image_scanner_changed: the reactivity signal to pass through, if any.
    :returns: the field, named after the model's ``hidden_images`` binding.
    """
    return ImagesField(
        "hidden_images",
        image_scanner=fake_scanner(mocker, PATHS),  # type: ignore[arg-type]
        image_scanner_changed=image_scanner_changed,
    )


def test_viewer_is_an_image_strip(mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is an ``ImageStrip``.

    **Test steps:**

    * build the viewer over a model
    * verify it is an ``ImageStrip``
    """
    field = make_field(mocker)
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, ImageStrip)
    qtbot.addWidget(viewer)


def test_editor_seeds_the_selector_with_all_images_checked_except_hidden(
    mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor is an ``ImageSelector`` listing every screenshot, unchecking the hidden ones.

    **Test steps:**

    * seed ``model.hidden_images`` with the middle screenshot
    * build the editor
    * verify all three rows exist with only the hidden one unchecked
    """
    model.hidden_images = ["info01.png"]
    field = make_field(mocker)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    view = editor.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    list_model = view.model()
    assert isinstance(list_model, QStandardItemModel)
    assert [list_model.item(row).checkState() for row in range(list_model.rowCount())] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
        Qt.CheckState.Checked,
    ]


def test_editor_toggle_writes_hidden_images_through_to_the_model(
    mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Unchecking a row in the editor writes the new hidden list through to the model.

    **Test steps:**

    * build the editor with nothing hidden
    * uncheck the first row
    * verify ``model.hidden_images`` follows
    """
    field = make_field(mocker)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    view = editor.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    list_model = view.model()
    assert isinstance(list_model, QStandardItemModel)
    list_model.item(0).setCheckState(Qt.CheckState.Unchecked)

    assert model.hidden_images == ["info00.jpg"]


def test_editor_follows_an_external_hidden_images_change(
    mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A hidden-list change from elsewhere reseeds the editor's check states.

    **Test steps:**

    * build the editor with nothing hidden
    * set ``model.hidden_images`` directly (as a revert would)
    * verify the matching row is now unchecked
    """
    field = make_field(mocker)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    model.hidden_images = ["info02.gif"]

    assert editor.hidden_filenames() == ["info02.gif"]


def test_viewer_forwards_image_scanner_changed_to_the_strip(
    mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The viewer strip picks up a scanner swap forwarded through ``image_scanner_changed``.

    **Test steps:**

    * build the viewer wired to an emitter standing in for the model's signal
    * fire the emitter with a scanner reporting a different, smaller file set
    * verify the strip's own scanner is the new one
    """
    emitter = Emitter()
    field = make_field(mocker, emitter.changed)
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, ImageStrip)
    qtbot.addWidget(viewer)

    new_scanner = fake_scanner(mocker, OTHER_PATHS)
    emitter.changed.emit(new_scanner)

    assert viewer.image_scanner is new_scanner


def test_editor_forwards_image_scanner_changed_to_the_selector(
    mocker: MockerFixture, qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor selector picks up a scanner swap forwarded through ``image_scanner_changed``.

    **Test steps:**

    * build the editor wired to an emitter standing in for the model's signal
    * fire the emitter with a scanner reporting a different, smaller file set
    * verify the selector's own scanner is the new one and its rows reflect it
    """
    emitter = Emitter()
    field = make_field(mocker, emitter.changed)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ImageSelector)
    qtbot.addWidget(editor)

    new_scanner = fake_scanner(mocker, OTHER_PATHS)
    emitter.changed.emit(new_scanner)

    assert editor.image_scanner is new_scanner
    view = editor.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    assert view.model().rowCount() == len(OTHER_PATHS)
