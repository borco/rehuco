"""Tests for LegacyScreenshotRulesEditor: the two-column rules editor's own behaviour (#53)."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLineEdit
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.legacy_screenshot_rules_editor import LegacyScreenshotRulesEditor
from rehuco_agent.settings.ui.legacy_screenshot_rules_model import (
    COVER_COLUMN,
    REST_COLUMN,
    LegacyScreenshotRulesModel,
)
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> LegacyScreenshotRulesEditor:
    """An editor holding the shipped rules.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the editor.
    """
    editor = LegacyScreenshotRulesEditor()
    qtbot.addWidget(editor)
    editor.values = LEGACY_SCREENSHOT_RULES
    # a shortcut armed on the view, and an in-place editor's keystrokes, only land once the widget is
    # really on screen -- so wait for the show rather than firing it and moving on, the same wait
    # `test_string_list_editor.py` makes for the same reason (offscreen exposes for real)
    with qtbot.waitExposed(editor):
        editor.show()
    return editor


def test_the_editor_is_the_shared_list_machinery_over_a_table(editor: LegacyScreenshotRulesEditor) -> None:
    """Everything about *how* the list is edited comes from the base, which is why this page and the
    string-list pages behave alike.

    **Test steps:**

    * verify the editor is an `ItemListEditor` over a content-sized table
    """
    assert isinstance(editor, ItemListEditor)
    assert isinstance(editor.view, ContentSizedTableView)


def test_a_row_is_blank_only_while_both_cells_are_empty(editor: LegacyScreenshotRulesEditor) -> None:
    """The base abandons an insert whose row is still blank; here that takes both columns, so a rest
    typed without a cover survives.

    **Test steps:**

    * insert a blank rule and check the editor reads it as blank
    * type into its rest cell only
    * verify it is no longer blank
    """
    model = editor.model
    assert isinstance(model, LegacyScreenshotRulesModel)
    row = model.insert(0)
    assert editor.row_is_blank(row) is True

    model.setData(model.index(row, REST_COLUMN), "shot-#")

    assert editor.row_is_blank(row) is False


def test_values_round_trip_exactly_as_typed(editor: LegacyScreenshotRulesEditor) -> None:
    """The editor holds what was typed; normalizing is the settings object's.

    **Test steps:**

    * set rules whose fields carry whitespace
    * verify they come back untouched
    """
    rules = (LegacyScreenshotRule(" shot-1 ", " shot-# "),)
    editor.values = rules

    assert editor.values == rules


def test_reset_is_hidden_when_there_is_nothing_to_restore(editor: LegacyScreenshotRulesEditor) -> None:
    """An empty default set means Reset would offer to empty the list, which is not a restore.

    **Test steps:**

    * clear the defaults and verify Reset hides
    * set them again and verify it comes back
    """
    editor.defaults = ()
    assert editor.defaults == ()
    assert editor.item_actions.reset_action.isVisible() is False

    editor.defaults = LEGACY_SCREENSHOT_RULES
    assert editor.defaults == LEGACY_SCREENSHOT_RULES
    assert editor.item_actions.reset_action.isVisible() is True


def test_the_keys_fire_while_the_view_has_focus(editor: LegacyScreenshotRulesEditor) -> None:
    """`Ins` adds a rule and `Del` drops one, from the view -- where somebody editing the list is.

    The issue asks for both by name. They come from `ItemListEditor`, but this is the first list whose
    rows are more than one cell, so it is worth showing they still reach *these* rows.

    **Test steps:**

    * focus the view on the first rule and press Ins
    * verify a blank rule landed below it
    * press Escape to abandon the open cell, then Del on the first rule
    * verify that rule was dropped
    """
    view = editor.view
    view.setFocus()
    editor.set_current_index(0)
    before = len(editor.values)

    QTest.keySequence(view, QKeySequence(Qt.Key.Key_Insert))
    assert len(editor.values) == before + 1
    assert editor.values[1] == LegacyScreenshotRule("", "")

    # the insert opens the new cover cell for typing; dismissing it with both cells still empty undoes
    # the insert (the base's rule, reached here through the both-cells-empty override). Escape goes to
    # the open cell editor, which holds the focus in the view's stead.
    open_cell = view.viewport().findChild(QLineEdit)
    assert open_cell is not None
    QTest.keyClick(open_cell, Qt.Key.Key_Escape)
    assert len(editor.values) == before

    view.setFocus()
    editor.set_current_index(0)
    first = editor.values[0]
    QTest.keySequence(view, QKeySequence(QKeySequence.StandardKey.Delete))

    assert len(editor.values) == before - 1
    assert first not in editor.values


def test_delete_edits_the_text_while_a_cell_is_open(editor: LegacyScreenshotRulesEditor) -> None:
    """`Del` mid-edit deletes a character, not the row -- the issue's explicit requirement.

    The shortcuts are armed on the view, and an open in-place editor holds the focus in its stead.

    **Test steps:**

    * open the first rule's cover cell and put the cursor at the start of its text
    * press Del
    * verify a character went and every rule is still there
    """
    view = editor.view
    view.setFocus()
    editor.set_current_index(0)
    before = len(editor.values)
    editor.edit_current()
    line = view.viewport().findChild(QLineEdit)
    assert line is not None

    line.setCursorPosition(0)
    QTest.keySequence(line, QKeySequence(QKeySequence.StandardKey.Delete))

    assert line.text() == "0"
    assert len(editor.values) == before


def test_a_click_acts_on_one_whole_rule(editor: LegacyScreenshotRulesEditor) -> None:
    """A row is one rule, and multi-select would promise a bulk edit no action here carries out.

    **Test steps:**

    * read the view's selection behaviour and mode
    """
    view = editor.view

    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection


def test_both_columns_share_the_width(editor: LegacyScreenshotRulesEditor) -> None:
    """A cover and a template are each unbounded, so neither gets to take the row.

    **Test steps:**

    * verify both columns stretch and nothing scrolls sideways
    """
    table = editor.view
    assert isinstance(table, ContentSizedTableView)
    header = table.horizontalHeader()

    assert header.sectionResizeMode(COVER_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(REST_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
