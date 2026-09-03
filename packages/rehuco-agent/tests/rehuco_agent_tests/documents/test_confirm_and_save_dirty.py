"""Tests for ``confirm_and_save_dirty``: the batch confirm-and-save both close guards share (#176)."""

from typing import Final

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.confirm_and_save_dirty import confirm_and_save_dirty

UNSAVED_CHANGES_DIALOG: Final = "rehuco_agent.documents.confirm_and_save_dirty.UnsavedChangesDialog"
"""Where the batch dialog is looked up -- patched by every test here, and by both callers' suites."""


@fixture
def parent(qtbot: QtBot) -> QWidget:
    """A real widget to parent the (mocked) dialogs to, registered for teardown."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def test_proceeds_without_a_dialog_when_nothing_is_dirty(mocker: MockerFixture, parent: QWidget) -> None:
    """An empty model list proceeds silently -- there is nothing to confirm, so no dialog appears.

    **Test steps:**

    * mock the dialog class to detect an unwanted construction
    * call ``confirm_and_save_dirty`` with no models
    * verify it returned ``True`` and the dialog was never constructed
    """
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG)

    assert confirm_and_save_dirty(parent, []) is True
    dialog_class.assert_not_called()


def test_refuses_when_the_dialog_is_cancelled(mocker: MockerFixture, parent: QWidget) -> None:
    """Cancelling the dialog reports ``False`` and saves nothing -- the caller must abort its close.

    **Test steps:**

    * stand in one dirty model and mock the dialog to report Rejected
    * call ``confirm_and_save_dirty``
    * verify it returned ``False``, never asked for selections, and saved nothing
    """
    model = mocker.MagicMock()
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Rejected
    dialog_class = mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)

    assert confirm_and_save_dirty(parent, [model]) is False
    dialog_class.assert_called_once_with([model], parent)
    dialog.selected_models.assert_not_called()
    model.save.assert_not_called()


def test_saves_only_the_selected_models_when_accepted(mocker: MockerFixture, parent: QWidget) -> None:
    """Accepting saves the models the dialog reports as selected; an unselected one is left dirty.

    **Test steps:**

    * stand in two dirty models and mock the dialog to accept, selecting only the first
    * call ``confirm_and_save_dirty``
    * verify it returned ``True`` and only the selected model was saved
    """
    selected, unselected = mocker.MagicMock(), mocker.MagicMock()
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [selected]
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)

    assert confirm_and_save_dirty(parent, [selected, unselected]) is True
    selected.save.assert_called_once_with()
    unselected.save.assert_not_called()


def test_refuses_and_stops_saving_when_a_failing_save_is_cancelled(mocker: MockerFixture, parent: QWidget) -> None:
    """Cancelling the retry/cancel dialog a failing save raises (#146) reports ``False`` *before* the
    remaining selections are attempted -- the ordering both callers rely on to close nothing.

    **Test steps:**

    * stand in two selected models, the first's ``save`` raising ``OSError``
    * mock the dialog to accept and select both, and the critical dialog to answer Cancel
    * call ``confirm_and_save_dirty``
    * verify it returned ``False``, surfaced the failure, and never reached the second save
    """
    failing, later = mocker.MagicMock(label="doc.rehu"), mocker.MagicMock(label="other.rehu")
    failing.save.side_effect = OSError("offline mount")
    dialog = mocker.MagicMock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.selected_models.return_value = [failing, later]
    mocker.patch(UNSAVED_CHANGES_DIALOG, return_value=dialog)
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    assert confirm_and_save_dirty(parent, [failing, later]) is False
    critical.assert_called_once()
    later.save.assert_not_called()
