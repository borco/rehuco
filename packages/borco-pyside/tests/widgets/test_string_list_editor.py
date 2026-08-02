"""Tests for StringListEditor: a list of strings edited in place, by button and by key.

The offscreen platform opens real in-place editors, so the insert/edit tests drive the delegate's own
`QLineEdit` rather than setting model data behind its back -- which is the only way the "``Del`` edits
text while an entry is open" rule can be asserted at all.
"""

from borco_pyside.widgets import ContentSizedListView, StringItemListModel, StringListEditor
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QSizePolicy
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

DEFAULTS = ("*.tmp", "Thumbs.db")


# region helpers


@fixture
def editor(qtbot: QtBot) -> StringListEditor:
    """An editor over three entries, with two defaults and its ordering column shown.

    :param qtbot: the widget-owning fixture.
    :returns: the editor, shown so its in-place editors get focus.
    """
    widget = StringListEditor(defaults=DEFAULTS)
    qtbot.addWidget(widget)
    widget.values = ("one", "two", "three")
    # an in-place editor is only fed keystrokes once its parent is really on screen, so wait for the
    # show to land rather than firing it and moving on -- offscreen exposes for real
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def inner_view(widget: StringListEditor) -> ContentSizedListView:
    """The editor's own view, for driving focus and the current row.

    :param widget: the editor to reach into.
    :returns: the view it edits through.
    """
    view = widget.view
    assert isinstance(view, ContentSizedListView)
    return view


def inner_model(widget: StringListEditor) -> StringItemListModel:
    """The editor's own model -- the list itself, and what every domain operation is a call on.

    :param widget: the editor to reach into.
    :returns: the string-item-list model behind the view.
    """
    model = widget.model
    assert isinstance(model, StringItemListModel)
    return model


def select(widget: StringListEditor, row: int) -> None:
    """Make ``row`` the current one.

    :param widget: the editor to select in.
    :param row: the row to make current, or ``-1`` to leave none current.
    """
    index = inner_model(widget).index(row, 0) if row >= 0 else QModelIndex()
    inner_view(widget).setCurrentIndex(index)


def current_row(widget: StringListEditor) -> int:
    """The row currently being acted on.

    :param widget: the editor to read.
    :returns: the current row, or ``-1``.
    """
    return inner_view(widget).currentIndex().row()


def row_signals(widget: StringListEditor) -> list[str]:
    """Record which row-level model signals fire from now on.

    :param widget: the editor whose model to watch.
    :returns: a list that fills with signal names as they fire.
    """
    seen: list[str] = []
    model = inner_model(widget)
    for name in ("rowsInserted", "rowsRemoved", "rowsMoved", "modelReset"):
        getattr(model, name).connect(lambda *_, name=name: seen.append(name))
    return seen


def open_editor() -> QLineEdit:
    """The in-place editor currently open, as the focused widget.

    :returns: the delegate's editor line edit.
    """
    # the delegate builds and shows its editor inline, but the show only lands on the next pass
    # through the event loop -- and a widget that has not been mapped yet takes no keystrokes
    QApplication.processEvents()
    focused = QApplication.focusWidget()
    assert isinstance(focused, QLineEdit), "no in-place editor is open"
    return focused


def type_and_commit(text: str) -> None:
    """Type into the open in-place editor and commit it with Enter.

    :param text: what to type.
    """
    field = open_editor()
    QTest.keyClicks(field, text)
    commit(field)


def commit(field: QLineEdit) -> None:
    """Close the open in-place editor with Enter and let the commit land.

    :param field: the editor to close.
    """
    QTest.keyClick(field, Qt.Key.Key_Return)
    # the delegate writes the typed text back and tears the editor down off the event loop, so the
    # list is still showing the old text until this returns
    QApplication.processEvents()


# endregion

# region values


def test_values_round_trips_a_list_set_into_it(editor: StringListEditor) -> None:
    """What was set is what is read back, in order and unnormalized.

    **Test steps:**

    * set a list holding whitespace and mixed case
    * verify it comes back exactly as given
    """
    editor.values = ("  Padded  ", "MiXeD", "plain")

    assert editor.values == ("  Padded  ", "MiXeD", "plain")


