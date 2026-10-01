"""Tests for `ShortcutsPage`: the Shortcuts settings page, a draft keymap over the command registry (#344)."""

from typing import Any

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope, Keymap
from borco_pyside.widgets import KeySequenceRecorder, key_sequence_recorder
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QFocusEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableView,
    QToolButton,
    QWidget,
)
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.shortcuts_settings import shared_shortcuts_settings
from rehuco_agent.settings.ui import shortcuts_page
from rehuco_agent.settings.ui.key_list_editor import KeyListEditor
from rehuco_agent.settings.ui.settings_dialog import SettingsDialog
from rehuco_agent.settings.ui.shortcuts_page import TABLE_FRAME_INDEX, ShortcutsPage
from rehuco_agent.settings.ui.shortcuts_table_model import COMMAND_COLUMN, CONFLICT_COLUMN, KEYS_COLUMN

from rehuco_agent_tests.conftest import FakeSettings

DOCUMENT = (CommandScope.DOCUMENT_FOCUSED,)
WINDOW = (CommandScope.WINDOW, CommandScope.APP_WIDE)

SAVE = Command("test.save", "Save", "Save the focused document", ("Ctrl+S",), DOCUMENT)
OPEN = Command("test.open", "Open", "Open a file from disk", ("Ctrl+O",), WINDOW)
IDLE = Command("test.idle", "Idle", "Does nothing until given a key", (), WINDOW)
LIST = Command(
    "test.list", "List refresh", "Refresh the list", ("F5",), (CommandScope.WIDGET, CommandScope.WINDOW), "list"
)
VIEW = Command("test.view", "View refresh", "Refresh the view", ("F5",), (CommandScope.WIDGET,), "view")


# region helpers


@fixture
def registry(qapp: Any) -> CommandRegistry:
    """A registry of five sample commands -- two of them sharing F5 in different focus groups.

    :param qapp: the application the key classes need.
    :returns: the registry, with the default keymap.
    """
    del qapp
    subject = CommandRegistry()
    subject.register(SAVE, OPEN, IDLE, LIST, VIEW)
    return subject


@fixture
def view_settings(mocker: MockerFixture) -> FakeSettings:
    """The in-memory store the page reads and writes its settings through -- never the real one.

    :param mocker: patches the page module's `persistent_settings`.
    :returns: the store.
    """
    store = FakeSettings()
    mocker.patch.object(shortcuts_page, "persistent_settings", return_value=store)
    return store


@fixture
def page(qtbot: QtBot, registry: CommandRegistry, view_settings: FakeSettings, mocker: MockerFixture) -> ShortcutsPage:
    """A page over the sample registry, whose saves go to a mock and whose conflict question never opens.

    The question answers *Cancel* unless a test patches it again -- a real modal would block the suite.

    :param qtbot: the widget-owning fixture.
    :param registry: the commands.
    :param view_settings: the store the page persists to.
    :param mocker: patches the question.
    :returns: the page, with the first command selected.
    """
    del view_settings
    mocker.patch.object(key_sequence_recorder, "SETTLE_DELAY_MS", 10)  # a recording settles at once
    widget = ShortcutsPage(registry)
    qtbot.addWidget(widget)
    mocker.patch.object(widget, "confirm_reassign", return_value=False)
    return widget


def child[T: QWidget](page: QWidget, kind: type[T], name: str) -> T:
    """A named child of the page.

    :param page: the page.
    :param kind: its type.
    :param name: its object name.
    :returns: the child.
    """
    found = page.findChild(kind, name)
    assert found is not None
    return found


def row_of(page: ShortcutsPage, name: str) -> int:
    """The table row showing a command.

    :param page: the page.
    :param name: the command's display name.
    :returns: the row.
    """
    model = child(page, QTableView, "shortcuts_table").model()
    return next(row for row in range(model.rowCount()) if model.index(row, COMMAND_COLUMN).data() == name)


def select(page: ShortcutsPage, name: str) -> None:
    """Make the row of a command current.

    :param page: the page.
    :param name: the command's display name.
    """
    child(page, QTableView, "shortcuts_table").selectRow(row_of(page, name))


def keys_editor(page: ShortcutsPage) -> KeyListEditor:
    """The selected command's key buttons.

    :param page: the page.
    :returns: the editor.
    """
    return child(page, KeyListEditor, "keys_editor")


