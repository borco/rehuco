"""Tests for what a table browser's model says of a row's root: a root that cannot be reached (#511), the server its
files are on and its label (#627)."""

from dataclasses import replace
from typing import Final
from uuid import UUID, uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.catalog_table_model import COLUMNS, CatalogColumn, CatalogTableModel
from rehuco_core import CatalogRecord, RecordKind

from .test_catalog_table_model import (  # noqa: F401  # pylint: disable=unused-import
    ROOT_ID,
    cell,
    column_of,
    fixture_model,
    rehu,
    row,
)

# region A root that cannot be reached (#511)

OFFLINE_REASON: Final = "This network share is not connected."


def test_an_offline_roots_rows_are_greyed_and_say_why_and_the_others_are_not(qtbot: QtBot) -> None:
    """A row of a root that cannot be reached draws in the disabled text colour and says why when hovered, over every
    cell's own tooltip; a row of another root draws and hovers as before.

    **Test steps:**

    * a model holding an unreadable row of one root and a row of another, then mark the first root offline
    * verify one ``dataChanged`` over every cell, for the foreground and the tooltip
    * verify the first row is greyed and says why, the reason is the root's, and the other row is as it was
    """
    other = uuid4()
    model = CatalogTableModel()
    model.set_rows(
        [row(CatalogRecord("broken/info.rehu", RecordKind.REHU, error="Not JSON")), row(rehu("a/info.rehu"), other)],
        [ROOT_ID, other],
    )

    with qtbot.waitSignal(model.dataChanged) as changed:
        model.set_offline_roots({ROOT_ID: OFFLINE_REASON})

    assert changed.args is not None
    top_left, bottom_right, roles = changed.args
    assert (top_left.row(), top_left.column()) == (0, 0)
    assert (bottom_right.row(), bottom_right.column()) == (1, len(COLUMNS) - 1)
    assert roles == [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole]
    disabled = QGuiApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert cell(model, 0, CatalogColumn.TITLE, Qt.ItemDataRole.ForegroundRole) == disabled
    assert cell(model, 0, CatalogColumn.TITLE, Qt.ItemDataRole.ToolTipRole) == OFFLINE_REASON
    assert cell(model, 1, CatalogColumn.TITLE, Qt.ItemDataRole.ForegroundRole) is None
    assert cell(model, 1, CatalogColumn.TITLE, Qt.ItemDataRole.ToolTipRole) is None
    assert model.offline_reason(ROOT_ID) == OFFLINE_REASON
    assert model.offline_reason(other) is None


def test_the_same_offline_roots_again_change_nothing(qtbot: QtBot, model: CatalogTableModel) -> None:
    """Every read of the rows hands the browsers the offline roots again; the same set repaints nothing.

    **Test steps:**

    * mark a root offline, then hand the same set again
    * verify the second call emits no ``dataChanged``
    """
    model.set_offline_roots({ROOT_ID: OFFLINE_REASON})

    with qtbot.assertNotEmitted(model.dataChanged):
        model.set_offline_roots({ROOT_ID: OFFLINE_REASON})


def test_an_empty_model_takes_the_offline_roots_without_a_signal(qtbot: QtBot) -> None:
    """A browser with no rows has nothing to repaint, but keeps the set for the rows a read brings.

    **Test steps:**

    * mark a root offline on an empty model
    * verify no ``dataChanged``, and that the root's reason is kept
    """
    model = CatalogTableModel()

    with qtbot.assertNotEmitted(model.dataChanged):
        model.set_offline_roots({ROOT_ID: OFFLINE_REASON})

    assert model.offline_reason(ROOT_ID) == OFFLINE_REASON


def two_root_model(first: UUID, second: UUID) -> CatalogTableModel:
    """A model holding one row of ``first``, labeled ``tutorials``, and one of ``second``, labeled ``books``."""
    model = CatalogTableModel()
    model.set_rows(
        [row(rehu("a/info.rehu"), first), replace(row(rehu("b/info.rehu"), second), root_label="books")],
        [first, second],
    )
    return model


