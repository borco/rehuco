"""Tests for what a document's sub-docks show and allow while it waits for its storage to answer (#698).

Driven through `DocumentWidget`, as ``test_document_sub_docks_reads`` is, over the same in-memory model; the wait is
the model's :attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.storage_wait`, set here as the
documents area sets it -- when it is set is that area's own tests' subject.
"""

from collections.abc import Callable
from unittest.mock import MagicMock

from borco_pyside.widgets import MessageBannerSeverity
from PySide6.QtWidgets import QLineEdit
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import OFFLINE_STORAGE_MESSAGE, WAITING_STORAGE_MESSAGE
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.storage_wait import StorageWait

from .test_document_sub_docks_saves import (  # noqa: F401  # pylint: disable=unused-import
    fixture_banner_rows,
    fixture_model,
    shown,
)
from .test_document_widget import _drag_onto_main_editor, _url_mime_data, drag_onto_images_dock, find_on_surfaces


def test_a_document_waiting_for_its_storage_says_so_and_locks_its_editors_and_revert(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """While its storage has not answered, the document shows nothing an edit could be based on and has no file to
    read again: the banner says what it waits for, and the editors and Revert are locked until the storage answers.

    **Test steps:**

    * say the document's storage was asked
    * verify the banner's waiting row, every editor disabled, and Revert disabled
    * say the storage did not answer, and verify the row says so, as a warning
    * say the wait is over
    * verify the row is gone, and the editors and Revert are back
    """
    widget, spy = banner_rows
    path = model.path

    model.storage_wait = StorageWait.ASKING

    assert shown(spy) == [(MessageBannerSeverity.INFO, WAITING_STORAGE_MESSAGE.format(path=path))]
    editors = find_on_surfaces(widget, QLineEdit)
    assert editors
    assert not any(editor.isEnabled() for editor in editors)
    assert not widget.revert_action.isEnabled()

    model.storage_wait = StorageWait.OFFLINE

    assert shown(spy) == [(MessageBannerSeverity.WARNING, OFFLINE_STORAGE_MESSAGE.format(path=path))]
    assert not widget.revert_action.isEnabled()

    model.storage_wait = None

    assert shown(spy) == []
    assert all(editor.isEnabled() for editor in editors)
    assert widget.revert_action.isEnabled()


@mark.parametrize(
    ("dock", "url"),
    [
        (_drag_onto_main_editor, "https://www.artstation.com/artwork/example"),
        (drag_onto_images_dock, "https://example.com/photo.jpg"),
    ],
    ids=["main editor", "images"],
)
def test_a_drop_is_refused_while_the_document_waits_for_its_storage(
    banner_rows: tuple[DocumentWidget, MagicMock],
    model: RehuDocumentModel,
    qtbot: QtBot,
    dock: Callable[..., tuple[bool, bool]],
    url: str,
) -> None:
    """A link dropped on a document still waiting for its storage is refused at the enter, and taken once the wait is
    over.

    **Test steps:**

    * say the document's storage was asked, and drag a link onto the dock
    * verify neither the enter nor the drop was accepted
    * say the wait is over, and drag again
    * verify both were accepted
    """
    widget, _ = banner_rows
    model.storage_wait = StorageWait.ASKING

    assert dock(widget, qtbot, _url_mime_data(url)) == (False, False)

    model.storage_wait = None

    assert dock(widget, qtbot, _url_mime_data(url)) == (True, True)
