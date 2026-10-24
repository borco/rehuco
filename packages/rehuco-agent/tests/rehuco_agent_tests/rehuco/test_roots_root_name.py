"""Tests for editing a root's name on the card (#514): an empty name is kept without a question, the column follows what
is typed and shows where the root is while the label is empty, and a button gives the root its default name.

The panel runs over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served and its writes captured.
"""

import json
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock
from uuid import UUID

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QToolButton
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_node import RootsNode, RootsNodeKind
from rehuco_core import RehucoRoot, TaskQueue

from rehuco_agent_tests.mapped_roots import mapped_root

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    REHUCO_PATH,
    CatalogDocks,
    GateJob,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_held,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
    select_root,
    shown_labels,
    wait_for_jobs,
)

WARNING: Final = "rehuco_agent.rehuco.roots_panel.QMessageBox.warning"


@fixture(name="has_focus", autouse=True)
def fixture_has_focus(mocker: MockerFixture, dock: CatalogDocks) -> MagicMock:
    """Say the name field has the focus, as it does while a person types in it: the pane then leaves what is typed
    alone when the row it shows changes, instead of showing the saved name again.

    :param mocker: pytest-mock fixture.
    :param dock: the docks.
    :returns: the stand-in for the field's ``hasFocus``, for a test to say the focus has left.
    """
    return mocker.patch.object(dock.roots.root_name_edit, "hasFocus", return_value=True)


def type_name(dock: CatalogDocks, text: str) -> None:
    """Type into the card's name field the way a person does: the field says it was edited.

    :param dock: the docks.
    :param text: the field's new text.
    """
    edit = dock.roots.root_name_edit
    edit.setText(text)
    edit.textEdited.emit(text)


def finish_name(dock: CatalogDocks) -> None:
    """Finish editing the name field.

    :param dock: the docks.
    """
    dock.roots.root_name_edit.editingFinished.emit()


def written_labels(saves: MagicMock) -> list[str]:
    """The root labels of the last ``.rehuco`` written.

    :param saves: the mock capturing the writes.
    :returns: one label per root.
    """
    return [root["label"] for root in json.loads(saves.call_args[0][1])["roots"]]


@mark.usefixtures("served")
def test_an_empty_name_is_saved_as_typed_without_a_question(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock
) -> None:
    """Emptying the name is allowed: nothing is asked and the empty string is what the file holds.

    **Test steps:**

    * select the second root, clear its name and finish editing
    * verify no warning, an empty label written for it, and the field left empty
    """
    warning = mocker.patch(WARNING)
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    type_name(dock, "")
    finish_name(dock)

    warning.assert_not_called()
    assert written_labels(saves) == ["tutorials", ""]
    assert dock.roots.root_name_edit.text() == ""


@mark.usefixtures("served", "saves")
def test_an_empty_name_stays_empty_when_it_is_cleared_again(mocker: MockerFixture, dock: CatalogDocks) -> None:
    """Clearing the name a second time leaves the field empty, as the first time did.

    **Test steps:**

    * clear the name, finish, type a name, finish, clear it and finish again
    * verify no warning was shown and the field is empty
    """
    warning = mocker.patch(WARNING)
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    for text in ("", "again", ""):
        type_name(dock, text)
        finish_name(dock)

    warning.assert_not_called()
    assert dock.roots.root_name_edit.text() == ""


@mark.usefixtures("served", "saves")
def test_the_column_shows_the_folder_while_the_label_is_empty(dock: CatalogDocks) -> None:
    """A root with an empty label is listed by where it is on this machine.

    **Test steps:**

    * clear the second root's name and finish editing
    * verify its row shows its folder and the other keeps its label
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    type_name(dock, "")
    finish_name(dock)

    packs = dock.catalog.mapped_roots()[1]
    assert shown_labels(dock) == ["tutorials", str(packs.path)]


@mark.usefixtures("served", "saves")
def test_the_column_follows_what_is_typed_before_it_is_saved(dock: CatalogDocks, saves: MagicMock) -> None:
    """The row's label is what is in the field while it is being edited, and nothing is written until the edit ends.

    **Test steps:**

    * select the second root and type a name, then clear it, without finishing
    * verify the row shows the text, then the folder, and nothing was written
    * finish editing and verify the label is kept
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)
    folder = str(dock.catalog.mapped_roots()[1].path)

    type_name(dock, "Packs & Co")
    assert shown_labels(dock) == ["tutorials", "Packs & Co"]
    type_name(dock, "  ")
    assert shown_labels(dock) == ["tutorials", folder]
    saves.assert_not_called()

    finish_name(dock)

    assert written_labels(saves) == ["tutorials", ""]


