"""Tests for AuthorsEditor: the comma line while it is lossless, the record rows otherwise (#97)."""

from typing import Any

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import AuthorsEditor, AuthorsListEditor
from rehuco_agent.fields.widgets.authors_table_model import NAME_COLUMN, URL_COLUMN

from .drop_host import DropHost

RECORD = {"name": "Bob", "url": "https://example.com/bob"}


# region helpers
@fixture
def editor(qtbot: QtBot) -> AuthorsEditor:
    """An editor over two plain names -- the simple case.

    :param qtbot: the widget-owning fixture.
    :returns: the seeded editor.
    """
    widget = AuthorsEditor()
    qtbot.addWidget(widget)
    widget.set_value(["Alice", "Bob"])
    return widget


def simple(editor: AuthorsEditor) -> QLineEdit:
    """The comma line the simple mode edits through.

    :param editor: the editor to reach into.
    :returns: its line edit.
    """
    line_edit = editor.findChild(QLineEdit)
    assert isinstance(line_edit, QLineEdit)
    return line_edit


def rows(editor: AuthorsEditor) -> AuthorsListEditor:
    """The record rows the advanced mode edits through.

    :param editor: the editor to reach into.
    :returns: its list editor.
    """
    list_editor = editor.findChild(AuthorsListEditor)
    assert isinstance(list_editor, AuthorsListEditor)
    return list_editor


# endregion


# region modes
def test_a_simple_list_opens_in_the_comma_line(editor: AuthorsEditor, qtbot: QtBot) -> None:
    """Plain comma-free names are what the comma line is for.

    **Test steps:**

    * show the editor over two plain names
    * verify the simple mode is available and shown, and the rows are not
    """
    with qtbot.waitExposed(editor):
        editor.show()

    assert editor.simple_available is True
    assert editor.advanced is False
    assert simple(editor).isVisible() is True
    assert rows(editor).isVisible() is False
    assert simple(editor).text() == "Alice, Bob"


def test_a_record_entry_is_shown_as_rows(editor: AuthorsEditor, qtbot: QtBot) -> None:
    """A URL has no comma-line representation, so the rows are what is shown.

    **Test steps:**

    * set a value carrying a record entry and show the editor
    * verify the simple mode is unavailable and the rows are shown
    """
    editor.set_value([RECORD])
    with qtbot.waitExposed(editor):
        editor.show()

    assert editor.simple_available is False
    assert editor.advanced is True
    assert rows(editor).isVisible() is True
    assert simple(editor).isVisible() is False


def test_a_comma_in_a_name_is_shown_as_rows(editor: AuthorsEditor) -> None:
    """``Foo Bar, Jr.`` would split into two on re-parse.

    **Test steps:**

    * set a name containing a comma
    * verify the simple mode is unavailable
    """
    editor.set_value(["Foo Bar, Jr."])

    assert editor.simple_available is False
    assert editor.advanced is True


def test_the_chosen_mode_is_what_is_shown_while_both_are_available(editor: AuthorsEditor, qtbot: QtBot) -> None:
    """Picking the rows for a simple list is allowed -- that is where a URL gets added.

    **Test steps:**

    * switch the editor to the rows and show it
    * verify the rows are shown, and that switching back returns to the comma line
    """
    editor.set_advanced(True)
    with qtbot.waitExposed(editor):
        editor.show()

    assert editor.advanced is True
    assert rows(editor).isVisible() is True

    editor.set_advanced(False)

    assert editor.advanced is False
    assert simple(editor).isVisible() is True


def test_a_forced_mode_never_rewrites_the_choice(editor: AuthorsEditor) -> None:
    """The mode never switches on its own (#97): a value it cannot show holds the rows open, and
    letting that stand as the choice would strand the user there.

    **Test steps:**

    * leave the editor in the simple mode, then set a value it cannot show
    * verify the rows are forced
    * set a simple value again
    * verify the editor is back in the comma line the user never left
    """
    editor.set_value([RECORD])
    assert editor.advanced is True

    editor.set_value(["Alice"])

    assert editor.advanced is False


def test_switching_to_the_same_mode_changes_nothing(editor: AuthorsEditor) -> None:
    """A choice already made is not a change to report.

    **Test steps:**

    * record every ``mode_changed`` and pick the mode the editor is already in
    * verify nothing was reported
    """
    modes: list[int] = []
    editor.mode_changed.connect(lambda: modes.append(1))

    editor.set_advanced(False)

    assert not modes


