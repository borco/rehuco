"""Tests for the default root layouts on the Root Catalog settings page: the list of their names, and the maps of the
one selected (#578)."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_layouts_editor import RootLayoutsEditor
from rehuco_agent.rehuco.string_map_editor import StringMapEditor
from rehuco_agent.rehuco.string_map_model import VALUE_COLUMN
from rehuco_agent.settings.root_catalog_settings import DEFAULT_ROOT_LAYOUTS, RootLayout
from rehuco_agent.settings.ui.default_root_layouts_editor import (
    NO_PRESET_SELECTED,
    UNNAMED_PRESET,
    DefaultRootLayoutsEditor,
)
from rehuco_agent.settings.ui.root_layout_list_editor import RootLayoutListEditor
from rehuco_agent.settings.ui.root_layout_list_model import RootLayoutListModel
from rehuco_agent.settings.ui.settings_frame_filter import ValueControl

LAYOUTS = (
    RootLayout("By author", {"tutorial": ("{authors}/{title}",)}, {"authors": "Unknown"}),
    RootLayout("Flat", {"*": ("*",)}, {}),
)


@fixture(name="editor")
def fixture_editor(qtbot: QtBot) -> DefaultRootLayoutsEditor:
    """An editor holding ``LAYOUTS``, the first selected.

    :param qtbot: pytest-qt fixture.
    :returns: the editor.
    """
    built = DefaultRootLayoutsEditor()
    qtbot.addWidget(built)
    built.layouts = LAYOUTS
    return built


def names_editor(editor: DefaultRootLayoutsEditor) -> RootLayoutListEditor:
    """The list of names.

    :param editor: the editor.
    :returns: its list.
    """
    found = editor.findChild(RootLayoutListEditor)
    assert found is not None
    return found


def maps_editor(editor: DefaultRootLayoutsEditor) -> RootLayoutsEditor:
    """The maps of the layout selected.

    :param editor: the editor.
    :returns: its maps editor.
    """
    found = editor.findChild(RootLayoutsEditor)
    assert found is not None
    return found


def test_the_editor_is_one_settings_value_of_every_layout(editor: DefaultRootLayoutsEditor) -> None:
    """The settings dialog snapshots and restores the whole list through it, names and maps together.

    **Test steps:**

    * read its value, write another back, and write something that is no list of layouts
    * verify the protocol, the values, and that the last write changed nothing
    """
    assert isinstance(editor, ValueControl)
    assert editor.settings_value() == LAYOUTS

    editor.set_settings_value(LAYOUTS[1:])
    assert editor.layouts == LAYOUTS[1:]
    editor.set_settings_value("not layouts")
    assert editor.layouts == LAYOUTS[1:]


def test_the_maps_follow_the_layout_selected(editor: DefaultRootLayoutsEditor) -> None:
    """Below the names stand the maps of the layout selected; with none selected they are empty and unusable.

    **Test steps:**

    * read the maps with the first layout selected, select the second, then none
    * verify the maps each time and that they are disabled with none
    """
    maps = maps_editor(editor)
    assert (maps.layouts, maps.fallbacks) == ({"tutorial": ("{authors}/{title}",)}, {"authors": "Unknown"})

    names_editor(editor).set_current_index(1)
    assert (maps.layouts, maps.fallbacks) == ({"*": ("*",)}, {})

    names_editor(editor).set_current_index(-1)
    assert (maps.layouts, maps.fallbacks) == ({}, {})
    assert not maps.isEnabled()


def test_an_edit_of_the_maps_is_kept_in_the_layout_selected(editor: DefaultRootLayoutsEditor) -> None:
    """The maps edited are the selected layout's; the others stay as they were.

    **Test steps:**

    * select the second layout and retype its ``*`` layout
    * verify the layouts
    """
    names_editor(editor).set_current_index(1)
    table = maps_editor(editor).findChild(StringMapEditor, "layouts_editor")
    assert table is not None

    table.model.setData(table.model.index(0, VALUE_COLUMN), "{title}")

    assert editor.layouts == (LAYOUTS[0], RootLayout("Flat", {"*": ("{title}",)}, {}))


def test_the_heading_names_the_preset_whose_maps_are_shown(editor: DefaultRootLayoutsEditor) -> None:
    """The maps are the selected preset's, and the heading over them says whose -- following a rename, or saying none
    is selected.

    **Test steps:**

    * read the heading; rename the selected preset, then empty its name; select none
    * verify the heading each time
    """
    heading = editor.findChild(QLabel, "selected_label")
    assert heading is not None
    model = names_editor(editor).layout_model
    assert heading.text() == "By author:"

    model.setData(model.index(0), "Deep")
    assert heading.text() == "Deep:"
    model.setData(model.index(0), "")
    assert heading.text() == f"{UNNAMED_PRESET}:"

    names_editor(editor).set_current_index(-1)
    assert heading.text() == NO_PRESET_SELECTED


def test_a_maps_edit_with_no_layout_selected_changes_no_layout(editor: DefaultRootLayoutsEditor) -> None:
    """With nothing selected there is no layout for the maps to belong to.

    **Test steps:**

    * select no layout and announce an edit of the maps
    * verify the layouts are as they were
    """
    names_editor(editor).set_current_index(-1)

    maps_editor(editor).edited.emit()

    assert editor.layouts == LAYOUTS


def test_a_new_list_keeps_the_row_selected_where_it_can(editor: DefaultRootLayoutsEditor) -> None:
    """Replacing the list keeps the selection's row, moved onto the last when the list got shorter.

    **Test steps:**

    * select the second layout, then replace the list with one layout
    * verify the one layout is selected and its maps shown; replace it with none and verify none is selected
    """
    names_editor(editor).set_current_index(1)

    editor.layouts = LAYOUTS[:1]
    assert names_editor(editor).current_index == 0
    assert maps_editor(editor).layouts == {"tutorial": ("{authors}/{title}",)}

    editor.layouts = ()
    assert names_editor(editor).current_index == -1


def test_the_list_model_names_each_layout_and_flags_an_empty_name() -> None:
    """A row shows a layout's name, editable; an empty one is coloured and explained, and saved as it is.

    **Test steps:**

    * insert a row after the first of ``LAYOUTS``, read it, then name it
    * verify its maps are a new root's default, its flag, and the name taken without its blanks
    """
    model = RootLayoutListModel()
    model.set_entries(LAYOUTS)

    row = model.insert(0)

    assert model.entries[row] == RootLayout("")
    assert (
        model.index(row).data(Qt.ItemDataRole.ToolTipRole) == "No name: the Add Roots dialog shows this layout blank."
    )
    assert isinstance(model.index(row).data(Qt.ItemDataRole.ForegroundRole), QBrush)
    assert model.index(row).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.index(0).data(Qt.ItemDataRole.ToolTipRole) is None
    assert model.setData(model.index(row), " Deep ")
    assert model.index(row).data() == "Deep"
    assert not model.setData(model.index(row), "Deep")
    assert not model.setData(model.index(row), "x", Qt.ItemDataRole.DisplayRole)
    assert not model.setData(QModelIndex(), "x")
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert model.rowCount(model.index(0)) == 0


def test_the_list_model_moves_copies_deletes_and_resets() -> None:
    """The list editor's operations act on the row they are given; Reset puts the shipped layouts back.

    **Test steps:**

    * duplicate, move every way, set a row's maps twice, delete, try rows that do not exist, and reset
    * verify the entries after each
    """
    model = RootLayoutListModel()
    model.set_entries(LAYOUTS)

    assert model.duplicate(0) == 1
    assert model.move_to_bottom(0) == 2
    assert model.move_to_top(2) == 0
    assert model.move_down(0) == 1
    assert model.move_up(1) == 0
    model.set_maps(1, {"*": ("{title}",)}, {})
    model.set_maps(1, {"*": ("{title}",)}, {})
    assert model.entries[1] == RootLayout("By author", {"*": ("{title}",)}, {})
    model.delete(1)
    assert model.entries == LAYOUTS

    assert model.duplicate(-1) == -1
    assert model.move_up(0) == 0
    model.delete(-1)
    assert not model.insertRows(9, 1)
    assert not model.removeRows(9, 1)
    assert not model.moveRows(model.index(0), 0, 1, QModelIndex(), 1)
    assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 1)
    assert model.count == 2

    model.reset()
    assert model.entries == DEFAULT_ROOT_LAYOUTS