@mark.usefixtures("served")
def test_the_default_name_button_wins_over_a_name_saved_as_the_focus_left_for_it(
    dock: CatalogDocks, saves: MagicMock, has_focus: MagicMock
) -> None:
    """Pressing the button takes the focus from the field in the app -- the dock's scroll area takes it -- so what was
    typed is saved first; the button then gives the root its default name all the same, in the field too.

    **Test steps:**

    * select the second root and type a name
    * let the focus leave the field, which finishes the edit, and trigger the default-name action
    * verify the field, the column and the written label are the default name
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)
    type_name(dock, "xxx")
    has_focus.return_value = False
    finish_name(dock)
    assert written_labels(saves) == ["tutorials", "xxx"]

    dock.roots.default_root_name_action.trigger()

    assert dock.roots.root_name_edit.text() == "packs"
    assert shown_labels(dock) == ["tutorials", "packs"]
    assert written_labels(saves) == ["tutorials", "packs"]


@mark.usefixtures("served", "saves")
def test_the_default_name_button_puts_back_a_default_name_still_being_typed_over(dock: CatalogDocks) -> None:
    """While a root that already has its default name is being renamed, the button puts that name back in the field
    and the column, with nothing to write.

    **Test steps:**

    * select the second root, whose name is its default, and type another one
    * trigger the default-name action
    * verify the field and the column show the default name again
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)
    type_name(dock, "Other")
    assert shown_labels(dock)[1] == "Other"

    dock.roots.default_root_name_action.trigger()

    assert dock.roots.root_name_edit.text() == "packs"
    assert shown_labels(dock) == ["tutorials", "packs"]


def default_button(dock: CatalogDocks) -> QToolButton:
    """The tool button that carries the default-name action.

    :param dock: the docks.
    :returns: the button.
    """
    action = dock.roots.default_root_name_action
    return next(button for button in dock.roots.findChildren(QToolButton) if button.defaultAction() is action)


