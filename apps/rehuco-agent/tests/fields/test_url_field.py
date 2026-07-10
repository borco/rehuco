"""Tests for UrlField: the elided hyperlink viewer, the line-edit editor, and the live binding."""

from borco_pyside.widgets import ElidedLabel
from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from fields.field_testers import UrlFieldTester as UrlField


def test_url_field_viewer_is_an_elided_external_link(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is an ``ElidedLabel`` external link, rendering the URL and tracking model changes.

    **Test steps:**

    * build a ``url`` viewer over a seeded URL
    * verify it's an ``ElidedLabel`` opening external links, shown as the full hyperlink
    * change ``model.url`` and verify the label follows
    """
    field = UrlField("url")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, ElidedLabel)
    qtbot.addWidget(viewer)

    assert viewer.openExternalLinks() is True
    assert viewer.text() == '<a href="https://example.com">https://example.com</a>'

    model.url = "https://changed.example"
    assert viewer.text() == '<a href="https://changed.example">https://changed.example</a>'


def test_url_field_viewer_renders_nothing_when_empty(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An empty URL renders as an empty label, not an empty link.

    **Test steps:**

    * clear ``model.url``
    * build the viewer over it
    * verify the label text is empty
    """
    model.url = ""
    field = UrlField("url")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""


def test_url_field_viewer_escapes_html_in_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A URL containing HTML-special characters is escaped, not injected as markup.

    **Test steps:**

    * set a URL carrying a ``"`` and a ``<``
    * build the viewer (wide, so it doesn't elide) over it
    * verify the rendered text escapes them
    """
    model.url = 'https://example.com/?a="x"<y>'
    field = UrlField("url")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, ElidedLabel)
    qtbot.addWidget(viewer)

    assert "<y>" not in viewer.text()
    assert "&lt;y&gt;" in viewer.text()


def test_url_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the line edit writes through to the model.

    **Test steps:**

    * build the ``url`` editor (a ``QLineEdit``)
    * set its text and verify ``model.url`` follows
    """
    field = UrlField("url")
    line_edit = field.make_editor(model.bind(field)).editor
    assert isinstance(line_edit, QLineEdit)
    qtbot.addWidget(line_edit)

    line_edit.setText("https://typed.example")
    assert model.url == "https://typed.example"


def test_url_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same ``url`` field and model
    * type in the editor
    * verify the viewer reflects it and the editor still holds the value once (no echo loop)
    """
    field = UrlField("url")
    # pylint: disable=duplicate-code
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, QLineEdit)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    # pylint: enable=duplicate-code

    editor.setText("https://live.example")

    assert model.url == "https://live.example"
    assert viewer.text() == '<a href="https://live.example">https://live.example</a>'
    assert editor.text() == "https://live.example"


def test_url_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the ``url`` editor
    * change ``model.url`` directly (as another surface would)
    * verify the editor text follows
    """
    field = UrlField("url")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)

    model.url = "https://external.example"
    assert editor.text() == "https://external.example"


def test_url_field_editor_preserves_the_cursor_when_typing_mid_string(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Typing in the middle of the text doesn't teleport the cursor to the end (cf. #35).

    **Test steps:**

    * build the ``url`` editor and seed it with a value
    * place the cursor mid-string and type one character there
    * verify the character landed at the cursor and the cursor advanced by one (not to the end)
    """
    field = UrlField("url")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)
    editor.setText("https://example.com")
    editor.setCursorPosition(8)

    qtbot.keyClicks(editor, "x")

    assert editor.text() == "https://xexample.com"
    assert editor.cursorPosition() == 9
