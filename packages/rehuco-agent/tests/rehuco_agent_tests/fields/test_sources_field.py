"""Tests for SourcesField and the ``viewer_only`` text fields: the sources editor bound to the model (#391)."""

from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import SourceCardContent, SourcesEditor

from rehuco_agent_tests.fields.field_testers import SourcesFieldTester as SourcesField
from rehuco_agent_tests.fields.field_testers import TextFieldTester as TextField
from rehuco_agent_tests.fields.field_testers import UrlFieldTester as UrlField


def test_the_sources_field_has_no_viewer(model: RehuDocumentModel) -> None:
    """The viewer keeps its own Title, Publisher and URL rows, so this field is editor-only.

    **Test steps:**

    * build the field's viewer bundle
    * verify it carries neither a label nor a widget, which is what makes the assembler drop the row
    """
    field = SourcesField("sources")

    bundle = field.make_viewer(model.bind(field))

    assert bundle.label is None
    assert bundle.viewer is None


def test_the_sources_editor_is_bound_to_the_models_sources(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor shows the model's sources and writes an edit back to them.

    **Test steps:**

    * build the editor over a model with one source
    * verify the one card shows it
    * type a new title into the card and verify ``model.sources`` and ``model.title`` follow, dirty
    """
    field = SourcesField("sources")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SourcesEditor)
    qtbot.addWidget(editor)
    cards = editor.cards
    content = cards[0].content
    assert isinstance(content, SourceCardContent)
    assert content.title_edit.text() == "Foo"

    content.title_edit.setText("Typed")

    assert model.title == "Typed"
    assert model.sources == [{"title": "Typed", "publisher": "Bar", "url": "https://example.com"}]
    assert model.dirty is True


def test_a_scraped_url_lands_on_the_top_card(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """After ``model.add_source`` fills the primary's URL, the top card shows it.

    **Test steps:**

    * build the editor over a primary that has a publisher and no URL
    * add a source through the model
    * verify the top card's URL edit reads the scraped URL, and there is still one card
    """
    model.url = ""
    field = SourcesField("sources")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SourcesEditor)
    qtbot.addWidget(editor)

    model.add_source("Scraped", "https://scraped.example/page")

    cards = editor.cards
    content = cards[0].content
    assert isinstance(content, SourceCardContent)
    assert content.url_edit.text() == "https://scraped.example/page"
    assert len(editor.cards) == 1


def test_a_viewer_only_text_field_builds_no_editor(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """``viewer_only`` keeps the viewer and drops the editor row, for both text and url.

    **Test steps:**

    * build a viewer-only ``title`` and ``url`` field
    * verify each still builds a viewer, and the title's shows the model's value
    * verify each editor bundle is empty, and that the default still builds a ``QLineEdit``
    """
    title = TextField("title", viewer_only=True)
    viewer = title.make_viewer(model.bind(title)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)
    assert viewer.text() == "Foo"

    url = UrlField("url", viewer_only=True)
    url_viewer = url.make_viewer(model.bind(url)).viewer
    assert url_viewer is not None
    qtbot.addWidget(url_viewer)

    for field in (title, url):
        bundle = field.make_editor(model.bind(field))
        assert bundle.label is None
        assert bundle.editor is None

    default = TextField("title")
    editor = default.make_editor(model.bind(default)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)


def test_the_sources_row_has_no_misc_control(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Every source shows all the time, so the row carries no expand toggle.

    **Test steps:**

    * build the row and verify its bundle has a label and an editor but nothing in the misc column
    """
    field = SourcesField("sources")

    bundle = field.make_editor(model.bind(field))
    assert isinstance(bundle.editor, SourcesEditor)
    qtbot.addWidget(bundle.editor)

    assert bundle.label is not None
    assert bundle.misc is None