def test_a_value_holding_a_comma_survives_a_round_trip(editor: StringListEditor) -> None:
    """The one thing a comma-separated field could never do (#231).

    **Test steps:**

    * set a list whose entry contains a comma
    * verify it comes back as one entry, comma intact
    """
    editor.values = ("Screenshot, final.png",)

    assert editor.values == ("Screenshot, final.png",)


def test_setting_the_same_values_changes_nothing_and_says_nothing(editor: StringListEditor) -> None:
    """A no-op set neither touches the model nor reports an edit that didn't happen.

    **Test steps:**

    * spy on the change signal and the model's row signals
    * set the values already shown
    * verify neither fired
    """
    seen = row_signals(editor)
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))

    editor.values = ("one", "two", "three")

    assert not changes
    assert not seen


def test_replacing_the_list_is_one_model_reset_and_one_edit(editor: StringListEditor) -> None:
    """The whole replacement is a single reset, not a clear and a row-by-row refill.

    **Test steps:**

    * spy on the change signal and every row-level model signal, then replace the whole list
    * verify exactly one edit was reported, by exactly one model reset
    """
    seen = row_signals(editor)
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))

    editor.values = ("only", "two")

    assert len(changes) == 1
    assert seen == ["modelReset"]


# endregion

# region insert, edit, delete, reset


def test_insert_puts_a_new_entry_below_the_current_one_and_opens_it(editor: StringListEditor) -> None:
    """Insert is where a new entry comes from, and it lands where the user is looking.

    **Test steps:**

    * make the first row current, then insert
    * verify a blank entry landed below it, is current, and is open for typing
    """
    select(editor, 0)

    editor.item_actions.insert_action.trigger()

    assert editor.values == ("one", "", "two", "three")
    assert current_row(editor) == 1
    assert isinstance(QApplication.focusWidget(), QLineEdit)


def test_insert_appends_when_nothing_is_current(editor: StringListEditor) -> None:
    """With no current row there is no "below", so the entry goes last -- which is also how an
    emptied list gets its first row back.

    **Test steps:**

    * clear the list entirely, then insert and type
    * verify the typed entry is the list's only one
    """
    editor.values = ()

    editor.item_actions.insert_action.trigger()
    type_and_commit("first")

    assert editor.values == ("first",)


def test_an_inserted_entry_left_blank_is_undone(editor: StringListEditor) -> None:
    """An abandoned insert is a gesture, not a value -- and reports no edit either.

    **Test steps:**

    * spy on the change signal, insert, and dismiss the editor with Escape
    * verify the list is untouched and nothing was reported
    """
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 0)

    editor.item_actions.insert_action.trigger()
    QTest.keyClick(open_editor(), Qt.Key.Key_Escape)

    assert editor.values == ("one", "two", "three")
    assert not changes


def test_an_inserted_entry_committed_as_whitespace_is_undone_and_never_reported(editor: StringListEditor) -> None:
    """Committing whitespace with Enter is the same abandoned gesture as Escape -- and must leak no
    signal either, even though the commit touches the model an instant before the undo.

    Guards the gap the Escape test cannot see: a whitespace commit lands in the model
    (``dataChanged``) before ``closeEditor`` removes the row, and reporting that instant would leave
    the last report -- a list with a whitespace entry in it -- disagreeing with the state the silent
    undo settles on.

    **Test steps:**

    * spy on the change signal, insert below the first row, type only spaces, and press Enter
    * verify the list is untouched and nothing was ever reported
    """
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 0)

    editor.item_actions.insert_action.trigger()
    type_and_commit("   ")

    assert editor.values == ("one", "two", "three")
    assert not changes


def test_typing_into_an_inserted_entry_reports_exactly_one_edit(editor: StringListEditor) -> None:
    """The insert itself is silent, so the commit is the one edit anyone hears about.

    **Test steps:**

    * spy on the change signal, insert below the first row, and type
    * verify the entry landed and exactly one edit was reported
    """
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 0)

    editor.item_actions.insert_action.trigger()
    type_and_commit("typed")

    assert editor.values == ("one", "typed", "two", "three")
    assert len(changes) == 1