def test_the_mode_is_remembered_across_a_session(editor: AuthorsEditor, qtbot: QtBot) -> None:
    """The choice is persisted per ``.rehu`` (`StatefulWidget`), so a rebuilt form opens where it was.

    **Test steps:**

    * pick the rows and save the state
    * restore it into a fresh editor and verify it opens in the rows
    * restore the other state and verify it opens in the comma line
    """
    editor.set_advanced(True)

    restored = AuthorsEditor()
    qtbot.addWidget(restored)
    restored.set_value(["Alice"])
    restored.restore_state(editor.save_state())

    assert restored.advanced is True

    restored.restore_state(b"\x00")

    assert restored.advanced is False


def test_a_forced_mode_is_not_what_is_saved(editor: AuthorsEditor) -> None:
    """A document whose authors all carry links opens in the rows either way -- saving that would
    make the choice permanent.

    **Test steps:**

    * leave the editor in the simple mode and set a value it cannot show
    * verify what is saved is still the simple mode
    """
    editor.set_value([RECORD])

    assert editor.advanced is True
    assert editor.save_state() == b"\x00"


def test_an_unreadable_saved_state_reads_as_the_comma_line(editor: AuthorsEditor) -> None:
    """Anything but the advanced marker is the default mode.

    **Test steps:**

    * restore from an empty blob
    * verify the editor is in the comma line
    """
    editor.set_advanced(True)

    editor.restore_state(b"")

    assert editor.advanced is False


# endregion


# region editing
def test_typing_in_the_comma_line_reports_the_parsed_list(editor: AuthorsEditor) -> None:
    """The simple mode is the same comma text the other list fields round-trip through.

    **Test steps:**

    * record every reported value and type into the comma line
    * verify the parsed list was reported and is what the editor holds
    """
    reported: list[list[object]] = []
    editor.value_changed.connect(reported.append)

    simple(editor).setText("Carol, Dave")

    assert reported == [["Carol", "Dave"]]
    assert editor.value == ["Carol", "Dave"]


def test_editing_a_row_reports_the_entries(editor: AuthorsEditor) -> None:
    """The advanced mode reports through the same one signal, so its owner never learns which mode
    made the edit.

    **Test steps:**

    * record every reported value and give an author a URL through the rows
    * verify the record was reported
    """
    reported: list[list[object]] = []
    editor.value_changed.connect(reported.append)

    model = rows(editor).model
    model.setData(model.index(1, URL_COLUMN), "https://example.com/bob")

    assert reported == [["Alice", RECORD]]


def test_an_edit_in_one_mode_lands_in_the_other(editor: AuthorsEditor) -> None:
    """Both halves are kept current, so switching modes has nothing to catch up on.

    **Test steps:**

    * type in the comma line, then read the rows
    * verify the rows hold what was typed
    * rename an author through the rows and verify the comma line followed
    """
    simple(editor).setText("Carol, Dave")

    assert rows(editor).entries == ("Carol", "Dave")

    model = rows(editor).model
    model.setData(model.index(0, NAME_COLUMN), "Erin")

    assert simple(editor).text() == "Erin, Dave"


def test_seeding_the_editor_reports_nothing(editor: AuthorsEditor) -> None:
    """A value arriving from the model is not an edit (the echo guard).

    **Test steps:**

    * record every reported value and set one through ``set_value``
    * verify nothing was reported and the editor holds it
    """
    reported: list[list[object]] = []
    editor.value_changed.connect(reported.append)

    editor.set_value(["Carol", RECORD])

    assert not reported
    assert editor.value == ["Carol", RECORD]


def test_typing_mid_string_keeps_the_cursor_where_it_is(editor: AuthorsEditor, qtbot: QtBot) -> None:
    """The echo compares the *parsed* text, so a user's own keystroke doesn't bounce back (cf. #35).

    **Test steps:**

    * put the cursor mid-string and type one character there
    * verify the character landed at the cursor and the cursor advanced by one
    """
    line_edit = simple(editor)
    line_edit.setCursorPosition(5)

    qtbot.keyClicks(line_edit, "x")

    assert line_edit.text() == "Alicex, Bob"
    assert line_edit.cursorPosition() == 6


def test_a_value_the_comma_line_cannot_write_leaves_it_disabled(editor: AuthorsEditor) -> None:
    """It still shows the names -- a display, never written back from, since the rows are on screen.

    **Test steps:**

    * set a value carrying a record
    * verify the comma line is disabled, tooltipped, and showing the plain names
    """
    editor.set_value(["Alice", RECORD])

    line_edit = simple(editor)
    assert line_edit.isEnabled() is False
    assert line_edit.toolTip() != ""
    assert line_edit.text() == "Alice, Bob"


def test_the_comma_line_says_what_it_is_while_it_is_usable(editor: AuthorsEditor) -> None:
    """Two tooltips, one per state, so the control always accounts for itself.

    **Test steps:**

    * read the comma line's tooltip over a simple value
    * verify it is enabled and explains the comma convention
    """
    line_edit = simple(editor)

    assert line_edit.isEnabled() is True
    assert "commas" in line_edit.toolTip()


