"""Tests for ScreenshotNamePatternsEditor: the one-column patterns editor's own behaviour (#53, #287)."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLineEdit
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.screenshot_name_patterns_editor import ScreenshotNamePatternsEditor
from rehuco_agent.settings.ui.screenshot_name_patterns_model import PATTERN_COLUMN
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> ScreenshotNamePatternsEditor:
    """An editor holding the shipped patterns.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the editor.
    """
    editor = ScreenshotNamePatternsEditor()
    qtbot.addWidget(editor)
    editor.values = SCREENSHOT_NAME_PATTERNS
    # a shortcut armed on the view, and an in-place editor's keystrokes, only land once the widget is
    # really on screen -- so wait for the show rather than firing it and moving on, the same wait
    # `test_string_list_editor.py` makes for the same reason (offscreen exposes for real)
    with qtbot.waitExposed(editor):
        editor.show()
    return editor


def test_the_editor_is_the_shared_list_machinery_over_a_table(editor: ScreenshotNamePatternsEditor) -> None:
    """Everything about *how* the list is edited comes from the base, which is why this page and the
    string-list pages behave alike.

    **Test steps:**

    * verify the editor is an `ItemListEditor` over a content-sized table
    """
    assert isinstance(editor, ItemListEditor)
    assert isinstance(editor.view, ContentSizedTableView)


def test_values_round_trip_exactly_as_typed(editor: ScreenshotNamePatternsEditor) -> None:
    """The editor holds what was typed; normalizing is the settings object's.

    **Test steps:**

    * set patterns whose text carries whitespace
    * verify they come back untouched
    """
    patterns = (ScreenshotNamePattern(" ^shot-(\\d+)$ "),)
    editor.values = patterns

    assert editor.values == patterns


def test_reset_is_hidden_when_there_is_nothing_to_restore(editor: ScreenshotNamePatternsEditor) -> None:
    """An empty default set means Reset would offer to empty the list, which is not a restore.

    **Test steps:**

    * clear the defaults and verify Reset hides
    * set them again and verify it comes back
    """
    editor.defaults = ()
    assert editor.defaults == ()
    assert editor.item_actions.reset_action.isVisible() is False

    editor.defaults = SCREENSHOT_NAME_PATTERNS
    assert editor.defaults == SCREENSHOT_NAME_PATTERNS
    assert editor.item_actions.reset_action.isVisible() is True


def test_the_keys_fire_while_the_view_has_focus(editor: ScreenshotNamePatternsEditor) -> None:
    """`Ins` adds a pattern and `Del` drops one, from the view -- where somebody editing the list is;
    and an insert dismissed while still blank is undone, the base's rule read off this one-column row.

    **Test steps:**

    * focus the view on the first pattern and press Ins
    * verify a blank pattern landed below it
    * press Escape to abandon the open cell, then Del on the first pattern
    * verify that pattern was dropped
    """
    view = editor.view
    view.setFocus()
    editor.set_current_index(0)
    before = len(editor.values)

    QTest.keySequence(view, QKeySequence(Qt.Key.Key_Insert))
    assert len(editor.values) == before + 1
    assert editor.values[1] == ScreenshotNamePattern("")

    # the insert opens the new pattern cell for typing; dismissing it while still empty undoes the
    # insert (the base's rule). Escape goes to the open cell editor, which holds the focus in the
    # view's stead.
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


def test_delete_edits_the_text_while_a_cell_is_open(editor: ScreenshotNamePatternsEditor) -> None:
    """`Del` mid-edit deletes a character, not the row -- the issue's explicit requirement.

    The shortcuts are armed on the view, and an open in-place editor holds the focus in its stead.

    **Test steps:**

    * open the first pattern's cell and put the cursor at the start of its text
    * press Del
    * verify a character went and every pattern is still there
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

    assert line.text() == SCREENSHOT_NAME_PATTERNS[0].pattern[1:]
    assert len(editor.values) == before


def test_a_click_acts_on_one_whole_pattern(editor: ScreenshotNamePatternsEditor) -> None:
    """A row is one pattern, and multi-select would promise a bulk edit no action here carries out.

    **Test steps:**

    * read the view's selection behaviour and mode
    """
    view = editor.view

    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection


def test_the_column_takes_the_full_width(editor: ScreenshotNamePatternsEditor) -> None:
    """A pattern is unbounded, so its one column takes the whole row.

    **Test steps:**

    * verify the column stretches and nothing scrolls sideways
    """
    table = editor.view
    assert isinstance(table, ContentSizedTableView)
    header = table.horizontalHeader()

    assert header.sectionResizeMode(PATTERN_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
