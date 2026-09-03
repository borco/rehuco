"""Tests for AuthorsField: the rich-text link viewer, the two-mode editor and its misc-column toggle
(#95, #97), and the scheme-dispatching link handlers."""

import logging

import pytest
from PySide6.QtWidgets import QLabel
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import AuthorsEditor, ExpandToggleButton

from rehuco_agent_tests.fields.field_testers import AuthorsFieldTester as AuthorsField


# region helpers
def build_editor(qtbot: QtBot, model: RehuDocumentModel) -> tuple[AuthorsEditor, ExpandToggleButton]:
    """Build the field's editor row over ``model``.

    :param qtbot: the widget-owning fixture.
    :param model: the view-model to bind to.
    :returns: the editor and the row's misc-column toggle.
    """
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, toggle = widgets.editor, widgets.misc
    assert isinstance(editor, AuthorsEditor)
    assert isinstance(toggle, ExpandToggleButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(toggle)
    return editor, toggle


# endregion


# region viewer
def test_authors_field_viewer_renders_plain_names_with_no_anchors(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A plain-string-only list renders as comma-joined, escaped names -- no ``(url)`` anchor.

    **Test steps:**

    * seed ``model.authors`` with two plain names
    * build the viewer
    * verify the label joins them with no anchor markup
    """
    model.authors = ["Alice", "Bob"]
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == "Alice, Bob"
    assert "<a" not in viewer.text()


def test_authors_field_viewer_renders_an_anchor_for_a_valid_http_url(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A record entry with a strict http/https URL renders a trailing ``(url)`` anchor.

    **Test steps:**

    * seed ``model.authors`` with one ``{name, url}`` record carrying an ``https`` URL
    * build the viewer
    * verify the label shows the escaped name plus the anchor
    """
    model.authors = [{"name": "Alice", "url": "https://example.com/alice"}]
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == 'Alice (<a href="https://example.com/alice">url</a>)'


def test_authors_field_viewer_renders_no_anchor_for_a_non_http_url(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A non-http(s), malformed, or empty URL renders exactly as if no URL were present.

    **Test steps:**

    * seed a record with an ``ftp`` URL, one with an unparseable URL, and one with an empty URL
    * build the viewer
    * verify every entry shows its name only, with no anchor
    """
    model.authors = [
        {"name": "Alice", "url": "ftp://example.com/alice"},
        {"name": "Bob", "url": "not a url"},
        {"name": "Carol", "url": ""},
    ]
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == "Alice, Bob, Carol"


def test_authors_field_viewer_escapes_html_in_a_name(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A name carrying HTML-special characters is escaped, not interpreted
    ([[data-model#write-integrity]]).

    **Test steps:**

    * seed a name carrying ``<``, ``&``, and ``"``
    * build the viewer
    * verify the raw markup never appears and the escaped form does
    """
    model.authors = ['<b>"Alice"</b> & Co']
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert "<b>" not in viewer.text()
    assert "&lt;b&gt;" in viewer.text()
    assert "&amp;" in viewer.text()


def test_authors_field_viewer_tracks_model_changes(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the model's ``authors`` changes.

    **Test steps:**

    * build the viewer over a plain-name seed
    * change ``model.authors`` to a mixed plain/record list
    * verify the label follows
    """
    model.authors = ["Alice"]
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    model.authors = ["Bob", {"name": "Carol", "url": "https://example.com"}]
    assert viewer.text() == 'Bob, Carol (<a href="https://example.com">url</a>)'


# endregion


# region editor
def test_authors_field_editor_opens_simple_for_a_comma_free_plain_list(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A losslessly comma-editable list opens in the comma line, with the toggle offered and unchecked.

    **Test steps:**

    * seed a comma-free plain-string list
    * build the editor row
    * verify the simple mode is what is shown, and the toggle is enabled and unchecked
    """
    model.authors = ["Alice", "Bob"]
    editor, toggle = build_editor(qtbot, model)

    assert editor.advanced is False
    assert editor.simple_available is True
    assert toggle.isChecked() is False
    assert toggle.defaultAction().isEnabled() is True


def test_authors_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the comma line writes the parsed list through to the model.

    **Test steps:**

    * build the editor over an empty seed
    * set its value as the comma line would
    * verify ``model.authors`` holds the parsed list
    """
    editor, _toggle = build_editor(qtbot, model)

    editor.value_changed.emit(["Alice", "Bob"])
    assert model.authors == ["Alice", "Bob"]


def test_authors_field_editor_opens_in_rows_for_a_record_entry(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A record entry (an author URL) is shown as rows, with the toggle held there and explained.

    **Test steps:**

    * seed one ``{name, url}`` record
    * build the editor row
    * verify the rows are what is shown, and the toggle is checked, disabled and tooltipped
    """
    model.authors = [{"name": "Alice", "url": "https://example.com"}]
    editor, toggle = build_editor(qtbot, model)

    assert editor.advanced is True
    assert editor.simple_available is False
    assert toggle.isChecked() is True
    assert toggle.defaultAction().isEnabled() is False
    assert toggle.defaultAction().toolTip() != ""


def test_authors_field_editor_opens_in_rows_for_a_comma_in_a_name(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A name containing a comma is shown as rows -- it has no lossless comma-line representation.

    **Test steps:**

    * seed a plain name containing a comma
    * build the editor row
    * verify the rows are what is shown and the toggle is not the user's to change
    """
    model.authors = ["Foo Bar, Jr."]
    editor, toggle = build_editor(qtbot, model)

    assert editor.advanced is True
    assert toggle.defaultAction().isEnabled() is False


def test_authors_field_editor_toggle_switches_modes(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Clicking the misc-column toggle switches the editor between the comma line and the rows.

    **Test steps:**

    * build the editor over a simple list
    * check the toggle, then uncheck it
    * verify the editor followed both ways
    """
    model.authors = ["Alice"]
    editor, toggle = build_editor(qtbot, model)

    toggle.setChecked(True)
    assert editor.advanced is True

    toggle.setChecked(False)
    assert editor.advanced is False


def test_authors_field_editor_forcing_the_rows_does_not_rewrite_the_choice(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A value the comma line cannot show holds the editor in the rows without becoming the choice
    (#97: the mode never switches on its own).

    **Test steps:**

    * build the editor over a simple list, left in the simple mode
    * change ``model.authors`` to a record entry -- the rows are forced, the toggle reads checked
    * change it back to a plain list
    * verify the editor is back in the comma line the user never left
    """
    model.authors = ["Alice"]
    editor, toggle = build_editor(qtbot, model)

    model.authors = [{"name": "Alice", "url": "https://example.com"}]
    assert editor.advanced is True
    assert toggle.isChecked() is True

    model.authors = ["Alice", "Bob"]

    assert editor.advanced is False
    assert toggle.isChecked() is False
    assert toggle.defaultAction().isEnabled() is True


def test_authors_field_editor_tracks_model_changes(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A ``binding.changed`` -- a revert, a type switch -- lands in the editor.

    **Test steps:**

    * build the editor over one seed
    * change ``model.authors``
    * verify the editor holds the new value
    """
    model.authors = ["Alice"]
    editor, _toggle = build_editor(qtbot, model)

    model.authors = ["Bob", "Carol"]

    assert editor.value == ["Bob", "Carol"]


def test_authors_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same ``authors`` field and model
    * report an edit from the editor
    * verify the viewer reflects it and the editor still holds the edited value once
    """
    field = AuthorsField("authors")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, AuthorsEditor)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.value_changed.emit(["Alice", "Bob"])

    assert model.authors == ["Alice", "Bob"]
    assert viewer.text() == "Alice, Bob"
    assert editor.value == ["Alice", "Bob"]


def test_authors_field_editor_is_named_for_its_field_so_its_mode_persists(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor carries the field's name, which is the key its saved mode is stored under
    (`StatefulWidget`).

    **Test steps:**

    * build the editor row
    * verify the editor's object name is the field's
    """
    editor, _toggle = build_editor(qtbot, model)

    assert editor.objectName() == "authors"


# endregion


# region link dispatch
def test_authors_field_link_activated_opens_an_http_url(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """Activating an http(s) link opens it via ``QDesktopServices``.

    **Test steps:**

    * build the viewer
    * emit ``linkActivated`` with an ``https`` href
    * verify ``QDesktopServices.openUrl`` was called with it
    """
    open_url = mocker.patch("rehuco_agent.fields.authors_field.QDesktopServices.openUrl")
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    viewer.linkActivated.emit("https://example.com/alice")

    open_url.assert_called_once()
    assert open_url.call_args[0][0].toString() == "https://example.com/alice"  # pylint: disable=no-member


def test_authors_field_link_activated_logs_a_no_op_for_a_filter_link(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A ``filter://`` href is a logged no-op, never opened -- the dispatch seam for the future catalog browser
    ([[plugins#filter-urls]]).

    **Test steps:**

    * build the viewer
    * emit ``linkActivated`` with a ``filter://`` href
    * verify ``QDesktopServices.openUrl`` was never called and the href was logged
    """
    open_url = mocker.patch("rehuco_agent.fields.authors_field.QDesktopServices.openUrl")
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    with caplog.at_level(logging.INFO, logger="rehuco_agent.fields.authors_field"):
        viewer.linkActivated.emit("filter://authors?name=Alice")

    open_url.assert_not_called()
    assert "filter://authors?name=Alice" in caplog.text


def test_authors_field_link_activated_ignores_an_unsupported_scheme(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A scheme that is neither http(s) nor ``filter`` is never followed.

    **Test steps:**

    * build the viewer
    * emit ``linkActivated`` with a ``file://`` href
    * verify ``QDesktopServices.openUrl`` was never called
    """
    open_url = mocker.patch("rehuco_agent.fields.authors_field.QDesktopServices.openUrl")
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    viewer.linkActivated.emit("file:///etc/passwd")

    open_url.assert_not_called()


def test_authors_field_link_hovered_emits_the_href_as_a_status_message(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Hovering a link emits the href as :attr:`~rehuco_agent.fields.field.StatusReporter.status_message`
    for the owner to route to the real status bar; leaving the link (empty href) emits an empty clear --
    the field never touches app chrome itself.

    **Test steps:**

    * build the viewer and record every ``status_message`` it emits
    * emit ``linkHovered`` with an href
    * verify ``status_message`` fired with that href
    * emit ``linkHovered`` with an empty href (cursor left the link)
    * verify ``status_message`` fired with an empty string (the clear)
    """
    field = AuthorsField("authors")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    messages: list[str] = []
    field.status_message.connect(messages.append)

    viewer.linkHovered.emit("https://example.com/alice")
    viewer.linkHovered.emit("")

    assert messages == ["https://example.com/alice", ""]


# endregion
