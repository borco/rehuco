"""Tests for `ShortcutsTableModel` and its filter proxy: the draft keymap, shown one command per row (#344)."""

from typing import Any

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope, Keymap
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from pytest import fixture
from rehuco_agent.settings.ui.shortcuts_table_model import (
    COMMAND_COLUMN,
    CONFLICT_COLUMN,
    KEYS_COLUMN,
    SCOPE_COLUMN,
    ShortcutsFilterProxyModel,
    ShortcutsTableModel,
)

DOCUMENT = (CommandScope.DOCUMENT_FOCUSED,)
WINDOW = (CommandScope.WINDOW, CommandScope.APP_WIDE)
WIDGET = (CommandScope.WIDGET,)

SAVE = Command("test.save", "Save", "Save the focused document", ("Ctrl+S",), DOCUMENT)
OPEN = Command("test.open", "Open", "Open a file from disk", ("Ctrl+O",), WINDOW)
IDLE = Command("test.idle", "Idle", "Does nothing until given a key", (), WINDOW)
LIST_REFRESH = Command("test.list", "List refresh", "Refresh the list", ("F5",), WIDGET, "list_group")
VIEW_REFRESH = Command("test.view", "View refresh", "Refresh the view", ("F5",), WIDGET, "view_group")


@fixture
def model(qapp: Any) -> ShortcutsTableModel:
    """A model over five sample commands, on an empty draft.

    :param qapp: the application the key classes need.
    :returns: the model.
    """
    del qapp
    registry = CommandRegistry()
    registry.register(SAVE, OPEN, IDLE, LIST_REFRESH, VIEW_REFRESH)
    subject = ShortcutsTableModel(registry)
    subject.set_draft(registry.keymap)
    return subject


