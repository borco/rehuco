"""Tests for where a double-clicked video goes: the document's player, always (#317, #319, [[plugins#in-app-player]]).

Which engine decodes it is the player's business, decided where the player is built; the browser only names the
video.
"""

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QTableView
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.files_view import FilesView

from rehuco_agent_tests.documents.test_files_view_progress import (  # noqa: F401  # pylint: disable=unused-import
    fixture_model,
    fixture_view,
    names,
)

pytestmark = mark.usefixtures("real_path_stat")


def test_a_double_clicked_video_goes_to_the_documents_player(qtbot: QtBot, view: FilesView) -> None:
    """**Test steps:**

    * listen to the browser's activations and double-click the tutorial's first video
    * verify the player signal carried its key and the status bar was told nothing
    """
    del qtbot
    played: list[str] = []
    status: list[str] = []
    view.video_activated.connect(played.append)
    view.status_message.connect(status.append)

    view.activate(names(view).index("a.mp4"))

    assert played == ["a.mp4"]
    assert not status


def test_a_clicked_video_is_reported_for_its_notes_and_plays_nothing(qtbot: QtBot, view: FilesView) -> None:
    """**Test steps:**

    * click the tutorial's first video
    * verify the click named its key and the player was not asked to play it
    """
    played: list[str] = []
    view.video_activated.connect(played.append)
    table = view.findChild(QTableView)
    assert table is not None

    with qtbot.waitSignal(view.video_clicked) as clicked:
        table.clicked.emit(view.proxy.index(names(view).index("a.mp4"), 0))

    assert clicked.args == ["a.mp4"]
    assert not played


def test_a_click_on_no_video_row_reports_nothing(qtbot: QtBot, view: FilesView) -> None:
    """**Test steps:**

    * click where there is no row
    * verify no video was reported
    """
    table = view.findChild(QTableView)
    assert table is not None

    with qtbot.assertNotEmitted(view.video_clicked):
        table.clicked.emit(QModelIndex())
