"""Tests for the temporary roots list's model (#377)."""

from pathlib import Path
from typing import Final
from uuid import uuid4

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture
from rehuco_agent.rehuco.rehuco_roots_model import UNREACHABLE_TOOLTIP, RehucoRootsModel
from rehuco_core import RehucoRoot

TUTORIALS: Final = RehucoRoot(uuid4(), Path("/fake/tutorials"), "tutorials", False)
PACKS: Final = RehucoRoot(uuid4(), Path("/fake/packs"), "packs", True)


@fixture(name="model")
def fixture_model() -> RehucoRootsModel:
    """A model of two roots, the second of which the last scan could not list."""
    model = RehucoRootsModel()
    model.set_roots([TUTORIALS, PACKS], {TUTORIALS.root_id: True, PACKS.root_id: False})
    return model


def test_a_root_shows_its_label_and_folder(model: RehucoRootsModel) -> None:
    """Two columns, in file order.

    **Test steps:**

    * read the headers and the second row
    * verify the label and the folder
    """
    assert model.columnCount() == 2
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in range(2)] == ["Label", "Path"]
    assert [model.index(1, column).data() for column in range(2)] == ["packs", str(PACKS.path)]


def test_an_unreachable_root_says_so_on_hover(model: RehucoRootsModel) -> None:
    """Only a root the last scan could not list gets the tooltip; a never-scanned one does not.

    **Test steps:**

    * read the tooltips of a reachable, an unreachable and a never-scanned root
    * verify only the unreachable one has one
    """
    assert model.index(1, 0).data(Qt.ItemDataRole.ToolTipRole) == UNREACHABLE_TOOLTIP
    assert model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole) is None
    model.set_roots([TUTORIALS], {TUTORIALS.root_id: None})
    assert model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole) is None


def test_root_at_answers_the_root_or_none(model: RehucoRootsModel) -> None:
    """A row out of range is no root rather than an error.

    **Test steps:**

    * ask for rows in and out of range
    * verify the root, then ``None``
    """
    assert model.root_at(0) is TUTORIALS
    assert model.root_at(2) is None
    assert model.root_at(-1) is None


def test_setting_roots_resets_the_model(model: RehucoRootsModel) -> None:
    """Replacing the roots is a reset.

    **Test steps:**

    * replace the roots with none
    * verify the table is empty
    """
    model.set_roots([], {})

    assert model.rowCount() == 0
    assert model.index(0, 0).data() is None


def test_an_invalid_index_answers_nothing(model: RehucoRootsModel) -> None:
    """A view asking about no cell gets ``None``.

    **Test steps:**

    * read the display role of an invalid index
    * verify it is ``None``
    """
    assert model.data(QModelIndex()) is None


def test_a_child_index_has_no_rows(model: RehucoRootsModel) -> None:
    """A table has no children under a cell.

    **Test steps:**

    * ask for the counts under a cell
    * verify both are zero
    """
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0


def test_other_roles_and_headers_answer_nothing(model: RehucoRootsModel) -> None:
    """Only the display and tooltip roles say anything.

    **Test steps:**

    * read a decoration, a vertical header and a header tooltip
    * verify each is ``None``
    """
    assert model.index(0, 0).data(Qt.ItemDataRole.DecorationRole) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