def test_edit_reopens_the_current_entry(editor: StringListEditor) -> None:
    """Edit starts the same in-place edit a double-click does, on the current row.

    **Test steps:**

    * make the second row current and trigger Edit
    * retype it and verify the new text took, reported as one edit
    """
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 1)

    editor.item_actions.edit_action.trigger()
    open_editor().clear()
    type_and_commit("retyped")

    assert editor.values == ("one", "retyped", "three")
    assert len(changes) == 1


def test_delete_drops_the_current_entry(editor: StringListEditor) -> None:
    """Delete takes out the current row and nothing else.

    **Test steps:**

    * make the second row current and trigger Delete
    * verify only that entry is gone
    """
    select(editor, 1)

    editor.item_actions.delete_action.trigger()

    assert editor.values == ("one", "three")


def test_edit_and_delete_do_nothing_without_a_current_row(editor: StringListEditor, mocker: MockerFixture) -> None:
    """Both act on a current row, so a trigger arriving without one is a no-op, not a crash.

    **Test steps:**

    * clear the current row and spy on the view's ``edit``
    * fire both actions' ``triggered`` directly, past the disabled state that stops ``trigger()``
    * verify no edit was started and the list is unchanged
    """
    select(editor, -1)
    edit = mocker.patch.object(ContentSizedListView, "edit")

    editor.item_actions.edit_action.triggered.emit()
    editor.item_actions.delete_action.triggered.emit()

    edit.assert_not_called()
    assert editor.values == ("one", "two", "three")


def test_reset_replaces_the_list_with_the_defaults(editor: StringListEditor) -> None:
    """A user who emptied the list has no other way back, so Reset is the way.

    **Test steps:**

    * empty the list, then trigger Reset
    * verify the defaults are listed
    """
    editor.values = ()

    editor.reset_action.trigger()

    assert editor.values == DEFAULTS


def test_reset_is_hidden_until_there_are_defaults_to_restore(qtbot: QtBot) -> None:
    """A Reset with nothing to restore promises an action that would do nothing.

    **Test steps:**

    * build an editor with no defaults and verify Reset is hidden
    * give it defaults and verify Reset comes back, restoring them
    """
    widget = StringListEditor()
    qtbot.addWidget(widget)

    assert widget.reset_action.isVisible() is False

    widget.defaults = DEFAULTS

    assert widget.defaults == DEFAULTS
    assert widget.reset_action.isVisible() is True


def test_insert_stays_available_with_nothing_selected(editor: StringListEditor) -> None:
    """Insert is list-wide: disabling it alongside the row actions would strand an emptied list.

    **Test steps:**

    * empty the list, leaving nothing current
    * verify Insert is still enabled while Edit and Delete are not
    """
    editor.values = ()

    assert editor.item_actions.insert_action.isEnabled() is True
    assert editor.item_actions.edit_action.isEnabled() is False
    assert editor.item_actions.delete_action.isEnabled() is False


# endregion

# region ordering


def test_the_move_actions_reorder_one_entry_and_keep_it_current(editor: StringListEditor) -> None:
    """Each of the four moves the current entry where it says, and leaves it current there.

    **Test steps:**

    * from the first row, move down, then to the bottom, then up, then back to the top
    * verify the order and the current row after each
    """
    select(editor, 0)

    editor.ordering_actions.move_down_action.trigger()
    assert (editor.values, current_row(editor)) == (("two", "one", "three"), 1)

    editor.ordering_actions.move_to_bottom_action.trigger()
    assert (editor.values, current_row(editor)) == (("two", "three", "one"), 2)

    editor.ordering_actions.move_up_action.trigger()
    assert (editor.values, current_row(editor)) == (("two", "one", "three"), 1)

    editor.ordering_actions.move_to_top_action.trigger()
    assert (editor.values, current_row(editor)) == (("one", "two", "three"), 0)