def cell(page: ShortcutsPage, name: str, column: int) -> str:
    """What a column shows for a command.

    :param page: the page.
    :param name: the command's display name.
    :param column: the column.
    :returns: the cell text.
    """
    model = child(page, QTableView, "shortcuts_table").model()
    return str(model.index(row_of(page, name), column).data() or "")


def record(
    qtbot: QtBot, button: KeySequenceRecorder | QToolButton, key: Qt.Key, modifiers: Qt.KeyboardModifier
) -> None:
    """Click a key button -- or the add button, which opens one -- and press one chord into it, waiting for
    the recording to settle.

    :param qtbot: waits on the signal.
    :param button: the key button, or the add button.
    :param key: the key.
    :param modifiers: the modifiers held.
    """
    button.click()
    if isinstance(button, QToolButton):
        editor = button.parentWidget()
        assert isinstance(editor, KeyListEditor)
        pending = editor.pending_button
        assert pending is not None
        button = pending
    with qtbot.waitSignal(button.recorded, timeout=3000):
        QApplication.sendEvent(button, QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


def native(text: str) -> str:
    """A key's native spelling.

    :param text: portable key text.
    :returns: the platform's spelling of it.
    """
    return QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)


# endregion

# region ShortcutsPage tests


def test_the_table_fills_the_page_and_the_editor_stays_below(page: ShortcutsPage) -> None:
    """The table frame takes the stretch, so the editor is never pushed out of view.

    **Test steps:**

    * read the root layout's stretch factors
    """
    layout = page.layout()
    assert isinstance(layout, QBoxLayout)
    assert layout.stretch(TABLE_FRAME_INDEX) == 1
    assert layout.stretch(TABLE_FRAME_INDEX + 1) == 0


def test_selecting_a_command_fills_the_editor(page: ShortcutsPage) -> None:
    """Title, scope, default keys and key buttons follow the selected row.

    **Test steps:**

    * select Open
    * verify each editor field
    """
    select(page, "Open")

    assert OPEN.description in child(page, QLabel, "selected_frame_label").text()
    combo = child(page, QComboBox, "scope_combo")
    assert [combo.itemText(row) for row in range(combo.count())] == [scope.label for scope in OPEN.scopes]
    assert combo.isEnabled()
    assert child(page, QLabel, "default_keys_label").text() == native("Ctrl+O")
    assert keys_editor(page).keys == (QKeySequence("Ctrl+O"),)


def test_a_single_scope_shows_disabled_and_a_keyless_default_reads_none(page: ShortcutsPage) -> None:
    """With one scope there is nothing to choose; with no declared keys the default says so.

    **Test steps:**

    * select Save and verify its combo is disabled, showing its one scope
    * select Idle and verify its default reads None and it has no key buttons
    """
    select(page, "Save")
    combo = child(page, QComboBox, "scope_combo")
    assert not combo.isEnabled()
    assert combo.currentText() == CommandScope.DOCUMENT_FOCUSED.label

    select(page, "Idle")
    assert child(page, QLabel, "default_keys_label").text() == "None"
    assert keys_editor(page).keys == ()


def test_adding_a_key_shows_in_the_table_and_reaches_the_action_after_save(
    page: ShortcutsPage, registry: CommandRegistry, qtbot: QtBot
) -> None:
    """The add button records a second key; saving puts both on the bound action.

    **Test steps:**

    * bind an action to Save and select Save
    * record ``Ctrl+Alt+S`` with the add button, then save
    * verify the Keys column, the stored keymap and the action's shortcuts
    """
    action = QAction("Save")
    registry.bind(action, SAVE.id)
    select(page, "Save")

    modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    record(qtbot, keys_editor(page).add_button, Qt.Key.Key_S, modifiers)
    assert cell(page, "Save", KEYS_COLUMN) == f"{native('Ctrl+S')}; {native('Ctrl+Alt+S')}"
    assert page.is_dirty()
    page.save_changes()

    expected = (QKeySequence("Ctrl+S"), QKeySequence("Ctrl+Alt+S"))
    assert shared_shortcuts_settings().keymap.keys[SAVE.id] == expected
    assert action.shortcuts() == list(expected)
    assert not page.is_dirty()


