"""Tests for LegacyScreenshotRulesEditor: the two-column rules editor's own behaviour (#53)."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView
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
