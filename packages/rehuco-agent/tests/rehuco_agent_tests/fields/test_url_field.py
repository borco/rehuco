"""Tests for UrlField: the elided hyperlink viewer, the line-edit editor, and the live binding."""

from borco_pyside.widgets import ElidedLabel
from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import FieldsTab
from rehuco_agent.settings.record_url_settings import RecordUrlSettings

from rehuco_agent_tests.fields.field_testers import TEST_VIEWER_TAB
from rehuco_agent_tests.fields.field_testers import UrlFieldTester as UrlField

DESCRIPTION_TAB = FieldsTab("Description", ":/icons/document_viewer_description.svg")


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
    assert viewer.text().startswith('<a href="https://example.com" style="color:')
    assert viewer.text().endswith(">https://example.com</a>")

    model.url = "https://changed.example"
    assert viewer.text().startswith('<a href="https://changed.example" style="color:')
    assert viewer.text().endswith(">https://changed.example</a>")


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
    assert viewer.text().startswith('<a href="https://live.example" style="color:')
    assert viewer.text().endswith(">https://live.example</a>")
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


def test_url_field_draws_one_row_without_a_second_tab(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no ``description_tab`` the field is the single row it always was.

    **Test steps:**

    * build the viewer rows of a field given no second tab
    * verify there is one, on the field's own tab
    """
    field = UrlField("url")

    rows = field.make_viewer_rows([model.bind(field)])

    assert [row.tab for row in rows] == [TEST_VIEWER_TAB]
    for row in rows:
        qtbot.addWidget(row.viewer)


def test_url_field_draws_a_row_on_each_tab_and_both_follow_the_url(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Given a ``description_tab`` the field draws the url on both surfaces, each a link of its own.

    **Test steps:**

    * build the viewer rows of a field given a description tab
    * verify the main tab's row comes first and the description tab's second, with no label of its own
    * change ``model.url`` and verify both links follow
    """
    field = UrlField("url", description_tab=DESCRIPTION_TAB)

    rows = field.make_viewer_rows([model.bind(field)])
    assert len(rows) == 2
    main, description = rows[0], rows[1]
    for row in (main, description):
        assert isinstance(row.viewer, ElidedLabel)
        qtbot.addWidget(row.viewer)

    assert (main.tab, description.tab) == (TEST_VIEWER_TAB, DESCRIPTION_TAB)
    assert main.viewer is not description.viewer
    assert main.label is not None and description.label is None
    assert (main.vertical, description.vertical) == (False, True)
    model.url = "https://changed.example"
    for row in (main, description):
        assert isinstance(row.viewer, ElidedLabel)
        assert ">https://changed.example</a>" in row.viewer.text()


def test_url_field_hides_a_placement_that_starts_off(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A placement whose setting starts off is built hidden -- label and link -- the other shown.

    **Test steps:**

    * build both rows with the Main View off
    * parent them to a shown widget
    * verify the main row's label and link are hidden and the description row's shown
    """
    field = UrlField("url", description_tab=DESCRIPTION_TAB, main_visible=False)
    rows = field.make_viewer_rows([model.bind(field)])
    assert len(rows) == 2
    main, description = rows[0], rows[1]
    host = QLabel()
    qtbot.addWidget(host)
    for widget in (main.label, main.viewer, description.viewer):
        assert widget is not None
        widget.setParent(host)
    host.show()

    assert main.label is not None and main.viewer is not None and description.viewer is not None
    assert (main.label.isVisible(), main.viewer.isVisible()) == (False, False)
    assert description.viewer.isVisible() is True


def test_url_field_placements_follow_their_settings_live(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Each placement shows and hides with its own setting, the other untouched, with no rebuild.

    **Test steps:**

    * build both rows over a `RecordUrlSettings`' values and signals, in a shown host
    * turn the Main View off, then on, and verify only the main row follows
    * turn the Description View off, then on, and verify only the description row follows
    """
    settings = RecordUrlSettings()
    field = UrlField(
        "url",
        description_tab=DESCRIPTION_TAB,
        main_visible=settings.show_on_main_view,
        main_visible_changed=settings.show_on_main_view_changed,  # type: ignore[attr-defined]
        description_visible=settings.show_on_description_view,
        description_visible_changed=settings.show_on_description_view_changed,  # type: ignore[attr-defined]
    )
    rows = field.make_viewer_rows([model.bind(field)])
    assert len(rows) == 2
    main, description = rows[0], rows[1]
    host = QLabel()
    qtbot.addWidget(host)
    for widget in (main.label, main.viewer, description.viewer):
        assert widget is not None
        widget.setParent(host)
    host.show()
    main_label, main_link, description_link = main.label, main.viewer, description.viewer
    assert main_label is not None and main_link is not None and description_link is not None

    def shown() -> tuple[bool, bool]:
        return main_link.isVisible() and main_label.isVisible(), description_link.isVisible()

    assert shown() == (True, True)
    settings.show_on_main_view = False
    assert shown() == (False, True)
    settings.show_on_main_view = True
    assert shown() == (True, True)
    settings.show_on_description_view = False
    assert shown() == (True, False)
    settings.show_on_description_view = True
    assert shown() == (True, True)