@mark.usefixtures("served")
def test_the_default_name_is_the_placeholder_and_the_button_gives_it_to_the_root(
    dock: CatalogDocks, saves: MagicMock
) -> None:
    """The name a root was added with -- the last segment of its location -- shows in the empty field, and its button
    renames the root to it at once, though the field never had the focus.

    **Test steps:**

    * select the second root and verify the placeholder, and the default button disabled as the name is it already
    * rename the root and verify the button is enabled
    * trigger it and verify the field, the column and the written label are the default name again
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)
    default = dock.roots.default_root_name_action
    assert dock.roots.root_name_edit.placeholderText() == "packs"
    assert not default.isEnabled()

    type_name(dock, "Other")
    finish_name(dock)
    assert written_labels(saves) == ["tutorials", "Other"]
    assert default.isEnabled()

    default.trigger()

    assert dock.roots.root_name_edit.text() == "packs"
    assert shown_labels(dock) == ["tutorials", "packs"]
    assert written_labels(saves) == ["tutorials", "packs"]
    assert not default.isEnabled()


@mark.usefixtures("served", "saves")
def test_the_default_name_button_is_shown_beside_a_roots_name_only(dock: CatalogDocks) -> None:
    """The button sits beside the name for a root row and is not one of the row's action buttons.

    **Test steps:**

    * select a root and verify the default-name button is shown and is not among the pane's buttons
    * select no root and verify it is hidden
    """
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)
    preview = dock.roots._RootsPanel__preview  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert not default_button(dock).isHidden()
    assert default_button(dock) not in preview.buttons

    dock.roots.roots_view.setCurrentIndex(QModelIndex())

    assert default_button(dock).isHidden()


@mark.usefixtures("saves")
def test_the_default_name_button_stays_off_while_the_names_cannot_be_edited(
    dock: CatalogDocks, served: dict[str, Any]
) -> None:
    """A catalog newer than this build is read-only, so its names cannot be edited, by the button either.

    **Test steps:**

    * open a catalog stamped newer than this build and select a root
    * verify the name field is disabled, and typing in it does not enable the default-name button
    """
    served["format_version"] = 99
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 0)

    type_name(dock, "x")

    assert not dock.roots.root_name_edit.isEnabled()
    assert not dock.roots.default_root_name_action.isEnabled()


@mark.usefixtures("served")
def test_a_name_another_root_has_is_still_refused_and_the_column_goes_back(
    mocker: MockerFixture, dock: CatalogDocks, saves: MagicMock
) -> None:
    """Only an empty name is let through: a clash still asks, writes nothing, and the field and column show the label
    the root has.

    **Test steps:**

    * type another root's label while the column follows it, and finish editing
    * verify a warning, no write, and the label back in the field and the column
    """
    warning = mocker.patch(WARNING)
    dock.catalog.open_rehuco(REHUCO_PATH)
    select_root(dock, 1)

    type_name(dock, "TUTORIALS")
    finish_name(dock)

    warning.assert_called_once()
    saves.assert_not_called()
    assert dock.roots.root_name_edit.text() == "packs"
    assert shown_labels(dock) == ["tutorials", "packs"]


@mark.usefixtures("served", "saves")
def test_an_unmapped_root_shows_its_location_while_its_label_is_empty(
    dock: CatalogDocks, served: dict[str, Any]
) -> None:
    """A root this machine does not map is listed by its location when its label is empty.

    **Test steps:**

    * serve a third root with an empty label and no mapping, and open the catalog
    * verify its row shows its location
    """
    away = "//nas/data/Away"
    served["roots"].append({"id": str(UUID(int=9)), "location": away, "label": ""})

    dock.catalog.open_rehuco(REHUCO_PATH)

    assert shown_labels(dock)[2] == away


@mark.usefixtures("saves")
def test_a_root_with_an_empty_name_is_named_by_where_it_is_in_its_jobs(
    qtbot: QtBot, dock: CatalogDocks, served: dict[str, Any], queue: TaskQueue, held: GateJob
) -> None:
    """A job's name says which root it is for, so a root whose name is empty is named by where it is: this machine's
    folder, or the location of a root not mapped here.

    **Test steps:**

    * serve the second root with an empty label and a third, not mapped here, also with one, and open the catalog
    * hold the queue; scan the second root, remove the third, then the second
    * verify the jobs are named by the folder and by the location
    """
    away = "//nas/data/Away"
    served["roots"][1]["label"] = ""
    served["roots"].append({"id": str(UUID(int=9)), "location": away, "label": ""})
    dock.catalog.open_rehuco(REHUCO_PATH)
    packs = dock.catalog.mapped_roots()[1]

    dock.catalog.scan_root(packs.root_id)
    dock.catalog.remove_root(2)
    dock.catalog.remove_root(1)

    assert [status.label for status in queue.jobs()[1:]] == [
        f"Scan - {packs.path}",
        f"Remove root - {away}",
        f"Remove root - {packs.path}",
    ]
    held.let_finish()
    wait_for_jobs(qtbot, queue)


def test_a_node_shows_its_name_or_where_the_root_is() -> None:
    """The label a row shows is its name -- and, for a root with an empty name, where the root is; a folder or file
    is just its name.

    **Test steps:**

    * build a mapped root's node, an unmapped one's and a folder's, the roots with empty names
    * verify each label, and that naming the mapped root makes its label the name
    """
    folder_of_mapped = Path("/data/x")
    mapped = RootsNode("", RootsNodeKind.ROOT, None, root=mapped_root(folder_of_mapped, ""))
    unmapped = RootsNode("", RootsNodeKind.ROOT, None, root=RehucoRoot(UUID(int=2), "", "//nas/y"))
    folder = RootsNode("sub", RootsNodeKind.FOLDER, None)

    assert mapped.label == str(folder_of_mapped)
    assert unmapped.label == "//nas/y"
    assert folder.label == "sub"
    mapped.name = "named"
    assert mapped.label == "named"