def test_a_move_is_one_model_move_not_a_removal_and_an_insertion(editor: StringListEditor) -> None:
    """A move is ``moveRow`` -- the model's own primitive -- so the list is never rebuilt to reorder it.

    A remove-then-insert would say the entry was destroyed and a different one created, which is what
    every attached selection, persistent index and proxy would then have to survive.

    **Test steps:**

    * spy on the change signal and every row-level model signal
    * move the first row down
    * verify the model reported exactly one ``rowsMoved`` and nothing else, and one edit came out
    """
    seen = row_signals(editor)
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 0)

    editor.ordering_actions.move_down_action.trigger()

    assert seen == ["rowsMoved"]
    assert len(changes) == 1
    assert editor.values == ("two", "one", "three")


def test_a_persistent_index_follows_the_entry_through_a_move(editor: StringListEditor) -> None:
    """The moved entry keeps its identity: anything holding a persistent index onto it is carried along.

    This is what a remove-then-insert cannot do -- it would invalidate that index, because it says the
    entry was destroyed and an unrelated one created at the destination.

    **Test steps:**

    * take a persistent index on the first row, then move that row down
    * verify the index is still valid, now names row 1, and still reads the same entry
    """
    persistent = QPersistentModelIndex(inner_model(editor).index(0, 0))
    select(editor, 0)

    editor.ordering_actions.move_down_action.trigger()

    assert persistent.isValid()
    assert persistent.row() == 1
    assert persistent.data() == "one"


def test_the_move_actions_are_disabled_at_the_ends_and_without_a_selection(editor: StringListEditor) -> None:
    """A move that cannot go anywhere is off, so the buttons say where the entry already is.

    **Test steps:**

    * clear the current row and verify all four are off
    * select the first row and verify the upward pair is off, the downward pair on
    * select the last row and verify the reverse
    """
    ordering = editor.ordering_actions

    def enabled() -> tuple[bool, bool, bool, bool]:
        return (
            ordering.move_to_top_action.isEnabled(),
            ordering.move_up_action.isEnabled(),
            ordering.move_down_action.isEnabled(),
            ordering.move_to_bottom_action.isEnabled(),
        )

    select(editor, -1)
    assert enabled() == (False, False, False, False)

    select(editor, 0)
    assert enabled() == (False, False, True, True)

    select(editor, 2)
    assert enabled() == (True, True, False, False)


def test_a_move_fired_without_a_current_row_does_nothing(editor: StringListEditor) -> None:
    """The actions are disabled there, so this is the guard behind them, not the UI.

    **Test steps:**

    * clear the current row and fire every move's ``triggered`` past its disabled state
    * verify the list is unchanged
    """
    select(editor, -1)

    for action in (
        editor.ordering_actions.move_to_top_action,
        editor.ordering_actions.move_up_action,
        editor.ordering_actions.move_down_action,
        editor.ordering_actions.move_to_bottom_action,
    ):
        action.triggered.emit()

    assert editor.values == ("one", "two", "three")


def test_a_move_to_where_the_entry_already_is_does_nothing(editor: StringListEditor) -> None:
    """Moving the first row to the top is not an edit, so it reports none.

    **Test steps:**

    * make the first row current and spy on the change signal
    * fire Move to Top's ``triggered`` past its disabled state
    * verify nothing changed and nothing was reported
    """
    changes: list[None] = []
    editor.values_changed.connect(lambda: changes.append(None))
    select(editor, 0)

    editor.ordering_actions.move_to_top_action.triggered.emit()

    assert editor.values == ("one", "two", "three")
    assert not changes