def test_an_entry_that_is_a_record_in_name_only_reads_as_a_plain_name(editor: AuthorsEditor) -> None:
    """A hand-written ``{"name"}`` record would otherwise keep the comma line switched off for a
    reason no user could see.

    **Test steps:**

    * set a record carrying nothing but a name
    * verify the simple mode is still available and the value reads as the plain name
    """
    editor.set_value([{"name": "Alice"}])

    assert editor.simple_available is True
    assert editor.value == ["Alice"]


# endregion


def test_the_first_line_is_a_stable_height(editor: AuthorsEditor) -> None:
    """`HeaderPinned`: the row's label stays level with the editor's first line in either mode.

    **Test steps:**

    * read the header height in the simple mode, then in the rows
    * verify it did not move
    """
    in_simple = editor.header_height

    editor.set_advanced(True)

    assert editor.header_height == in_simple


# region a row pending a name


def test_an_edit_to_a_row_pending_a_name_is_not_reported(editor: AuthorsEditor) -> None:
    """A half-typed author is not in the value, so typing into it changes nothing to report.

    **Test steps:**

    * switch to the rows, insert one and give it only a URL
    * verify nothing was reported and the value is the two names
    """
    editor.set_advanced(True)
    reported: list[Any] = []
    editor.value_changed.connect(reported.append)
    model = rows(editor).model

    model.insertRows(2, 1)
    model.setData(model.index(2, URL_COLUMN), "https://example.com/carol")

    assert not reported
    assert editor.value == ["Alice", "Bob"]


def test_naming_a_pending_row_reports_it(editor: AuthorsEditor) -> None:
    """The name is what makes the row an author, and that is the edit reported.

    **Test steps:**

    * switch to the rows, insert one, give it a URL and then a name
    * verify one report arrived, carrying the new author last
    """
    editor.set_advanced(True)
    reported: list[Any] = []
    editor.value_changed.connect(reported.append)
    model = rows(editor).model
    model.insertRows(2, 1)
    model.setData(model.index(2, URL_COLUMN), "https://example.com/carol")

    model.setData(model.index(2, NAME_COLUMN), "Carol")

    assert reported == [["Alice", "Bob", {"name": "Carol", "url": "https://example.com/carol"}]]


# endregion

# region a link dropped on the editor (#385)

LINK_URL = "https://example.com/carol"


def link_data(text: str = "Carol", url: str = LINK_URL) -> QMimeData:
    """The mime data of a dragged link, as Firefox and Chromium write it.

    :param text: the link's text.
    :param url: the link's URL.
    :returns: ``text/x-moz-url`` carrying both.
    """
    data = QMimeData()
    data.setData("text/x-moz-url", f"{url}\n{text}".encode("utf-16"))
    return data


def drop_on(target: QWidget, data: QMimeData) -> bool:
    """Drag ``data`` over the middle of ``target`` and drop it there.

    :param target: the widget to drop on.
    :param data: what is dragged; the caller keeps it alive.
    :returns: whether the drop was accepted.
    """
    centre = QPointF(target.rect().center())
    args = (Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, QDragEnterEvent(centre.toPoint(), *args))
    drop = QDropEvent(centre, *args)
    QApplication.sendEvent(target, drop)
    return drop.isAccepted()


@fixture
def hosted(qtbot: QtBot) -> tuple[AuthorsEditor, DropHost]:
    """An editor over two plain names, inside a widget that accepts drops, shown.

    :param qtbot: the widget-owning fixture.
    :returns: the editor and its host.
    """
    host = DropHost()
    qtbot.addWidget(host)
    editor = AuthorsEditor()
    QVBoxLayout(host).addWidget(editor)
    editor.set_value(["Alice", "Bob"])
    with qtbot.waitExposed(host):
        host.show()
    return editor, host


