"""Tests for RootLayoutsEditor and its tables: a root's layouts and fallbacks, edited (#578, #637)."""

from PySide6.QtCore import QPersistentModelIndex, Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QStyleOptionViewItem, QTableView
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_layouts_editor import RootLayoutsEditor
from rehuco_agent.rehuco.string_map_editor import MapChoicesDelegate, StringMapEditor
from rehuco_agent.rehuco.string_map_model import KEY_COLUMN, VALUE_COLUMN
from rehuco_agent.settings.root_layout_templates_settings import shared_root_layout_templates_settings
from rehuco_core import DEFAULT_PLUGIN_REGISTRY, PLACEHOLDERS

LIBRARY = ("{authors}/{title}", "{publisher}/{title}{{ ({count})}}", "{author}/{title}")
"""A library of templates: one every type accepts, one only a type with a count does, one naming no placeholder."""


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

    * retype a layout, then the fallback of authors
    * verify an announcement for each and the maps read back
    """
    layouts, fallbacks = tables(editor)

    with qtbot.waitSignal(editor.edited):
        layouts.model.setData(layouts.model.index(0, VALUE_COLUMN), "{title}")
    with qtbot.waitSignal(editor.edited):
        fallbacks.model.setData(fallbacks.model.index(PLACEHOLDERS.index("authors"), VALUE_COLUMN), "Anonymous")

    assert (editor.layouts, editor.fallbacks) == ({"tutorial": "{title}"}, {"authors": "Anonymous"})


def test_the_layouts_type_is_picked_from_the_installed_types_or_typed(qtbot: QtBot, editor: RootLayoutsEditor) -> None:
    """A layout's type is edited in a combo of ``*`` and every installed type, which takes other text too; its
    template in a combo of ``*`` and the library, and a fallback's text in a plain field.

    **Test steps:**

    * open the editor of the layout's type and read its choices, pick another and write it back
    * open the template's editor, and the fallback text's
    * verify the combo and its choices, the value written, a combo of ``*`` alone for the template of an empty library,
      and a plain field for the fallback
    """
    layouts, fallbacks = tables(editor)
    delegate = view(layouts).itemDelegate()
    assert isinstance(delegate, MapChoicesDelegate)
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
    assert isinstance(field, QComboBox) and field.isEditable()
    assert [field.itemText(row) for row in range(field.count())] == ["*"]
    fallback = fallbacks.model.index(0, VALUE_COLUMN)
    plain = view(fallbacks).itemDelegate().createEditor(view(fallbacks).viewport(), QStyleOptionViewItem(), fallback)
    qtbot.addWidget(plain)
    assert isinstance(plain, QLineEdit)
    fallback_delegate = view(fallbacks).itemDelegate()
    fallback_delegate.setEditorData(plain, fallback)
    plain.setText("Anonymous")
    fallback_delegate.setModelData(plain, fallbacks.model, fallback)
    assert editor.fallbacks == {"title": "Anonymous", "authors": "Unknown"}


def template_choices(qtbot: QtBot, editor: RootLayoutsEditor, key: str) -> list[str]:
    """What the template drop-down of a layout of this type offers.

    :param qtbot: pytest-qt fixture.
    :param editor: the editor.
    :param key: the layout's type.
    :returns: the combo's items.
    """
    layouts, _ = tables(editor)
    editor.set_values({key: "*"}, {})
    template = layouts.model.index(0, VALUE_COLUMN)
    combo = view(layouts).itemDelegate().createEditor(view(layouts).viewport(), QStyleOptionViewItem(), template)
    qtbot.addWidget(combo)
    assert isinstance(combo, QComboBox)
    return [combo.itemText(row) for row in range(combo.count())]


def test_the_template_drop_down_offers_star_then_the_library_templates_the_type_accepts(
    qtbot: QtBot, editor: RootLayoutsEditor
) -> None:
    """Each row's drop-down is ``*`` and the library's templates valid for that row's type, in library order: ``*``
    takes only the base placeholders, a type with a count also the templates naming it, and one that names an
    unknown placeholder is offered nowhere (#637).

    **Test steps:**

    * put three templates in the library: one of the base placeholders, one naming ``{count}``, one with a typo
    * read the drop-down of a ``*`` row, a ``tutorial`` row and a ``reference_images`` row
    * verify the base template for the first two, both for the third, and the typo in none
    """
    shared_root_layout_templates_settings().templates = LIBRARY

    assert template_choices(qtbot, editor, "*") == ["*", LIBRARY[0]]
    assert template_choices(qtbot, editor, "tutorial") == ["*", LIBRARY[0]]
    assert template_choices(qtbot, editor, "reference_images") == ["*", LIBRARY[0], LIBRARY[1]]


def test_a_star_row_of_the_library_is_not_offered_a_second_time(qtbot: QtBot, editor: RootLayoutsEditor) -> None:
    """The drop-down has ``*`` already, so a ``*`` the library holds, flagged there, adds nothing (#637).

    **Test steps:**

    * put a ``*`` and a template in the library
    * verify the drop-down offers ``*`` once, then the template
    """
    shared_root_layout_templates_settings().templates = ("*", LIBRARY[0])

    assert template_choices(qtbot, editor, "tutorial") == ["*", LIBRARY[0]]


def test_a_template_invalid_for_its_type_is_flagged_and_still_saved_as_typed(editor: RootLayoutsEditor) -> None:
    """A template the type cannot use is coloured with the reason as its tooltip, and kept (#637).

    **Test steps:**

    * set layouts of a typo for ``tutorial``, of ``{count}`` for ``*``, of ``{count}`` for ``reference_images``, and
      of ``*`` for another type
    * verify the first two have a warning colour and a reason, the last two have neither
    * verify all four are read back as typed
    """
    layouts, _ = tables(editor)
    typed = {"tutorial": "{author}", "*": "{count}", "reference_images": "{count}", "other": "*"}
    editor.set_values(typed, {})

    def flagged(row: int) -> tuple[bool, bool]:
        index = layouts.model.index(row, VALUE_COLUMN)
        return (
            index.data(Qt.ItemDataRole.ForegroundRole) is not None,
            bool(index.data(Qt.ItemDataRole.ToolTipRole)),
        )

    assert [flagged(row) for row in range(4)] == [(True, True), (True, True), (False, False), (False, False)]
    assert editor.layouts == typed


def test_the_fallbacks_are_one_fixed_row_per_placeholder_and_only_what_is_filled_is_kept(
    editor: RootLayoutsEditor,
) -> None:
    """The fallbacks table always lists the five placeholders, whatever the root holds, with only *When empty*
    editable; an empty one is not written, and a key of no placeholder is dropped (#637).

    **Test steps:**

    * show fallbacks of authors and of a key that is no placeholder
    * verify five rows named as the placeholders, the key column read-only and the value column editable
    * verify only the authors fallback is read back, and that an empty cell leaves it out again
    """
    _, fallbacks = tables(editor)
    editor.set_values({}, {"authors": "Unknown", "colour": "Red"})
    model = fallbacks.model

    assert [model.index(row, KEY_COLUMN).data() for row in range(model.rowCount())] == list(PLACEHOLDERS)
    assert not model.flags(model.index(0, KEY_COLUMN)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, VALUE_COLUMN)) & Qt.ItemFlag.ItemIsEditable
    assert editor.fallbacks == {"authors": "Unknown"}

    model.setData(model.index(PLACEHOLDERS.index("authors"), VALUE_COLUMN), "")
    assert editor.fallbacks == {}


def test_the_fallbacks_table_cannot_grow_and_keeps_the_layouts_buttons_width(editor: RootLayoutsEditor) -> None:
    """No row can be added, duplicated or removed from the fallbacks, and the table is as wide as the layouts table
    above it, the width of its button column kept (#637).

    **Test steps:**

    * ask the fallbacks table to insert, remove, duplicate and delete a row
    * verify five rows still, and the three actions hidden
    * verify both button columns have the same width
    """
    layouts, fallbacks = tables(editor)
    model = fallbacks.model

    assert not model.insertRow(0)
    assert not model.removeRow(0)
    fallbacks.item_actions.duplicate_action.trigger()
    fallbacks.item_actions.delete_action.trigger()

    assert model.rowCount() == len(PLACEHOLDERS)
    assert not any(
        action.isVisible()
        for action in (
            fallbacks.item_actions.insert_action,
            fallbacks.item_actions.duplicate_action,
            fallbacks.item_actions.delete_action,
        )
    )
    assert fallbacks.item_actions.width() == layouts.item_actions.sizeHint().width()


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


def test_a_map_choices_delegate_with_no_choices_edits_keys_in_a_plain_field(qtbot: QtBot) -> None:
    """With nothing to offer, the key column is a plain field too.

    **Test steps:**

    * open a key's editor through a delegate given no choices
    * verify a line edit
    """
    editor = StringMapEditor()
    qtbot.addWidget(editor)
    editor.mapping = {"a": "b"}
    delegate = MapChoicesDelegate(editor)

    field = delegate.createEditor(editor, QStyleOptionViewItem(), QPersistentModelIndex(editor.model.index(0, 0)))
    qtbot.addWidget(field)

    assert isinstance(field, QLineEdit)