def test_re_recording_a_key_replaces_it_and_keeps_the_keypad_apart(page: ShortcutsPage, qtbot: QtBot) -> None:
    """Clicking a key button replaces that key; a keypad 5 records as ``Num+5``, not ``5``.

    **Test steps:**

    * select Open and re-record its key as keypad 5
    * verify the one key is ``Num+5``
    """
    select(page, "Open")

    record(qtbot, keys_editor(page).key_buttons()[0], Qt.Key.Key_5, Qt.KeyboardModifier.KeypadModifier)

    assert keys_editor(page).keys == (QKeySequence("Num+5"),)
    assert keys_editor(page).keys[0] != QKeySequence("5")


def test_clicking_away_from_a_recording_key_button_cancels_it(page: ShortcutsPage, qtbot: QtBot) -> None:
    """A key button records only while it has focus: focus moving elsewhere cancels and changes nothing.

    **Test steps:**

    * select Open, click its key button, then send it a focus-out
    * verify ``cancelled`` fired and the key is unchanged
    """
    select(page, "Open")
    button = keys_editor(page).key_buttons()[0]
    button.click()

    with qtbot.waitSignal(button.cancelled, timeout=500):
        QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason))

    assert keys_editor(page).keys == (QKeySequence("Ctrl+O"),)
    assert not page.is_dirty()


def test_the_remove_button_drops_a_key(page: ShortcutsPage) -> None:
    """A key's ✕ removes it, leaving the command with an explicit "no keys".

    **Test steps:**

    * select Open and click its key's ✕
    * verify no keys, an empty Keys cell and a dirty page
    """
    select(page, "Open")

    keys_editor(page).remove_buttons()[0].click()

    assert keys_editor(page).keys == ()
    assert cell(page, "Open", KEYS_COLUMN) == ""
    assert page.is_dirty()


def test_a_taken_key_asks_and_cancel_changes_nothing(page: ShortcutsPage, qtbot: QtBot) -> None:
    """Recording another command's key asks first; Cancel leaves the draft as it was.

    **Test steps:**

    * select Idle and record ``Ctrl+O``, which Open holds; the question answers Cancel
    * verify the question named Open, and nothing changed
    """
    select(page, "Idle")

    record(qtbot, keys_editor(page).add_button, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)

    ask: Any = page.confirm_reassign
    ask.assert_called_once()
    assert ask.call_args.args[0] == [(OPEN, QKeySequence("Ctrl+O"))]
    assert keys_editor(page).keys == ()
    assert not page.is_dirty()


def test_a_taken_key_reassigned_moves_it(page: ShortcutsPage, qtbot: QtBot, mocker: MockerFixture) -> None:
    """Reassign gives the key to the edited command and takes it from the other, with no conflict left.

    **Test steps:**

    * make the question answer Reassign
    * select Idle and record ``Ctrl+O``
    * verify Idle has it, Open has nothing, and the page can save
    """
    mocker.patch.object(page, "confirm_reassign", return_value=True)
    select(page, "Idle")

    record(qtbot, keys_editor(page).add_button, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)

    assert keys_editor(page).keys == (QKeySequence("Ctrl+O"),)
    assert cell(page, "Open", KEYS_COLUMN) == ""
    assert cell(page, "Open", CONFLICT_COLUMN) == ""
    assert page.can_save()


def test_a_scope_change_that_collides_asks_and_cancel_puts_the_combo_back(page: ShortcutsPage) -> None:
    """Moving a command into a scope where its key is taken asks; Cancel reverts the combo.

    **Test steps:**

    * select List refresh, whose F5 is shared with View refresh only through different focus groups
    * pick the window scope, where the focus groups no longer keep them apart; the question answers Cancel
    * verify the question named View refresh, and the combo and draft still hold the widget scope
    """
    select(page, "List refresh")
    combo = child(page, QComboBox, "scope_combo")

    combo.setCurrentIndex(1)
    combo.activated.emit(1)

    ask: Any = page.confirm_reassign
    assert ask.call_args.args[0] == [(VIEW, QKeySequence("F5"))]
    assert combo.currentIndex() == 0
    assert not page.is_dirty()


def test_the_editor_apply_saves_only_the_selected_command(page: ShortcutsPage) -> None:
    """The editor's Apply commits the selected command and leaves the rest of the draft staged.

    **Test steps:**

    * remove Save's key and Open's key
    * select Open and trigger the editor's Apply
    * verify only Open is saved, and the page is still dirty with Save's edit
    """
    select(page, "Save")
    keys_editor(page).remove_buttons()[0].click()
    select(page, "Open")
    keys_editor(page).remove_buttons()[0].click()

    page.editor_header.apply_action.trigger()

    assert shared_shortcuts_settings().keymap.keys == {OPEN.id: ()}
    assert page.is_dirty()


