"""Tests for AuthorsEditor: the comma line while it is lossless, the record rows otherwise (#97)."""

from PySide6.QtWidgets import QLineEdit
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import AuthorsEditor, AuthorsListEditor
from rehuco_agent.fields.widgets.authors_table_model import NAME_COLUMN, URL_COLUMN

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
