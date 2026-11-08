"""Tests for RootLayoutsEditor and its tables: a root's layouts and fallbacks, edited (#578)."""

from PySide6.QtCore import QPersistentModelIndex
from PySide6.QtWidgets import QComboBox, QLineEdit, QStyleOptionViewItem, QTableView
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_layouts_editor import RootLayoutsEditor
from rehuco_agent.rehuco.string_map_editor import KeyChoicesDelegate, StringMapEditor
from rehuco_agent.rehuco.string_map_model import KEY_COLUMN, VALUE_COLUMN
from rehuco_core import DEFAULT_PLUGIN_REGISTRY


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> RootLayoutsEditor:
    """An editor showing one layout and one fallback.

    :param qtbot: pytest-qt fixture.
    :returns: the editor.
    """
    built = RootLayoutsEditor()
    qtbot.addWidget(built)
    built.set_values({"tutorial": "{authors}/{title}"}, {"authors": "Unknown"})
    return built


def tables(editor: RootLayoutsEditor) -> tuple[StringMapEditor, StringMapEditor]:
    """The layouts table and the fallbacks table.

    :param editor: the editor.
    :returns: both, in that order.
    """
    found = tuple(editor.findChild(StringMapEditor, name) for name in ("layouts_editor", "fallbacks_editor"))
    assert all(table is not None for table in found)
    return found  # type: ignore[return-value]


def view(table: StringMapEditor) -> QTableView:
    """A table's view.

    :param table: the table.
    :returns: its view.
    """
    assert isinstance(table.view, QTableView)
    return table.view


def test_the_values_set_are_shown_without_an_edit_being_announced(qtbot: QtBot) -> None:
    """Filling the tables is what the owner does; only a person's edit is announced.

    **Test steps:**

    * build an editor, listen for edits, and set its values
    * verify the maps read back and nothing was announced
    """
    editor = RootLayoutsEditor()
    qtbot.addWidget(editor)

    with qtbot.assertNotEmitted(editor.edited):
        editor.set_values({"*": "*"}, {"title": "Untitled"})

    assert (editor.layouts, editor.fallbacks) == ({"*": "*"}, {"title": "Untitled"})


def test_an_edit_of_either_table_is_announced_once(qtbot: QtBot, editor: RootLayoutsEditor) -> None:
    """Each table's edit reaches the owner, with the maps as they now are.

    **Test steps:**

    * retype a layout, then a fallback
    * verify an announcement for each and the maps read back
    """
    layouts, fallbacks = tables(editor)

    with qtbot.waitSignal(editor.edited):
        layouts.model.setData(layouts.model.index(0, VALUE_COLUMN), "{title}")
    with qtbot.waitSignal(editor.edited):
        fallbacks.model.setData(fallbacks.model.index(0, VALUE_COLUMN), "Anonymous")

    assert (editor.layouts, editor.fallbacks) == ({"tutorial": "{title}"}, {"authors": "Anonymous"})


def test_the_layouts_type_is_picked_from_the_installed_types_or_typed(qtbot: QtBot, editor: RootLayoutsEditor) -> None:
    """A layout's type is edited in a combo of ``*`` and every installed type, which takes other text too; its
    template, and a fallback's placeholder, in a plain field.

    **Test steps:**

    * open the editor of the layout's type and read its choices, pick another and write it back
    * open the template's editor, and the fallback placeholder's
    * verify the combo and its choices, the value written, and plain fields for the others
    """
    layouts, fallbacks = tables(editor)
    delegate = view(layouts).itemDelegate()
    assert isinstance(delegate, KeyChoicesDelegate)
    key = layouts.model.index(0, KEY_COLUMN)

    combo = delegate.createEditor(view(layouts).viewport(), QStyleOptionViewItem(), key)
    qtbot.addWidget(combo)
    delegate.setEditorData(combo, key)

    assert isinstance(combo, QComboBox) and combo.isEditable()
    assert delegate.choices == ("*", *DEFAULT_PLUGIN_REGISTRY.main_keys)
    assert [combo.itemText(row) for row in range(combo.count())] == list(delegate.choices)
    assert combo.currentText() == "tutorial"
    combo.setCurrentText("reference_images")
    delegate.setModelData(combo, layouts.model, key)
    assert editor.layouts == {"reference_images": "{authors}/{title}"}

    template = layouts.model.index(0, VALUE_COLUMN)
    field = delegate.createEditor(view(layouts).viewport(), QStyleOptionViewItem(), template)
    qtbot.addWidget(field)
    delegate.setEditorData(field, template)
    delegate.setModelData(field, layouts.model, template)
    assert isinstance(field, QLineEdit)
    placeholder = fallbacks.model.index(0, KEY_COLUMN)
    plain = view(fallbacks).itemDelegate().createEditor(view(fallbacks).viewport(), QStyleOptionViewItem(), placeholder)
    qtbot.addWidget(plain)
    assert isinstance(plain, QLineEdit)


def test_f2_is_left_to_the_roots_views_edit_toggle(editor: RootLayoutsEditor) -> None:
    """F2 turns the Roots view's edit mode off from inside these tables, so they neither arm it nor edit on it; and
    a map has no factory value to reset to.

    **Test steps:**

    * read each table's edit shortcut, edit triggers and Reset
    * verify no F2, and Reset hidden
    """
    for table in tables(editor):
        assert table.item_actions.edit_action.shortcut().isEmpty()
        assert not view(table).editTriggers() & QTableView.EditTrigger.EditKeyPressed
        assert not table.item_actions.reset_action.isVisible()


def test_a_key_choices_delegate_with_no_choices_edits_keys_in_a_plain_field(qtbot: QtBot) -> None:
    """With nothing to offer, the key column is a plain field too.

    **Test steps:**

    * open a key's editor through a delegate given no choices
    * verify a line edit
    """
    editor = StringMapEditor()
    qtbot.addWidget(editor)
    editor.mapping = {"a": "b"}
    delegate = KeyChoicesDelegate(editor)

    field = delegate.createEditor(editor, QStyleOptionViewItem(), QPersistentModelIndex(editor.model.index(0, 0)))
    qtbot.addWidget(field)

    assert isinstance(field, QLineEdit)
