"""Tests for DescriptionField: the Markdown viewer and the ScintillaEdit editor binding."""

from PySide6.QtCore import QObject, Signal
from pyside6_scintilla import ScintillaEdit
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import MarkdownView
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings

from fields.field_testers import DescriptionFieldTester as DescriptionField


# region Sample classes
class Emitter(QObject):
    """A minimal signal source standing in for a model's ``image_scanner_changed``."""

    changed = Signal(object)


# endregion


def editor_text(editor: ScintillaEdit) -> str:
    """Read a `ScintillaEdit`'s full text as a string.

    :param editor: the editor to read.
    :returns: its UTF-8 text.
    """
    return bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")


def test_description_viewer_is_a_markdown_view_tracking_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is a ``MarkdownView`` rendering the description, and re-renders on a model change.

    **Test steps:**

    * seed the model with Markdown and build the viewer
    * verify it's a ``MarkdownView`` showing the text
    * change ``model.description`` and verify the viewer follows
    """
    model.description = "# Title\n\nsome body text"
    field = DescriptionField("description")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, MarkdownView)
    qtbot.addWidget(viewer)

    assert "Title" in viewer.toPlainText()
    assert "body text" in viewer.toPlainText()

    model.description = "changed prose"
    assert "changed prose" in viewer.toPlainText()


def test_description_viewer_follows_live_rendering_settings_changes(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The viewer picks up the shared Markdown-rendering settings' current values whenever they
    change (#26, #47) -- not just when it's first built -- so a Save on the settings page updates
    an already-open document's viewer immediately.

    **Test steps:**

    * build the viewer (default engine)
    * change the shared settings' engine and verify the viewer's own engine followed
    * change the image-width cap and verify the viewer re-renders -- the ``ImageScanner`` reads that
      setting live on the next ``loadResource``, so a re-render (not a value threaded through here)
      is what makes an already-open viewer pick it up
    """
    field = DescriptionField("description")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, MarkdownView)
    qtbot.addWidget(viewer)

    settings = shared_markdown_rendering_settings()
    settings.engine = "mistletoe"
    assert viewer._MarkdownView__engine == "mistletoe"  # type: ignore[attr-defined]  # pylint: disable=protected-access

    set_markdown = mocker.patch.object(viewer, "set_markdown")
    settings.max_image_width = 123
    set_markdown.assert_called_once()


def test_viewer_forwards_image_scanner_changed_to_the_markdown_view(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A scanner swap forwarded through ``image_scanner_changed`` reaches the viewer's own scanner.

    **Test steps:**

    * build the viewer wired to an emitter standing in for the model's signal
    * fire the emitter with a new scanner
    * verify the viewer's own scanner is the new one
    """
    emitter = Emitter()
    field = DescriptionField("description", image_scanner_changed=emitter.changed)
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, MarkdownView)
    qtbot.addWidget(viewer)

    new_scanner = object()
    emitter.changed.emit(new_scanner)

    assert viewer.image_scanner is new_scanner


def test_viewer_without_image_scanner_changed_makes_no_connection(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Omitting ``image_scanner_changed`` builds a viewer with no reactive scanner wiring, without error.

    **Test steps:**

    * build the viewer with no ``image_scanner_changed``
    * verify it builds successfully and its scanner is unset
    """
    field = DescriptionField("description")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, MarkdownView)
    qtbot.addWidget(viewer)

    assert viewer.image_scanner is None


def test_description_editor_is_a_scintilla_seeded_from_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor is a ``ScintillaEdit`` seeded with the model's current description.

    **Test steps:**

    * seed ``model.description`` and build the editor
    * verify it's a ``ScintillaEdit`` holding that text
    """
    model.description = "hello prose"
    field = DescriptionField("description")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ScintillaEdit)
    qtbot.addWidget(editor)

    assert editor_text(editor) == "hello prose"


def test_description_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the ScintillaEdit writes through to the model.

    **Test steps:**

    * build the editor and set its text
    * verify ``model.description`` follows
    """
    field = DescriptionField("description")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ScintillaEdit)
    qtbot.addWidget(editor)

    editor.setText("typed prose")
    assert model.description == "typed prose"


def test_description_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the editor
    * change ``model.description`` directly (as another surface would)
    * verify the editor text follows
    """
    field = DescriptionField("description")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ScintillaEdit)
    qtbot.addWidget(editor)

    model.description = "external prose"
    assert editor_text(editor) == "external prose"


def test_description_editor_and_viewer_stay_live_together(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live (live "both"), across the two docks.

    **Test steps:**

    * build an editor and a viewer over the same ``description`` field and model
    * type in the editor
    * verify the viewer reflects it
    """
    field = DescriptionField("description")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, ScintillaEdit)
    assert isinstance(viewer, MarkdownView)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.setText("live prose")

    assert model.description == "live prose"
    assert "live prose" in viewer.toPlainText()
