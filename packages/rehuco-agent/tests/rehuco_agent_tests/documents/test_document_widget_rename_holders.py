"""Tests for the magnifier on a refused rename's banner row (#505): it is offered for a refusal over an open handle,
and opens the dialog asking what holds the record's files."""

from pathlib import Path
from typing import Final

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolButton
from pytest_mock import MockerFixture
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from .test_document_widget import (  # noqa: F401  # pylint: disable=unused-import
    banner,
    fixture_refimages_model,
    fixture_refimages_widget,
)

RECORD: Final = Path("/fake/library/pack/info.rehu")
REFUSED: Final = 'Could not rename "pack" to "new": The process cannot access the file.'


def find_holders_action(widget: DocumentWidget) -> QAction:
    """The magnifier's action, which the banner row carries.

    :param widget: the document widget.
    :returns: the action.
    """
    return widget.sub_docks._DocumentSubDocks__find_holders_action  # type: ignore[attr-defined]  # pylint: disable=protected-access


def banner_actions(widget: DocumentWidget) -> list[QAction]:
    """The actions the banner's rows show as buttons.

    :param widget: the document widget.
    :returns: one per button.
    """
    return [button.defaultAction() for button in banner(widget).findChildren(QToolButton)]


def banner_texts(widget: DocumentWidget) -> set[str]:
    """What the banner's rows say.

    :param widget: the document widget.
    :returns: each row's text.
    """
    return {label.text() for label in banner(widget).findChildren(QLabel)}


def test_a_rename_refused_over_an_open_handle_offers_the_magnifier(
    refimages_widget: DocumentWidget, refimages_model: RehuDocumentModel
) -> None:
    """The refused rename's row carries the magnifier while the record is offered, and loses it with the offer.

    **Test steps:**

    * offer the record and say the refusal
    * verify the banner shows the magnifier
    * withdraw the offer, keeping the refusal
    * verify the row stays and the magnifier goes
    """
    refimages_model.rename_held = RECORD
    refimages_model.rename_error = REFUSED

    assert banner_actions(refimages_widget) == [find_holders_action(refimages_widget)]

    refimages_model.rename_held = None

    assert not banner_actions(refimages_widget)
    assert REFUSED in banner_texts(refimages_widget)


def test_another_failed_rename_offers_no_magnifier(
    refimages_widget: DocumentWidget, refimages_model: RehuDocumentModel
) -> None:
    """A rename refused for any other reason has nobody to find.

    **Test steps:**

    * say a refusal with no record offered
    * verify the banner shows the row and no button
    """
    refimages_model.rename_error = 'Could not rename "pack" to "new": Permission denied.'

    assert banner_texts(refimages_widget)
    assert not banner_actions(refimages_widget)


def test_the_magnifier_opens_the_holders_dialog_for_the_record(
    refimages_widget: DocumentWidget, refimages_model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """Clicking the magnifier opens a dialog over the document for the record whose rename was refused, deleted
    once closed.

    **Test steps:**

    * offer the record and say the refusal, with the dialog patched
    * trigger the magnifier
    * verify the dialog was built for the record over the document, set to delete on close, and shown
    """
    dialog = mocker.patch("rehuco_agent.documents.document_sub_docks.RenameHoldersDialog")
    refimages_model.rename_held = RECORD
    refimages_model.rename_error = REFUSED

    find_holders_action(refimages_widget).trigger()

    dialog.assert_called_once_with(RECORD, refimages_widget)
    dialog.return_value.show.assert_called_once_with()
    dialog.return_value.setAttribute.assert_called_once()


def test_a_magnifier_triggered_with_no_record_opens_nothing(
    refimages_widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """The action is kept across rebuilds and can be reached with no offer standing; it then does nothing.

    **Test steps:**

    * trigger the magnifier with no record offered, the dialog patched
    * verify no dialog was built
    """
    dialog = mocker.patch("rehuco_agent.documents.document_sub_docks.RenameHoldersDialog")

    find_holders_action(refimages_widget).trigger()

    dialog.assert_not_called()