def test_the_editor_reset_and_defaults_restore_one_command(page: ShortcutsPage) -> None:
    """Defaults puts the declared keys back, Reset the saved ones -- for the selected command only.

    **Test steps:**

    * give Open no keys and save
    * Defaults: verify ``Ctrl+O`` is back in the draft
    * Reset: verify the saved "no keys" is back and the page is clean
    """
    select(page, "Open")
    keys_editor(page).remove_buttons()[0].click()
    page.save_changes()

    page.editor_header.defaults_action.trigger()
    assert keys_editor(page).keys == (QKeySequence("Ctrl+O"),)

    page.editor_header.reset_action.trigger()
    assert keys_editor(page).keys == ()
    assert not page.is_dirty()


def test_the_editor_defaults_asks_when_the_default_key_was_taken(
    page: ShortcutsPage, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Restoring a command's default key that another command has since taken goes through the question.

    **Test steps:**

    * move ``Ctrl+O`` from Open to Idle (answering Reassign)
    * select Open, answer Cancel, and trigger the editor's Defaults
    * verify the question was asked and Open still has no keys
    """
    mocker.patch.object(page, "confirm_reassign", return_value=True)
    select(page, "Idle")
    record(qtbot, keys_editor(page).add_button, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    asked = mocker.patch.object(page, "confirm_reassign", return_value=False)

    select(page, "Open")
    page.editor_header.defaults_action.trigger()

    asked.assert_called_once()
    assert keys_editor(page).keys == ()


def test_seeding_defaults_clears_every_override_on_save(page: ShortcutsPage) -> None:
    """The frame's Defaults is a staged edit; saving it drops every override.

    **Test steps:**

    * override two commands and save
    * seed the defaults and verify the page is dirty
    * save and verify no override is left
    """
    select(page, "Open")
    keys_editor(page).remove_buttons()[0].click()
    select(page, "Save")
    keys_editor(page).remove_buttons()[0].click()
    page.save_changes()
    assert len(shared_shortcuts_settings().keymap.keys) == 2

    page.seed_defaults()
    assert page.is_dirty()
    page.save_changes()

    assert shared_shortcuts_settings().keymap == Keymap()
    assert not page.is_dirty()


def test_dropping_changes_discards_the_draft(page: ShortcutsPage) -> None:
    """``drop_changes`` goes back to the saved keymap, and the editor follows.

    **Test steps:**

    * remove Open's key
    * drop the changes
    * verify the page is clean and the editor shows the saved key
    """
    select(page, "Open")
    keys_editor(page).remove_buttons()[0].click()

    page.drop_changes()

    assert not page.is_dirty()
    assert keys_editor(page).keys == (QKeySequence("Ctrl+O"),)


def test_a_scope_choice_is_saved(page: ShortcutsPage, registry: CommandRegistry) -> None:
    """Picking the app-wide scope is a draft edit that save writes and puts in force.

    **Test steps:**

    * select Open and pick its second scope
    * save
    * verify the keymap and the registry hold the scope
    """
    select(page, "Open")
    child(page, QComboBox, "scope_combo").activated.emit(1)
    assert page.is_dirty()

    page.save_changes()

    assert shared_shortcuts_settings().keymap.scopes[OPEN.id] == CommandScope.APP_WIDE
    assert registry.scope(OPEN.id) == CommandScope.APP_WIDE


def test_the_search_box_narrows_the_table(page: ShortcutsPage) -> None:
    """Typing in the search box filters the rows, and does not make the page dirty.

    **Test steps:**

    * type ``disk`` in the search box
    * verify one row is left and the page is clean
    """
    child(page, QLineEdit, "search_edit").setText("disk")

    assert child(page, QTableView, "shortcuts_table").model().rowCount() == 1
    assert not page.is_dirty()


def test_inside_the_dialog_the_editor_keeps_its_own_header(
    qtbot: QtBot, registry: CommandRegistry, view_settings: FakeSettings
) -> None:
    """The dialog wraps the table frame, whose value is the draft, and leaves the editor's own header alone.

    **Test steps:**

    * register the page in a dialog
    * verify the table frame's label moved into a dialog-built header, and the editor's is the page's own
    """
    del view_settings
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    page = ShortcutsPage(registry)
    dialog.add_page("Shortcuts", page)

    table_label = child(page, QLabel, "shortcuts_frame_label")
    editor_label = child(page, QLabel, "selected_frame_label")
    assert table_label.parentWidget() is not child(page, QWidget, "shortcuts_frame")
    assert editor_label.parentWidget() is page.editor_header


def test_cancelling_an_added_key_takes_its_button_away(page: ShortcutsPage, qtbot: QtBot) -> None:
    """The add button opens a recording key button; clicking elsewhere cancels it and it goes.

    **Test steps:**

    * select Open and click the add button
    * verify a recording key button appeared
    * send it a focus-out and verify it is gone and the keys are unchanged
    """
    select(page, "Open")
    editor = keys_editor(page)

    editor.add_button.click()
    pending = editor.pending_button
    assert pending is not None
    assert pending.is_recording

    with qtbot.waitSignal(pending.cancelled, timeout=500):
        QApplication.sendEvent(pending, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason))

    assert editor.pending_button is None
    assert editor.keys == (QKeySequence("Ctrl+O"),)


def test_the_add_and_remove_buttons_are_borderless_icon_buttons(page: ShortcutsPage) -> None:
    """Like a frame header's buttons: icon only, raised (bordered) only under the mouse.

    **Test steps:**

    * select Open
    * verify the add button and the key's remove button are auto-raised, icon-only, with an icon
    """
    select(page, "Open")
    editor = keys_editor(page)

    for button in (editor.add_button, editor.remove_buttons()[0]):
        assert button.autoRaise()
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert not button.icon().isNull()


def test_clicking_a_header_sorts_the_table(page: ShortcutsPage) -> None:
    """The columns sort; the declared order is the default.

    **Test steps:**

    * read the command column in declared order
    * sort it descending and verify it reads reversed-alphabetical
    """
    view = child(page, QTableView, "shortcuts_table")
    model = view.model()

    def names() -> list[str]:
        return [str(model.index(row, COMMAND_COLUMN).data()) for row in range(model.rowCount())]

    assert names() == ["Save", "Open", "Idle", "List refresh", "View refresh"]

    view.sortByColumn(COMMAND_COLUMN, Qt.SortOrder.DescendingOrder)

    assert names() == sorted(names(), reverse=True)


def test_the_search_text_and_sort_survive_a_new_page(
    qtbot: QtBot, registry: CommandRegistry, page: ShortcutsPage
) -> None:
    """What the page was showing comes back on the next one -- both read the fixture's one store.

    **Test steps:**

    * type a search and sort by the Keys column descending
    * build a second page over the same store
    * verify its search box, its filtered rows and its sort indicator match
    """
    child(page, QLineEdit, "search_edit").setText("refresh")
    child(page, QTableView, "shortcuts_table").sortByColumn(KEYS_COLUMN, Qt.SortOrder.DescendingOrder)

    second = ShortcutsPage(registry)
    qtbot.addWidget(second)

    assert child(second, QLineEdit, "search_edit").text() == "refresh"
    view = child(second, QTableView, "shortcuts_table")
    assert view.model().rowCount() == 2
    header: QHeaderView = view.horizontalHeader()
    assert header.sortIndicatorSection() == KEYS_COLUMN
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder


def conflicting_draft() -> Keymap:
    """A keymap giving Open and Idle the same key in the same scope -- what a path that skipped the question
    could leave behind.

    :returns: the keymap.
    """
    keymap = Keymap()
    keymap.set_keys(OPEN, [QKeySequence("Ctrl+K")])
    keymap.set_keys(IDLE, [QKeySequence("Ctrl+K")])
    return keymap


def test_a_page_over_no_commands_selects_nothing(qtbot: QtBot, view_settings: FakeSettings) -> None:
    """With nothing to list there is nothing to select, and the editor says so.

    **Test steps:**

    * build a page over an empty registry
    * verify the editor frame is disabled and carries the no-selection title
    """
    del view_settings
    empty = ShortcutsPage(CommandRegistry())
    qtbot.addWidget(empty)

    assert not child(empty, QWidget, "selected_frame").isEnabled()
    assert child(empty, QLabel, "selected_frame_label").text() == "Select a command"


def test_a_conflicted_draft_is_not_saved(page: ShortcutsPage) -> None:
    """The net under the question: a draft with two commands on one key refuses to save.

    **Test steps:**

    * write a conflicting keymap into the table's value
    * verify ``can_save`` is false, and ``save_changes`` leaves the saved keymap alone
    """
    child(page, QTableView, "shortcuts_table").set_settings_value(conflicting_draft())  # type: ignore[attr-defined]

    assert not page.can_save()
    page.save_changes()

    assert shared_shortcuts_settings().keymap == Keymap()


def test_the_editor_apply_refuses_a_conflicted_result(page: ShortcutsPage) -> None:
    """Applying one command whose draft collides still saves nothing.

    **Test steps:**

    * save Open on ``Ctrl+K``, then stage a draft giving Idle the same key, and select Idle
    * trigger the editor's Apply (the button is disabled, so the signal is sent directly)
    * verify the saved keymap is untouched: Idle's key would collide with Open's
    """
    table = child(page, QTableView, "shortcuts_table")
    saved = Keymap()
    saved.set_keys(OPEN, [QKeySequence("Ctrl+K")])
    table.set_settings_value(saved)  # type: ignore[attr-defined]
    page.save_changes()
    table.set_settings_value(conflicting_draft())  # type: ignore[attr-defined]
    select(page, "Idle")

    page.editor_header.apply_action.triggered.emit()

    assert shared_shortcuts_settings().keymap == saved


def test_every_editor_action_does_nothing_without_a_selection(page: ShortcutsPage) -> None:
    """With the search matching nothing no command is current, and the editor's handlers are inert.

    **Test steps:**

    * search for text no command has
    * send every editor signal
    * verify the page is still clean
    """
    child(page, QLineEdit, "search_edit").setText("zzz no such command")
    assert child(page, QTableView, "shortcuts_table").model().rowCount() == 0

    child(page, QComboBox, "scope_combo").activated.emit(0)
    keys_editor(page).key_recorded.emit(-1, QKeySequence("F9"))
    keys_editor(page).key_removed.emit(0)
    page.editor_header.apply_action.triggered.emit()
    page.editor_header.reset_action.triggered.emit()
    page.editor_header.defaults_action.triggered.emit()

    assert not page.is_dirty()
    assert not child(page, QWidget, "selected_frame").isEnabled()


def test_the_reassign_question_names_what_it_takes_and_answers_by_button(
    page: ShortcutsPage, mocker: MockerFixture
) -> None:
    """The real question lists each taken key and its owner, and is true only for the Reassign button.

    **Test steps:**

    * replace the message box with a stand-in whose clicked button the test chooses
    * ask with Reassign clicked, then with Cancel clicked
    * verify the text names Open and its key, and the answers are True then False
    """
    box = mocker.patch.object(shortcuts_page, "QMessageBox")
    instance = box.return_value
    reassign = mocker.MagicMock()
    instance.addButton.side_effect = [reassign, mocker.MagicMock()]
    instance.clickedButton.return_value = reassign

    assert ShortcutsPage.confirm_reassign(page, [(OPEN, QKeySequence("Ctrl+O"))]) is True

    shown = box.call_args.args[2]
    assert f'"{native("Ctrl+O")}" is already used by "Open".' == shown
    instance.setInformativeText.assert_called_with('Reassigning removes it from "Open".')
    instance.exec.assert_called_once()

    instance.addButton.side_effect = [reassign, mocker.MagicMock()]
    instance.clickedButton.return_value = mocker.MagicMock()
    assert ShortcutsPage.confirm_reassign(page, [(OPEN, QKeySequence("Ctrl+O"))]) is False
    assert QMessageBox is not None  # the real class is only patched on the page's module


def test_adding_a_key_while_one_is_being_recorded_opens_no_second_button(page: ShortcutsPage) -> None:
    """One recording at a time: a second click on add while a new key button is open does nothing.

    **Test steps:**

    * select Open and click the add button twice
    * verify the same pending button is still the only one
    """
    select(page, "Open")
    editor = keys_editor(page)

    editor.add_button.click()
    first = editor.pending_button
    editor.add_button.click()

    assert first is not None
    assert editor.pending_button is first
    assert len(editor.findChildren(KeySequenceRecorder, "pending_key_button")) == 1


# endregion
