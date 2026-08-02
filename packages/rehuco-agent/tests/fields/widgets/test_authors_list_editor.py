"""Tests for AuthorsListEditor: the shared list machinery (#231, #97) wearing the ``authors`` columns."""

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QToolButton
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import AuthorsListEditor
from rehuco_agent.fields.widgets.authors_table_model import NAME_COLUMN, URL_COLUMN


# region helpers
@fixture
def editor(qtbot: QtBot) -> AuthorsListEditor:
    """An editor over two entries: one plain name, one record carrying a URL.

    :param qtbot: the widget-owning fixture.
    :returns: the seeded editor.
    """
    widget = AuthorsListEditor()
    qtbot.addWidget(widget)
    widget.set_entries(["Alice", {"name": "Bob", "url": "https://example.com/bob"}])
    return widget


def select(editor: AuthorsListEditor, row: int) -> None:
    """Make ``row`` the current one.

    :param editor: the editor to select in.
    :param row: the row to make current.
    """
    editor.view.setCurrentIndex(editor.model.index(row, NAME_COLUMN))


# endregion


def test_it_is_the_shared_list_machinery(editor: AuthorsListEditor) -> None:
    """The buttons, the keys and the one-model-call rule are the same ones the settings pages get.

    **Test steps:**

    * verify the editor is an `ItemListEditor` over a row-sized table
    """
    assert isinstance(editor, ItemListEditor)
    assert isinstance(editor.view, ContentSizedTableView)


def test_the_entries_round_trip(editor: AuthorsListEditor) -> None:
    """What is set is what is read back, in canonical minimal form.

    **Test steps:**

    * read the seeded entries
    * verify both came back as they went in
    """
    assert editor.entries == ("Alice", {"name": "Bob", "url": "https://example.com/bob"})


def test_an_edit_is_reported_once(editor: AuthorsListEditor) -> None:
    """The model's own signals are what report an edit -- one path in, one path out.

    **Test steps:**

    * record every ``values_changed`` and commit a name through the model
    * verify exactly one edit was reported, carrying the new entry
    """
    edits: list[int] = []
    editor.values_changed.connect(lambda: edits.append(1))

    editor.model.setData(editor.model.index(0, NAME_COLUMN), "Alicia")

    assert edits == [1]
    assert editor.entries[0] == "Alicia"


def test_the_move_actions_reorder_the_authors(editor: AuthorsListEditor) -> None:
    """Credit order is the data, so the ordering column is shown and does the reordering.

    **Test steps:**

    * make the first author current and move it down
    * verify the two swapped
    """
    select(editor, 0)

    editor.ordering_actions.move_down_action.trigger()

    assert editor.entries[1] == "Alice"


def test_delete_drops_the_current_author(editor: AuthorsListEditor) -> None:
    """The item actions act on the current row, exactly as they do for a string list.

    **Test steps:**

    * make the second author current and delete it
    * verify only the first is left
    """
    select(editor, 1)

    editor.item_actions.delete_action.trigger()

    assert editor.entries == ("Alice",)


def test_the_reset_button_is_hidden(editor: AuthorsListEditor) -> None:
    """A default set of authors would be someone else's authors -- Reset is built (every item column
    carries one, wired to the model's no-op `reset()`) but hidden outright, not merely disabled.

    **Test steps:**

    * read the reset action's visibility and its button's
    * verify both are hidden
    """
    reset_action = editor.item_actions.reset_action
    button = next(
        button for button in editor.item_actions.findChildren(QToolButton) if button.defaultAction() is reset_action
    )

    assert reset_action.isVisible() is False
    assert button.isVisible() is False


def test_the_table_shows_one_author_per_row(editor: AuthorsListEditor) -> None:
    """A row is an author: no row numbers, no grid, and both columns sharing the width.

    **Test steps:**

    * read the table's chrome and column resize modes
    * verify rows are selected whole, the vertical header is gone, and both columns stretch
    """
    table = editor.view
    assert isinstance(table, ContentSizedTableView)

    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.verticalHeader().isVisible() is False
    assert table.showGrid() is False
    header = table.horizontalHeader()
    assert header.sectionResizeMode(NAME_COLUMN) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(URL_COLUMN) == QHeaderView.ResizeMode.Stretch