def test_the_server_column_shows_the_server_of_each_rows_root() -> None:
    """A row shows where its root's files are: ``local`` for this machine's disks, else the host; a root with no
    location here shows nothing.

    **Test steps:**

    * a model of rows in three roots, told the servers of two
    * verify the cells read ``local``, ``nas`` and empty, and the header reads ``Server``
    """
    nas, lost = uuid4(), uuid4()
    model = CatalogTableModel()
    model.set_rows(
        [row(rehu("a/info.rehu")), row(rehu("b/info.rehu"), nas), row(rehu("c/info.rehu"), lost)], [ROOT_ID, nas, lost]
    )

    model.set_servers({ROOT_ID: "local", nas: "nas"})

    assert column_of(model, CatalogColumn.SERVER) == ["local", "nas", None]
    assert model.headerData(CatalogColumn.SERVER, Qt.Orientation.Horizontal) == "Server"


def test_the_server_column_repaints_when_the_servers_change_and_not_when_they_do_not(qtbot: QtBot) -> None:
    """Every read hands the model the servers again; only a different map repaints the column.

    **Test steps:**

    * set the servers, then set a different map
    * verify one ``dataChanged`` over the Server column alone, and the new value shown
    * set the same map again and verify no ``dataChanged``
    """
    nas = uuid4()
    model = two_root_model(ROOT_ID, nas)
    model.set_servers({ROOT_ID: "local", nas: "nas"})

    with qtbot.waitSignal(model.dataChanged) as changed:
        model.set_servers({ROOT_ID: "local", nas: "mini2"})

    assert changed.args is not None
    top_left, bottom_right, _roles = changed.args
    assert (top_left.row(), top_left.column()) == (0, CatalogColumn.SERVER)
    assert (bottom_right.row(), bottom_right.column()) == (1, CatalogColumn.SERVER)
    assert column_of(model, CatalogColumn.SERVER) == ["local", "mini2"]
    with qtbot.assertNotEmitted(model.dataChanged):
        model.set_servers({ROOT_ID: "local", nas: "mini2"})


def test_an_empty_model_takes_the_servers_without_a_signal(qtbot: QtBot) -> None:
    """A browser with no rows has nothing to repaint, but keeps the servers for the rows a read brings.

    **Test steps:**

    * set the servers on an empty model, then fill it
    * verify no ``dataChanged`` and the row shows its server
    """
    model = CatalogTableModel()

    with qtbot.assertNotEmitted(model.dataChanged):
        model.set_servers({ROOT_ID: "nas"})
    model.set_rows([row(rehu("a/info.rehu"))], [ROOT_ID])

    assert column_of(model, CatalogColumn.SERVER) == ["nas"]


def test_sorting_by_server_follows_the_servers_when_they_change() -> None:
    """The Server column sorts case-blind with a root that has none first, and a changed map re-sorts it at once --
    the keys it worked out are not kept.

    **Test steps:**

    * sort by Server on rows of two roots, one on ``nas`` and one on ``local``
    * verify ``local`` rows first; swap the servers and verify the rows swap
    * leave one root out and verify its row sorts first
    """
    nas = uuid4()
    model = two_root_model(ROOT_ID, nas)
    model.set_servers({ROOT_ID: "NAS", nas: "local"})
    model.sort(CatalogColumn.SERVER)
    assert column_of(model, CatalogColumn.PATH) == ["books/b/info.rehu", "tutorials/a/info.rehu"]

    model.set_servers({ROOT_ID: "local", nas: "NAS"})
    assert column_of(model, CatalogColumn.PATH) == ["tutorials/a/info.rehu", "books/b/info.rehu"]

    model.set_servers({nas: "NAS"})
    assert column_of(model, CatalogColumn.PATH) == ["tutorials/a/info.rehu", "books/b/info.rehu"]


def test_the_root_column_shows_the_roots_label_and_sorts_by_it() -> None:
    """The Root column is the label alone, which sorts rows by root, case ignored.

    **Test steps:**

    * sort by Root on rows labeled ``tutorials`` and ``books``
    * verify the cells and the order
    """
    other = uuid4()
    model = two_root_model(ROOT_ID, other)

    model.sort(CatalogColumn.ROOT)

    assert column_of(model, CatalogColumn.ROOT) == ["books", "tutorials"]
    assert column_of(model, CatalogColumn.PATH) == ["books/b/info.rehu", "tutorials/a/info.rehu"]
