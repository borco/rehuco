"""Tests for AuthorsField: the rich-text link viewer, the lossless-guarded comma editor, and the
scheme-dispatching link handlers (#95)."""

import logging

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit, QToolButton
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from fields.field_testers import AuthorsFieldTester as AuthorsField


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
def test_authors_field_editor_enabled_for_a_comma_free_plain_list(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A losslessly comma-editable list leaves the editor enabled, untooltipped, its lock indicator
    hidden.

    **Test steps:**

    * seed a comma-free plain-string list
    * build the editor
    * verify it's enabled, has no tooltip, shows the joined text, and the lock indicator is hidden
    """
    model.authors = ["Alice", "Bob"]
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, lock = widgets.editor, widgets.misc
    assert isinstance(editor, QLineEdit)
    assert isinstance(lock, QToolButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(lock)

    assert editor.isEnabled() is True
    assert editor.toolTip() == ""
    assert editor.text() == "Alice, Bob"
    assert lock.isVisible() is False


def test_authors_field_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the enabled editor writes the parsed list through to the model.

    **Test steps:**

    * build the editor over an empty seed
    * set its text
    * verify ``model.authors`` holds the parsed list
    """
    field = AuthorsField("authors")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)

    editor.setText("Alice, Bob")
    assert model.authors == ["Alice", "Bob"]


def test_authors_field_editor_disables_for_a_record_entry(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A record entry (an author URL) disables the editor, tooltipped, showing the name only, with
    the row's lock indicator shown.

    **Test steps:**

    * seed one ``{name, url}`` record
    * build the editor
    * verify it is disabled, tooltipped, shows the entry's plain name, and the lock indicator is
      visible and tooltipped the same way
    """
    model.authors = [{"name": "Alice", "url": "https://example.com"}]
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, lock = widgets.editor, widgets.misc
    assert isinstance(editor, QLineEdit)
    assert isinstance(lock, QToolButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(lock)

    assert editor.isEnabled() is False
    assert editor.toolTip() != ""
    assert editor.text() == "Alice"
    assert lock.isVisible() is True
    assert lock.toolTip() == editor.toolTip()


def test_authors_field_editor_disables_for_a_comma_in_a_name(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A name containing a comma disables the editor -- it has no lossless comma-line representation.

    **Test steps:**

    * seed a plain name containing a comma
    * build the editor
    * verify it is disabled and the lock indicator is visible
    """
    model.authors = ["Foo Bar, Jr."]
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, lock = widgets.editor, widgets.misc
    assert isinstance(editor, QLineEdit)
    assert isinstance(lock, QToolButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(lock)

    assert editor.isEnabled() is False
    assert lock.isVisible() is True


def test_authors_field_editor_lock_indicator_click_is_a_no_op(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The lock indicator is a static flag, not a control yet -- clicking it changes nothing (#97's
    deferred advanced editor is what will eventually give it something to open).

    **Test steps:**

    * build the editor over a record entry (disabled, lock indicator visible)
    * click the lock indicator
    * verify the editor is still disabled, showing the same value
    """
    model.authors = [{"name": "Alice", "url": "https://example.com"}]
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, lock = widgets.editor, widgets.misc
    assert isinstance(editor, QLineEdit)
    assert isinstance(lock, QToolButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(lock)

    lock.click()

    assert editor.isEnabled() is False
    assert editor.text() == "Alice"
    assert model.authors == [{"name": "Alice", "url": "https://example.com"}]


def test_authors_field_editor_re_enables_live_after_reverting_to_a_clean_list(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A ``binding.changed`` back to an all-plain-comma-free list flips the guard live (e.g. revert()),
    hiding the lock indicator again.

    **Test steps:**

    * build the editor over a record entry (disabled, lock indicator visible)
    * change ``model.authors`` to a clean plain-string list, as a revert would
    * verify the editor re-enables, shows the new value, and the lock indicator hides
    """
    model.authors = [{"name": "Alice", "url": "https://example.com"}]
    field = AuthorsField("authors")
    widgets = field.make_editor(model.bind(field))
    editor, lock = widgets.editor, widgets.misc
    assert isinstance(editor, QLineEdit)
    assert isinstance(lock, QToolButton)
    qtbot.addWidget(editor)
    qtbot.addWidget(lock)
    assert editor.isEnabled() is False
    assert lock.isVisible() is True

    model.authors = ["Alice", "Bob"]

    assert editor.isEnabled() is True
    assert editor.toolTip() == ""
    assert editor.text() == "Alice, Bob"
    assert lock.isVisible() is False


def test_authors_field_editor_stays_disabled_when_the_disabled_display_text_is_unchanged(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A ``binding.changed`` that keeps the editor disabled, with the same displayed names, doesn't
    needlessly rewrite the (already correct) disabled text.

    **Test steps:**

    * build the editor over a record entry (disabled)
    * change ``model.authors`` to a different record with the same name (still disabled, same display)
    * verify the editor is still disabled, showing the unchanged name
    """
    model.authors = [{"name": "Alice", "url": "https://example.com/a"}]
    field = AuthorsField("authors")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)
    assert editor.isEnabled() is False

    model.authors = [{"name": "Alice", "url": "https://example.com/b"}]

    assert editor.isEnabled() is False
    assert editor.text() == "Alice"


def test_authors_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build both an editor and a viewer over the same ``authors`` field and model
    * type in the editor
    * verify the viewer reflects it and the editor still holds the typed text once
    """
    field = AuthorsField("authors")
    # pylint: disable=duplicate-code
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, QLineEdit)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)
    # pylint: enable=duplicate-code

    editor.setText("Alice, Bob")

    assert model.authors == ["Alice", "Bob"]
    assert viewer.text() == "Alice, Bob"
    assert editor.text() == "Alice, Bob"


def test_authors_field_editor_preserves_the_cursor_when_typing_mid_string(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Typing in the middle of the text doesn't teleport the cursor to the end (echo guard, cf. #35).

    **Test steps:**

    * build the editor and seed it with a two-name value
    * place the cursor mid-string and type one character there
    * verify the character landed at the cursor and the cursor advanced by one
    """
    field = AuthorsField("authors")
    # pylint: disable=duplicate-code
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QLineEdit)
    qtbot.addWidget(editor)
    editor.setText("Alice, Bob")
    editor.setCursorPosition(5)

    qtbot.keyClicks(editor, "x")

    assert editor.text() == "Alicex, Bob"
    assert editor.cursorPosition() == 6
    # pylint: enable=duplicate-code


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
    """A ``filter://`` href is a logged no-op, never opened -- the dispatch seam for Milestone B
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
