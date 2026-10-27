"""Tests for what a document's sub-docks do for watch progress (#316): the banner that says it is not being saved, and
the recorder a player writes through, flushed when the document goes."""

from pathlib import Path
from typing import Final

from borco_pyside.widgets import MessageBanner
from PySide6.QtWidgets import QLabel
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget

from .test_rehu_document_model_conflict import opened, write_record

pytestmark = mark.usefixtures("real_path_stat")

REASON: Final = "Watch progress is not being saved: the record is locked."
"""What the model says when it keeps progress to itself."""


def banner_rows(widget: DocumentWidget) -> list[str]:
    """What each row of the document's banner says.

    :param widget: the document's widget.
    :returns: the rows' texts.
    """
    banner = widget.findChild(MessageBanner)
    assert isinstance(banner, MessageBanner)
    return [label.text() for label in banner.findChildren(QLabel)]


def test_the_banner_says_progress_is_not_being_saved_for_as_long_as_the_model_does(
    tmp_path: Path, qtbot: QtBot
) -> None:
    """A warning row follows :attr:`~RehuDocumentModel.progress_unsaved`, and goes when it is cleared.

    **Test steps:**

    * open a document and verify the banner has no such row
    * have the model say progress is not being saved, and verify the row appears
    * clear it and verify the row is gone
    """
    record = tmp_path / "info.rehu"
    write_record(record, "Old")
    model = opened(record)
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    assert REASON not in banner_rows(widget)

    model.progress_unsaved = REASON
    assert REASON in banner_rows(widget)

    model.progress_unsaved = ""
    assert REASON not in banner_rows(widget)


def test_closing_the_document_writes_the_position_a_player_left_waiting(
    tmp_path: Path, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The last position of a video is not lost to the interval: the document's detach flushes the recorder.

    **Test steps:**

    * open a document, spy on its progress write, and report a position through the recorder
    * verify nothing was written yet
    * detach the document's sub-docks, as closing it does
    * verify the position was written
    """
    record = tmp_path / "info.rehu"
    write_record(record, "Old")
    model = opened(record)
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    write = mocker.patch.object(model, "record_progress")

    widget.sub_docks.watch_progress.position("a.mp4", 3.0, 10.0)
    write.assert_not_called()
    widget.sub_docks.detach()

    write.assert_called_once_with("a.mp4", 3.0, 10.0)
