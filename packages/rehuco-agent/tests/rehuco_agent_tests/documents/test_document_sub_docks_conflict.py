"""Tests for the banner row a refused save raises (#416), and how it stands in for the changed-on-disk row (#487)."""

from pathlib import Path

from borco_pyside.widgets import MessageBanner
from PySide6.QtWidgets import QLabel
from pytest import mark, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import CHANGED_ON_DISK_MESSAGE, CONFLICT_MESSAGE
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RecordConflict

from .test_rehu_document_model_conflict import edit_on_disk, opened, retitle, write_record

pytestmark = mark.usefixtures("real_path_stat")


def banner_rows(widget: DocumentWidget) -> list[str]:
    """What each row of the document's banner says.

    :param widget: the document's widget.
    :returns: the rows' texts.
    """
    banner = widget.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return [label.text() for label in banner.findChildren(QLabel)]


def refused(qtbot: QtBot, tmp_path: Path) -> tuple[DocumentWidget, RehuDocumentModel]:
    """A document widget over a real record whose title was edited here while the file's changed on disk.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: where the record is written.
    :returns: the widget, and its model, not saved yet.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    model.title = "Mine"
    edit_on_disk(path, retitle("Theirs, and longer"))
    return widget, model


def test_a_refused_save_is_said_on_the_banner_until_a_revert(qtbot: QtBot, tmp_path: Path) -> None:
    """The edits are still unsaved after a refused save, and the banner says why and what to do.

    **Test steps:**

    * open a record, edit it here and change it on disk, and save it
    * verify the banner holds the conflict row
    * revert the document
    * verify the row is gone
    """
    widget, model = refused(qtbot, tmp_path)

    with raises(RecordConflict):
        model.save()

    assert CONFLICT_MESSAGE in banner_rows(widget)

    model.revert()

    assert CONFLICT_MESSAGE not in banner_rows(widget)


def test_the_conflict_row_stands_in_for_the_changed_on_disk_row(qtbot: QtBot, tmp_path: Path) -> None:
    """Both rows describe the same file changed under the edits; once a save was refused, only the conflict row is
    shown, which says what Save does now.

    **Test steps:**

    * open a record, edit it here and change it on disk, and report the file as it is now
    * verify the banner holds the changed-on-disk row
    * save it, and verify the conflict row replaced that row
    * drop the conflict, and verify the changed-on-disk row is back
    """
    widget, model = refused(qtbot, tmp_path)
    path = tmp_path / "info.rehu"
    stat = path.stat()
    model.note_file_signature(stat.st_mtime_ns, stat.st_size)
    assert model.changed_on_disk

    assert CHANGED_ON_DISK_MESSAGE in banner_rows(widget)

    with raises(RecordConflict):
        model.save()

    rows = banner_rows(widget)
    assert CONFLICT_MESSAGE in rows
    assert CHANGED_ON_DISK_MESSAGE not in rows

    model.conflict = None

    rows = banner_rows(widget)
    assert CHANGED_ON_DISK_MESSAGE in rows
    assert CONFLICT_MESSAGE not in rows