def cell(model: ShortcutsTableModel, row: int, column: int, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
    """One cell's data.

    :param model: the model.
    :param row: the row.
    :param column: the column.
    :param role: the role.
    :returns: what the model answers.
    """
    return model.index(row, column).data(role)


def test_a_row_shows_the_command_its_keys_and_its_scope(model: ShortcutsTableModel) -> None:
    """The four columns read name, keys, scope label and an empty conflict.

    **Test steps:**

    * read the first row
    * verify each column
    """
    assert cell(model, 0, COMMAND_COLUMN) == "Save"
    assert cell(model, 0, KEYS_COLUMN) == QKeySequence("Ctrl+S").toString(QKeySequence.SequenceFormat.NativeText)
    assert cell(model, 0, SCOPE_COLUMN) == CommandScope.DOCUMENT_FOCUSED.label
    assert cell(model, 0, CONFLICT_COLUMN) == ""


def test_an_overridden_row_reads_bold_and_a_default_one_does_not(model: ShortcutsTableModel) -> None:
    """Bold marks a row that differs from its declaration.

    **Test steps:**

    * change one command's keys
    * verify its row is bold and an untouched row is not
    """
    model.set_entry(SAVE.id, [QKeySequence("Ctrl+Shift+S")], SAVE.default_scope)

    assert cell(model, 0, COMMAND_COLUMN, Qt.ItemDataRole.FontRole).bold()
    assert cell(model, 1, COMMAND_COLUMN, Qt.ItemDataRole.FontRole) is None


def test_two_commands_on_one_key_badge_both_rows(model: ShortcutsTableModel) -> None:
    """A collision in overlapping scopes badges both commands and names the other in the tooltip.

    **Test steps:**

    * bind the Open command's key to ``Ctrl+K`` and the Idle command's too (both window scope)
    * verify both Conflict cells name the other, with an error colour and a tooltip
    * verify the model reports conflicts
    """
    model.set_entry(OPEN.id, [QKeySequence("Ctrl+K")], OPEN.default_scope)
    model.set_entry(IDLE.id, [QKeySequence("Ctrl+K")], IDLE.default_scope)

    assert cell(model, 1, CONFLICT_COLUMN) == "Idle"
    assert cell(model, 2, CONFLICT_COLUMN) == "Open"
    assert cell(model, 1, CONFLICT_COLUMN, Qt.ItemDataRole.ForegroundRole) is not None
    assert "Conflicts with Idle" in cell(model, 1, CONFLICT_COLUMN, Qt.ItemDataRole.ToolTipRole)
    assert model.has_conflicts()


def test_the_same_key_in_two_focus_groups_is_not_a_conflict(model: ShortcutsTableModel) -> None:
    """Two widget commands on F5 in different focus groups coexist.

    **Test steps:**

    * read the fixture's two F5 commands
    * verify there is no conflict
    """
    assert not model.has_conflicts()
    assert cell(model, 3, KEYS_COLUMN) == cell(model, 4, KEYS_COLUMN)


def test_a_chord_prefix_is_a_conflict(model: ShortcutsTableModel) -> None:
    """``Ctrl+K`` against ``Ctrl+K, S`` collides, since the first would swallow the start of the second.

    **Test steps:**

    * bind one command to ``Ctrl+K`` and another to ``Ctrl+K, S``
    * verify the model reports a conflict
    """
    model.set_entry(OPEN.id, [QKeySequence("Ctrl+K")], OPEN.default_scope)
    model.set_entry(IDLE.id, [QKeySequence("Ctrl+K, S")], IDLE.default_scope)

    assert model.has_conflicts()


def test_a_scope_choice_is_kept_in_the_draft(model: ShortcutsTableModel) -> None:
    """Choosing another allowed scope shows in the Scope column.

    **Test steps:**

    * set the Open command's scope to app-wide
    * verify the Scope column and ``scope_of``
    """
    model.set_entry(OPEN.id, model.keys_of(OPEN.id), CommandScope.APP_WIDE)

    assert model.scope_of(OPEN.id) == CommandScope.APP_WIDE
    assert cell(model, 1, SCOPE_COLUMN) == CommandScope.APP_WIDE.label


def test_replacing_the_draft_keeps_the_rows_and_says_so(model: ShortcutsTableModel) -> None:
    """A replacement is a ``dataChanged`` plus ``draft_replaced``, never a reset that would drop the selection.

    **Test steps:**

    * listen for resets and replacements
    * replace the draft
    * verify no reset and one replacement
    """
    resets: list[bool] = []
    replaced: list[bool] = []
    model.modelReset.connect(lambda: resets.append(True))
    model.draft_replaced.connect(lambda: replaced.append(True))

    model.set_draft(model.draft())

    assert not resets
    assert replaced == [True]


def test_search_matches_name_description_and_key_text(model: ShortcutsTableModel) -> None:
    """The proxy narrows on any of the three, and on either spelling of a key.

    **Test steps:**

    * filter by a name, by a description word, by native key text and by portable key text
    * verify each leaves exactly the matching row, and a blank filter shows all
    """
    proxy = ShortcutsFilterProxyModel()
    proxy.setSourceModel(model)

    def shown(text: str) -> list[str]:
        proxy.set_filter_text(text)
        return [proxy.index(row, COMMAND_COLUMN).data() for row in range(proxy.rowCount())]

    assert shown("open") == ["Open"]
    assert shown("from disk") == ["Open"]
    assert shown("Ctrl+S") == ["Save"]
    assert shown(QKeySequence("Ctrl+O").toString(QKeySequence.SequenceFormat.NativeText)) == ["Open"]
    assert len(shown("")) == 5


def test_a_filtered_row_stays_while_it_is_edited(model: ShortcutsTableModel) -> None:
    """Editing a row's keys does not drop it from a filtered table, even if it no longer matches.

    **Test steps:**

    * filter on the Save command's key and edit that key
    * verify the row is still shown
    """
    proxy = ShortcutsFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_filter_text("Ctrl+S")

    model.set_entry(SAVE.id, [QKeySequence("Ctrl+Shift+S")], SAVE.default_scope)

    assert proxy.rowCount() == 1


def test_collisions_name_the_other_command_and_its_key(model: ShortcutsTableModel) -> None:
    """A prospective key is checked against every other command in an overlapping scope.

    **Test steps:**

    * ask what giving Idle ``Ctrl+O`` in the window scope would collide with
    * ask the same for ``F5`` in the window scope, against two focus-grouped widget commands
    * verify Open is named with its key, and the widget commands are not
    """
    assert model.collisions(IDLE.id, [QKeySequence("Ctrl+O")], CommandScope.WINDOW) == [(OPEN, QKeySequence("Ctrl+O"))]
    assert model.collisions(IDLE.id, [QKeySequence("F6")], CommandScope.WINDOW) == []


def test_taking_a_key_removes_it_from_the_other_command(model: ShortcutsTableModel) -> None:
    """Reassigning gives the key to one command and takes it from the other, leaving no conflict.

    **Test steps:**

    * give Idle ``Ctrl+O`` with ``take_keys``
    * verify Idle has it, Open has no keys left, and there is no conflict
    """
    model.take_keys(IDLE.id, [QKeySequence("Ctrl+O")], CommandScope.WINDOW)

    assert model.keys_of(IDLE.id) == (QKeySequence("Ctrl+O"),)
    assert model.keys_of(OPEN.id) == ()
    assert not model.has_conflicts()


def test_committing_one_command_brings_the_command_it_took_from(model: ShortcutsTableModel) -> None:
    """A per-command commit of a reassigned key also commits the command that lost it.

    **Test steps:**

    * reassign ``Ctrl+O`` from Open to Idle, and edit Save as well
    * commit Idle alone on top of an empty saved keymap
    * verify Idle and Open are in the result and Save is not
    """
    model.take_keys(IDLE.id, [QKeySequence("Ctrl+O")], CommandScope.WINDOW)
    model.set_entry(SAVE.id, [QKeySequence("Ctrl+Shift+S")], SAVE.default_scope)

    merged = model.committed_with(Keymap(), IDLE.id)

    assert merged.keys[IDLE.id] == (QKeySequence("Ctrl+O"),)
    assert not merged.keys[OPEN.id]  # an explicit "no keys" override, not a missing one
    assert SAVE.id not in merged.keys