def test_a_link_dropped_on_the_comma_line_adds_the_author(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """The line is a text field that would take the drop as text; a link is an author instead.

    **Test steps:**

    * drop a link on the comma line
    * verify the author was added with the URL, reported once, and the host never saw the drop
    """
    editor, host = hosted
    reported: list[Any] = []
    editor.value_changed.connect(reported.append)

    accepted = drop_on(simple(editor), link_data())

    assert accepted
    assert editor.value == ["Alice", "Bob", {"name": "Carol", "url": LINK_URL}]
    assert len(reported) == 1
    assert not host.dropped
    assert editor.advanced  # the value no longer fits the line


def test_a_link_dropped_on_the_rows_updates_the_author_listed(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """In the rows a link on a name cell is the editor's drop, not the dock's.

    **Test steps:**

    * switch to the rows and drop a link named like the second author on the table
    * verify that author got the URL, and the host never saw the drop
    """
    editor, host = hosted
    editor.set_advanced(True)

    accepted = drop_on(rows(editor).view.viewport(), link_data("Bob", "https://example.com/bob"))

    assert accepted
    assert editor.value == ["Alice", {"name": "Bob", "url": "https://example.com/bob"}]
    assert not host.dropped


def test_the_same_link_dropped_twice_is_one_edit(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """Dropping what is already listed is accepted, and changes nothing.

    **Test steps:**

    * drop a link, then the same link again
    * verify only the first was reported
    """
    editor, _ = hosted
    reported: list[Any] = []
    editor.value_changed.connect(reported.append)

    drop_on(simple(editor), link_data())
    assert editor.advanced
    drop_on(rows(editor).view.viewport(), link_data())

    assert len(reported) == 1


def test_an_anchor_dropped_on_the_editor_adds_the_author(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """The `text/html` of an anchor carries the same link.

    **Test steps:**

    * drop an anchor on the editor
    * verify the author was added
    """
    editor, _ = hosted
    data = QMimeData()
    data.setHtml(f'<a href="{LINK_URL}">Carol</a>')

    drop_on(simple(editor), data)

    assert editor.value[-1] == {"name": "Carol", "url": LINK_URL}


def test_a_drop_that_is_not_a_link_is_left_to_the_text_field(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """Plain text, a lone URL as text, a bare uri-list and a `file:` link are not this editor's drop: the
    comma line takes them as it always did.

    **Test steps:**

    * drop each on the comma line
    * verify the line took the text itself and no author became a record
    """
    editor, _ = hosted
    plain = QMimeData()
    plain.setText("just some words")
    url_text = QMimeData()
    url_text.setText(LINK_URL)
    uri_list = QMimeData()
    uri_list.setUrls([QUrl(LINK_URL)])
    file_link = link_data("A file", "file:///some/file.jpg")

    for data in (plain, url_text, uri_list, file_link):
        drop_on(simple(editor), data)

    assert simple(editor).text() != "Alice, Bob"
    assert all(isinstance(entry, str) for entry in editor.value)


def test_a_non_link_dropped_on_the_editor_itself_reaches_the_host(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """The editor hands on what it does not take, so the dock's own drops still work around it.

    **Test steps:**

    * drop plain text on the editor's own area
    * verify the host took it
    """
    editor, host = hosted
    plain = QMimeData()
    plain.setText(LINK_URL)

    drop_on(editor, plain)

    assert host.dropped
    assert editor.value == ["Alice", "Bob"]


def test_a_locked_editor_refuses_the_drop(hosted: tuple[AuthorsEditor, DropHost]) -> None:
    """A locked document disables its editor, and a disabled editor takes no link.

    **Test steps:**

    * disable the editor and hand its drag handlers a link (Qt may not deliver one to a disabled widget)
    * verify none was accepted and the list is unchanged
    """
    editor, _ = hosted
    editor.setEnabled(False)
    data = link_data()
    point = editor.rect().center()
    args = (Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    enter = QDragEnterEvent(point, *args)
    move = QDragMoveEvent(point, *args)
    drop = QDropEvent(QPointF(point), *args)

    editor.dragEnterEvent(enter)
    editor.dragMoveEvent(move)
    editor.dropEvent(drop)

    assert not (enter.isAccepted() or move.isAccepted() or drop.isAccepted())
    assert editor.value == ["Alice", "Bob"]


def test_a_drag_over_the_editor_is_accepted_for_a_link_and_ignored_otherwise(
    hosted: tuple[AuthorsEditor, DropHost],
) -> None:
    """The cursor moving over the editor keeps the drop on offer for a link, and hands anything else on.

    **Test steps:**

    * move a link, then plain text, over the editor and drop plain text on it
    * verify only the link was accepted, and the plain text drop changed nothing
    """
    editor, _ = hosted
    link = link_data()
    plain = QMimeData()
    plain.setText("just some words")
    point = editor.rect().center()
    args = (Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    over_link = QDragMoveEvent(point, args[0], link, *args[1:])
    over_text = QDragMoveEvent(point, args[0], plain, *args[1:])
    drop_text = QDropEvent(QPointF(point), args[0], plain, *args[1:])

    editor.dragMoveEvent(over_link)
    editor.dragMoveEvent(over_text)
    editor.dropEvent(drop_text)

    assert over_link.isAccepted()
    assert not over_text.isAccepted()
    assert not drop_text.isAccepted()
    assert editor.value == ["Alice", "Bob"]


# endregion
