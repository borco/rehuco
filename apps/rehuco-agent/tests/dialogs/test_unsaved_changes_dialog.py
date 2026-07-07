"""Tests for UnsavedChangesDialog: the whole-app close guard's Save Selected/Discard All/Cancel prompt."""

from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialogButtonBox, QStyleOptionViewItem
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.unsaved_changes_dialog import UnsavedChangesDialog

PATH: Final = Path.cwd() / "fake" / "info.rehu"


def make_model(mocker: MockerFixture, path: Path | None) -> Any:
    """Build a stand-in dirty document model with the given ``path``.

    :param mocker: pytest-mock fixture.
    :param path: the model's reported path, or ``None`` for an untitled document.
    :returns: a mock exposing just the ``path`` attribute the dialog reads.
    """
    return mocker.MagicMock(path=path)


def test_lists_every_model_checked_by_default(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Every model is listed, and every checkbox starts checked.

    **Test steps:**

    * build the dialog with two dirty models
    * verify both appear in the list model, each checked
    * verify both are reported selected before any interaction
    """
    first, second = make_model(mocker, PATH), make_model(mocker, None)
    dialog = UnsavedChangesDialog([first, second])
    qtbot.addWidget(dialog)

    list_model = dialog._UnsavedChangesDialog__list_model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert list_model.rowCount() == 2
    assert list_model.item(0).text() == str(PATH)
    assert list_model.item(1).text() == "Untitled"
    assert list_model.item(0).checkState() == Qt.CheckState.Checked
    assert list_model.item(1).checkState() == Qt.CheckState.Checked
    assert not list_model.item(0).isEditable()
    assert dialog.selected_models() == [first, second]


def test_unchecking_a_model_excludes_it_from_selection(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Unchecking a document's checkbox drops it from ``selected_models``.

    **Test steps:**

    * build the dialog with two dirty models
    * uncheck the first one's checkbox
    * verify only the second remains selected
    """
    first, second = make_model(mocker, PATH), make_model(mocker, None)
    dialog = UnsavedChangesDialog([first, second])
    qtbot.addWidget(dialog)

    list_model = dialog._UnsavedChangesDialog__list_model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    list_model.item(0).setCheckState(Qt.CheckState.Unchecked)

    assert dialog.selected_models() == [second]


def test_save_button_is_relabeled_save_selected(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The standard Save button reads "Save Selected", matching what it actually does.

    **Test steps:**

    * build the dialog
    * verify the button box's Save-role button text
    """
    dialog = UnsavedChangesDialog([make_model(mocker, PATH)])
    qtbot.addWidget(dialog)

    button_box = dialog._UnsavedChangesDialog__ui.button_box  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert button_box.button(QDialogButtonBox.StandardButton.Save).text() == "Save Selected"


def test_discard_all_accepts_and_selects_nothing_regardless_of_checkboxes(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Clicking Discard All accepts the dialog and reports no models to save, checkboxes notwithstanding.

    **Test steps:**

    * build the dialog with one (checked, by default) dirty model
    * click the Discard All button
    * verify the dialog was accepted and no models are selected
    """
    dialog = UnsavedChangesDialog([make_model(mocker, PATH)])
    qtbot.addWidget(dialog)
    button_box = dialog._UnsavedChangesDialog__ui.button_box  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    discard_all = next(b for b in button_box.buttons() if b.text() == "Discard All")

    discard_all.click()

    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.selected_models() == []


def test_clicking_anywhere_in_a_row_toggles_its_checkbox(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A mouse release anywhere within a checkable row's cell toggles it, not just its checkbox glyph.

    **Test steps:**

    * build the dialog with one (checked, by default) dirty model
    * dispatch a mouse-release editor event for that row through the view's delegate
    * verify the checkbox is now unchecked
    """
    dialog = UnsavedChangesDialog([make_model(mocker, PATH)])
    qtbot.addWidget(dialog)
    view = dialog._UnsavedChangesDialog__ui.documents_list_view  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    list_model = dialog._UnsavedChangesDialog__list_model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    index = list_model.index(0, 0)
    event = QEvent(QEvent.Type.MouseButtonRelease)

    handled = view.itemDelegate().editorEvent(event, list_model, QStyleOptionViewItem(), index)

    assert handled
    assert list_model.item(0).checkState() == Qt.CheckState.Unchecked


def test_other_editor_events_fall_through_to_the_base_delegate(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An event that isn't a mouse release is left to the base delegate's default handling.

    **Test steps:**

    * build the dialog with one dirty model
    * dispatch a mouse-move editor event (not a release) for that row
    * verify the checkbox is unchanged
    """
    dialog = UnsavedChangesDialog([make_model(mocker, PATH)])
    qtbot.addWidget(dialog)
    view = dialog._UnsavedChangesDialog__ui.documents_list_view  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    list_model = dialog._UnsavedChangesDialog__list_model  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    index = list_model.index(0, 0)
    event = QEvent(QEvent.Type.MouseMove)

    view.itemDelegate().editorEvent(event, list_model, QStyleOptionViewItem(), index)

    assert list_model.item(0).checkState() == Qt.CheckState.Checked
