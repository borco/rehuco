"""Tests for the Roots view's edit mode for a root (#578): F2 or the Edit button turns it on and off, it stays on from
one root to the next, and the layouts and fallbacks edited there are written to the root's ``.rehuroot``.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured.
"""

import json
from typing import Any, Final
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QToolButton, QWidget
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_preview import RootsPreview
from rehuco_agent.rehuco.string_map_editor import StringMapEditor
from rehuco_agent.rehuco.string_map_model import KEY_COLUMN, VALUE_COLUMN, StringMapModel
from rehuco_core import RehucoFile, read_layouts

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    HOME,
    REHUCO_PATH,
    CatalogDocks,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
    select_root,
)

WARNING: Final = "rehuco_agent.rehuco.root_properties_editor.QMessageBox.warning"


def preview(dock: CatalogDocks) -> RootsPreview:
    """The details pane.

    :param dock: the docks.
    :returns: the pane.
    """
    found = dock.roots.findChild(RootsPreview)
    assert found is not None
    return found


def layouts_table(dock: CatalogDocks) -> StringMapEditor:
    """The layouts table of the edit pane.

    :param dock: the docks.
    :returns: the table.
    """
    found = preview(dock).root_layouts_editor.findChild(StringMapEditor, "layouts_editor")
    assert found is not None
    return found


def saved_root(row: int) -> dict[str, Any]:
    """A root's file as it is now: what a save wrote there, or as served.

    :param row: the root's row in ``HOME``.
    :returns: the parsed file.
    """
    return json.loads((REHUCO_PATH.parent / f"{HOME['roots'][row]['id']}.rehuroot").read_text(encoding="utf-8"))


def editing(dock: CatalogDocks) -> bool:
    """Whether the edit pane is what the details pane shows.

    :param dock: the docks.
    :returns: whether it is.
    """
    return preview(dock).root_edit_pane.isVisibleTo(dock.roots)


def focus(qtbot: QtBot, widget: QWidget) -> None:
    """Give a widget the keyboard, its window active, as a shortcut needs.

    :param qtbot: pytest-qt fixture.
    :param widget: the widget.
    """
    widget.activateWindow()
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus)


@mark.usefixtures("served", "saves")
def test_f2_and_the_button_turn_the_edit_mode_on_and_off(qtbot: QtBot, dock: CatalogDocks) -> None:
    """F2 from the Roots view, and the button the root rows show, toggle the edit mode; the button is the action's.

    **Test steps:**

    * open a catalog, show the panel and select a root
    * press F2 in the view, then again, then click the button
    * verify the mode each time, and the button's action
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.show()
    qtbot.waitExposed(dock.roots)
    select_root(dock, 0)
    view = dock.roots.roots_view
    focus(qtbot, view)
    button = preview(dock).findChild(QToolButton, "edit_root_button")
    assert button is not None
    assert button.defaultAction() is dock.roots.edit_root_action
    assert button not in preview(dock).buttons
    assert not editing(dock)

    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert editing(dock)
    qtbot.keyClick(view, Qt.Key.Key_F2)
    assert not editing(dock)
    button.click()
    assert editing(dock)


@mark.usefixtures("served", "saves")
def test_f2_from_inside_a_layouts_table_ends_the_edit_mode(qtbot: QtBot, dock: CatalogDocks) -> None:
    """The tables give up their own F2, so it ends the mode from wherever the keyboard is in the pane.

    **Test steps:**

    * open a catalog, show the panel, select a root and turn the mode on
    * press F2 in the layouts table
    * verify the mode is off
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    dock.roots.show()
    qtbot.waitExposed(dock.roots)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)
    table = layouts_table(dock).view
    focus(qtbot, table)

    qtbot.keyClick(table, Qt.Key.Key_F2)

    assert not editing(dock)
    assert table.state() is not QAbstractItemView.State.EditingState