def test_the_ordering_column_can_be_hidden_shortcuts_and_all(qtbot: QtBot) -> None:
    """A list whose order carries no meaning hides the four buttons -- and their keys with them.

    **Test steps:**

    * build an editor with ordering off and verify the column is hidden
    * press Ctrl+End on its view and verify nothing moved -- the view navigated to the last row
      instead, which is what that key does when this widget has not taken it
    * put the current row back, turn ordering on, and verify the same key now moves the entry
    """
    widget = StringListEditor(with_ordering=False)
    qtbot.addWidget(widget)
    widget.values = ("one", "two")
    with qtbot.waitExposed(widget):
        widget.show()
    view = inner_view(widget)
    view.setFocus()
    select(widget, 0)

    assert widget.ordering_actions.isVisible() is False

    QTest.keySequence(view, QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End))
    assert widget.values == ("one", "two")
    assert current_row(widget) == 1

    select(widget, 0)
    widget.set_ordering_visible(True)
    # the column's show has to land before its actions' keys are back in the shortcut map
    QApplication.processEvents()
    QTest.keySequence(view, QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End))

    assert widget.ordering_actions.isVisible() is True
    assert widget.values == ("two", "one")


# endregion

# region keys


def test_the_shortcuts_fire_while_the_view_has_focus(editor: StringListEditor) -> None:
    """Every action's key works from the view, which is where a user editing a list is.

    **Test steps:**

    * focus the view on its last row and press Ctrl+Home, then Del
    * verify the entry moved to the top and was then dropped
    """
    view = inner_view(editor)
    view.setFocus()
    select(editor, 2)

    QTest.keySequence(view, QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home))
    assert editor.values == ("three", "one", "two")

    QTest.keySequence(view, QKeySequence(QKeySequence.StandardKey.Delete))
    assert editor.values == ("one", "two")


def test_delete_edits_the_text_while_an_entry_is_open(editor: StringListEditor) -> None:
    """The shortcuts are armed on the view, and an open in-place editor holds the focus in its stead --
    so ``Del`` there deletes a character rather than the row (#231).

    **Test steps:**

    * insert an entry and type two characters into its open editor
    * go to the start of the text and press Del
    * verify the first character went, not the row
    """
    inner_view(editor).setFocus()
    select(editor, 0)

    editor.item_actions.insert_action.trigger()
    field = open_editor()
    QTest.keyClicks(field, "ab")
    QTest.keyClick(field, Qt.Key.Key_Home)
    QTest.keyClick(field, Qt.Key.Key_Delete)
    commit(field)

    assert editor.values == ("one", "b", "two", "three")


def test_insert_from_the_keyboard_opens_the_new_entry_for_typing(editor: StringListEditor) -> None:
    """``Ins`` is the whole gesture: a new entry, current, and already accepting text.

    **Test steps:**

    * focus the view on its first row and press Ins
    * type and commit
    * verify the typed entry landed below the first row
    """
    view = inner_view(editor)
    view.setFocus()
    select(editor, 0)

    QTest.keySequence(view, QKeySequence(Qt.Key.Key_Insert))
    type_and_commit("typed")

    assert editor.values == ("one", "typed", "two", "three")


# endregion

# region layout


def test_the_view_grows_with_its_rows_so_an_enclosing_page_scrolls(editor: StringListEditor) -> None:
    """A list that scrolls inside a page that scrolls is two scrollbars and a list to scroll *to*.

    **Test steps:**

    * verify the editor's view is a `ContentSizedListView`
    * verify the editor itself never asks for more height than its contents need
    """
    assert isinstance(inner_view(editor), ContentSizedListView)
    assert editor.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum


def test_the_view_stays_level_with_the_first_button_however_short_it_is(editor: StringListEditor) -> None:
    """A one-entry list sits under the header, not floating in the middle of the row.

    The view is sized to its rows, so it is shorter than the button columns beside it -- and a layout
    centres a short item in its cell unless told otherwise.

    **Test steps:**

    * resize the editor tall, then show it holding three entries and then one
    * verify the view's top edge lines up with both button columns' at either length
    """
    editor.resize(600, 400)

    for values in (("one", "two", "three"), ("only",)):
        editor.values = values
        layout = editor.layout()
        assert layout is not None
        layout.activate()
        top = inner_view(editor).geometry().top()
        assert editor.item_actions.geometry().top() == top, f"item column adrift with {len(values)} entries"
        assert editor.ordering_actions.geometry().top() == top, f"ordering column adrift with {len(values)}"


# endregion
