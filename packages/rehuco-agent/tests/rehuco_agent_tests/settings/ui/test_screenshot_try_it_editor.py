"""Tests for ScreenshotTryItEditor: the try-it table's own behaviour (#287)."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.screenshot_try_it_editor import ScreenshotTryItEditor
from rehuco_agent.settings.ui.screenshot_try_it_model import FILENAME_COLUMN, NOT_A_SCREENSHOT, SLOT_COLUMN
from rehuco_core import SCREENSHOT_NAME_PATTERNS


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> ScreenshotTryItEditor:
    """An editor with no ordering column, reading no patterns yet -- what Designer constructs.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the editor.
    """
    editor = ScreenshotTryItEditor()
    qtbot.addWidget(editor)
    return editor


def test_the_editor_is_the_shared_list_machinery_over_a_table(editor: ScreenshotTryItEditor) -> None:
    """Everything about *how* the list is edited comes from the base.

    **Test steps:**

    * verify the editor is an `ItemListEditor` over a content-sized table
    """
    assert isinstance(editor, ItemListEditor)
    assert isinstance(editor.view, ContentSizedTableView)


def test_the_ordering_column_is_hidden(editor: ScreenshotTryItEditor) -> None:
    """Sample rows carry no meaningful order -- reordering them changes nothing about a slot.

    **Test steps:**

    * verify the ordering column is hidden
    """
    assert editor.ordering_actions.isHidden() is True


def test_the_patterns_provider_defaults_to_no_match(editor: ScreenshotTryItEditor) -> None:
    """A freshly Designer-constructed editor (parent only, no provider yet) matches nothing rather than
    crashing when its slot column is first read.

    **Test steps:**

    * set one sample and read its slot before a provider is set
    """
    editor.values = ("cover.jpg",)

    assert editor.model.data(editor.model.index(0, SLOT_COLUMN)) == NOT_A_SCREENSHOT


def test_the_patterns_provider_is_set_after_construction_and_read_back(editor: ScreenshotTryItEditor) -> None:
    """The page sets the provider after construction, then refreshes -- the sequence this editor is
    built for; the property reads back what was set.

    **Test steps:**

    * set one recognizable sample
    * point the provider at the shipped patterns, read it back, and refresh
    * verify the slot column now shows a real slot
    """
    editor.values = ("cover.jpg",)
    editor.patterns_provider = lambda: SCREENSHOT_NAME_PATTERNS
    assert editor.patterns_provider() == SCREENSHOT_NAME_PATTERNS

    editor.refresh_slots()

    assert editor.model.data(editor.model.index(0, SLOT_COLUMN)) == "00"


def test_values_round_trip_exactly_as_typed(editor: ScreenshotTryItEditor) -> None:
    """The editor holds what was typed; normalizing is the settings object's.

    **Test steps:**

    * set sample filenames carrying whitespace
    * verify they come back unchanged
    """
    editor.values = (" cover.jpg ", "sample-03.jpg")

    assert editor.values == (" cover.jpg ", "sample-03.jpg")


def test_reset_is_hidden_when_there_is_nothing_to_restore(editor: ScreenshotTryItEditor) -> None:
    """An empty default set means Reset would offer to empty the list, which is not a restore.

    **Test steps:**

    * verify a fresh editor has no defaults and hides Reset
    * set them and verify it comes back
    """
    assert editor.defaults == ()
    assert editor.item_actions.reset_action.isVisible() is False

    editor.defaults = ("cover.jpg",)
    assert editor.defaults == ("cover.jpg",)
    assert editor.item_actions.reset_action.isVisible() is True


def test_a_click_acts_on_one_whole_sample(editor: ScreenshotTryItEditor) -> None:
    """A row is one sample, and multi-select would promise a bulk edit no action here carries out.

    **Test steps:**

    * read the view's selection behaviour and mode
    """
    view = editor.view

    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection


def test_the_filename_column_stretches_and_the_slot_column_does_not(editor: ScreenshotTryItEditor) -> None:
    """The filename is unbounded; the slot is a short fixed answer that never benefits from extra width.

    **Test steps:**

    * verify the filename column stretches and the slot column sizes to its content
    """
    table = editor.view
    assert isinstance(table, ContentSizedTableView)
    header = table.horizontalHeader()

    assert header.sectionResizeMode(FILENAME_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(SLOT_COLUMN) == QHeaderView.ResizeMode.ResizeToContents
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
