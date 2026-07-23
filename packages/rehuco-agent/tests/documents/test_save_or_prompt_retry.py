"""Tests for ``save_or_prompt_retry``: the one seam every save call site funnels an I/O failure through (#146)."""

from PySide6.QtWidgets import QMessageBox, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.save_or_prompt_retry import save_or_prompt_retry


@fixture
def parent(qtbot: QtBot) -> QWidget:
    """A real widget to parent the (mocked) error dialog to, registered for teardown."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def test_returns_true_and_saves_once_on_a_clean_save(mocker: MockerFixture, parent: QWidget) -> None:
    """A save that succeeds returns ``True`` and shows no dialog.

    **Test steps:**

    * stand in a model whose ``save`` succeeds and mock the critical dialog to detect any call
    * call ``save_or_prompt_retry``
    * verify it returned ``True``, saved once, and never showed the dialog
    """
    model = mocker.MagicMock(label="doc.rehu")
    critical = mocker.patch.object(QMessageBox, "critical")

    assert save_or_prompt_retry(parent, model) is True
    model.save.assert_called_once_with()
    critical.assert_not_called()


def test_shows_a_critical_dialog_and_returns_false_on_cancel(mocker: MockerFixture, parent: QWidget) -> None:
    """An ``OSError`` (an offline mount) shows a critical dialog; Cancel returns ``False``.

    **Test steps:**

    * stand in a model whose ``save`` raises ``OSError`` and mock the critical dialog to answer Cancel
    * call ``save_or_prompt_retry``
    * verify the dialog was shown once and it returned ``False``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = OSError("offline mount")
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    assert save_or_prompt_retry(parent, model) is False
    critical.assert_called_once()


def test_retries_until_the_save_succeeds(mocker: MockerFixture, parent: QWidget) -> None:
    """Answering Retry re-attempts the save; a save that then succeeds returns ``True``.

    **Test steps:**

    * stand in a model whose ``save`` raises ``OSError`` twice then succeeds, and mock the critical
      dialog to answer Retry
    * call ``save_or_prompt_retry``
    * verify it saved three times and returned ``True``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = [OSError("offline mount"), OSError("offline mount"), None]
    mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Retry)

    assert save_or_prompt_retry(parent, model) is True
    assert model.save.call_count == 3


def test_falls_back_to_untitled_when_the_model_has_no_label(mocker: MockerFixture, parent: QWidget) -> None:
    """A path-less model (empty label) is named "Untitled" in the failure dialog rather than blank.

    **Test steps:**

    * stand in a model with an empty label whose ``save`` raises ``OSError``, and mock the critical
      dialog to answer Cancel
    * call ``save_or_prompt_retry``
    * verify the dialog's message names the document "Untitled"
    """
    model = mocker.MagicMock(label="")
    model.save.side_effect = OSError("offline mount")
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    save_or_prompt_retry(parent, model)

    assert "Untitled" in critical.call_args.args[2]