@mark.usefixtures("served", "saves")
def test_the_edit_mode_stays_on_from_root_to_root_showing_each_ones_values(dock: CatalogDocks) -> None:
    """Selecting another root keeps the mode, and the editors show that root.

    **Test steps:**

    * open a catalog, select the first root and turn the mode on; select the second
    * verify the mode is still on and the editors show the second root's name and layouts
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)

    select_root(dock, 1)

    assert editing(dock)
    assert dock.roots.edit_root_action.isChecked()
    assert dock.roots.root_name_edit.text() == "packs"
    assert preview(dock).root_layouts_editor.layouts == read_layouts(saved_root(1).get("layouts", {"*": "*"}))


@mark.usefixtures("served")
def test_an_edit_of_the_layouts_is_written_to_the_roots_file(dock: CatalogDocks, saves: MagicMock) -> None:
    """Each edit of the tables writes the root's ``.rehuroot``; the ``.rehuco`` and the other roots stay as they are.

    **Test steps:**

    * open a catalog, select the first root, turn the mode on, and retype its ``*`` layout
    * verify the root file holds it, the read-only rows say it once the mode is off, and the ``.rehuco`` is unwritten
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)
    table = layouts_table(dock)

    table.model.setData(table.model.index(0, VALUE_COLUMN), "{title}")

    assert saved_root(0)["layouts"] == {"*": ["{title}"]}
    assert saved_root(1)["layouts"] == {"*": "*"}
    saves.assert_not_called()
    dock.roots.edit_root_action.setChecked(False)
    assert preview(dock).root_texts["layouts"] == "* \N{RIGHTWARDS ARROW} {title}"


@mark.usefixtures("served", "saves")
def test_a_second_template_for_a_type_is_written_in_row_order_and_read_one_line_each(dock: CatalogDocks) -> None:
    """A second row for the same type is a second template, kept in the order of the rows (#638).

    **Test steps:**

    * open a catalog, select the first root, turn the mode on, retype its ``*`` layout and add a ``*`` row below it
    * verify the root file holds both templates as a list, and the read-only rows give each its own line
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)
    table = layouts_table(dock)
    table.model.setData(table.model.index(0, VALUE_COLUMN), "{title}")

    model = table.model
    assert isinstance(model, StringMapModel)
    row = model.insert(0)
    table.model.setData(table.model.index(row, KEY_COLUMN), "*")
    table.model.setData(table.model.index(row, VALUE_COLUMN), "{authors}/{title}")

    assert saved_root(0)["layouts"] == {"*": ["{title}", "{authors}/{title}"]}
    dock.roots.edit_root_action.setChecked(False)
    arrow = "\N{RIGHTWARDS ARROW}"
    assert preview(dock).root_texts["layouts"] == f"* {arrow} {{title}}\n* {arrow} {{authors}}/{{title}}"


@mark.usefixtures("served", "saves")
def test_a_refused_layouts_write_is_said_and_the_tables_go_back(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A root file that will not take the edit leaves the root as it was, on disk and in the tables.

    **Test steps:**

    * make the catalog refuse the write, then retype a layout
    * verify the warning, the tables showing the root's layouts again, and the root file unchanged
    """
    warning = mocker.patch(WARNING)
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)
    before = saved_root(0)
    mocker.patch.object(RehucoFile, "set_root_layouts", side_effect=ValueError("refused"))
    table = layouts_table(dock)

    table.model.setData(table.model.index(0, VALUE_COLUMN), "{title}")

    warning.assert_called_once()
    assert preview(dock).root_layouts_editor.layouts == {"*": ("*",)}
    assert saved_root(0) == before


@mark.usefixtures("served", "saves")
def test_an_edit_that_makes_the_same_maps_writes_nothing(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """A row added with no key yet changes no map, so nothing is written.

    **Test steps:**

    * select a root, turn the mode on, and announce an edit that leaves the maps as they are
    * verify no write was asked of the catalog
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    dock.roots.edit_root_action.setChecked(True)
    write = mocker.patch.object(RehucoFile, "set_root_layouts")

    preview(dock).root_layouts_editor.edited.emit()

    write.assert_not_called()


@mark.usefixtures("saves")
def test_the_edit_mode_cannot_be_used_on_a_read_only_catalog(dock: CatalogDocks, served: dict[str, Any]) -> None:
    """A catalog newer than this build is read-only: the toggle is off, and an edit announced anyway writes nothing.

    **Test steps:**

    * open a catalog stamped newer than this build and select a root
    * verify the toggle is disabled; announce an edit and verify the root file is unchanged
    """
    served["format_version"] = 99
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    before = saved_root(0)

    assert not dock.roots.edit_root_action.isEnabled()
    preview(dock).root_layouts_editor.edited.emit()
    assert saved_root(0) == before
