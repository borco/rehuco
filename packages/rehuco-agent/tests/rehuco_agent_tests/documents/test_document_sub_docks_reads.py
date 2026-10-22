"""Tests for what a document's sub-docks show and allow while its file is being read off the GUI thread (#564).

Driven through `DocumentWidget`, as ``test_document_sub_docks_saves`` is, over the same in-memory model; the read is
the model's :attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.reading`, set here as a read out would
set it -- when it is set is the model's own tests' subject.
"""

from collections.abc import Callable
from unittest.mock import MagicMock

from borco_pyside.widgets import MessageBannerSeverity
from PySide6.QtWidgets import QLineEdit
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import READING_MESSAGE
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from .test_document_sub_docks_saves import (  # noqa: F401  # pylint: disable=unused-import
    fixture_banner_rows,
    fixture_model,
    shown,
)
from .test_document_widget import _drag_onto_main_editor, _url_mime_data, drag_onto_images_dock, find_on_surfaces


def test_a_document_waiting_for_its_file_says_so_and_locks_its_editors_save_and_revert(
    banner_rows: tuple[DocumentWidget, MagicMock], model: RehuDocumentModel
) -> None:
    """While the file is being read, what the document shows is nothing an edit or a save could be based on: the
    banner says it is reading, and the editors, Save and Revert are locked until the file arrives.

    **Test steps:**

    * edit the document, so Save is offered
    * say its file is being read
    * verify the banner's reading row, every editor disabled, and Save and Revert disabled
    * say the read arrived
    * verify the row is gone, and the editors, Save and Revert are back
    """
    widget, spy = banner_rows
    model.title = "Edited"
    path = model.path

    model.reading = path

    assert shown(spy) == [(MessageBannerSeverity.INFO, READING_MESSAGE.format(path=path))]
    editors = find_on_surfaces(widget, QLineEdit)
    assert editors
    assert not any(editor.isEnabled() for editor in editors)
    assert (widget.save_action.isEnabled(), widget.revert_action.isEnabled()) == (False, False)

    model.reading = None

    assert shown(spy) == []
    assert all(editor.isEnabled() for editor in editors)
    assert (widget.save_action.isEnabled(), widget.revert_action.isEnabled()) == (True, True)


@mark.parametrize(
    ("dock", "url"),
    [
        (_drag_onto_main_editor, "https://www.artstation.com/artwork/example"),
        (drag_onto_images_dock, "https://example.com/photo.jpg"),
    ],
    ids=["main editor", "images"],
)
def test_a_drop_is_refused_while_the_document_waits_for_its_file_and_taken_once_it_arrived(
    banner_rows: tuple[DocumentWidget, MagicMock],
    model: RehuDocumentModel,
    qtbot: QtBot,
    dock: Callable[..., tuple[bool, bool]],
    url: str,
) -> None:
    """A link dropped on a document still waiting for its file is refused at the enter: what it shows is nothing a
    scrape or an image could land on. Once the file has arrived -- or while the document shows its save not landed,
    which never waits -- the same drop is taken.

    **Test steps:**

    * say the document's file is being read, and drag a link onto the dock
    * verify neither the enter nor the drop was accepted
    * say the read arrived, and drag again
    * verify both were accepted
    """
    widget, _ = banner_rows
    model.reading = model.path

    assert dock(widget, qtbot, _url_mime_data(url)) == (False, False)

    model.reading = None

    assert dock(widget, qtbot, _url_mime_data(url)) == (True, True)
