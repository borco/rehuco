"""Tests for where a double-clicked video goes: the document's player, always (#317, #319, [[plugins#in-app-player]]).

Which engine decodes it is the player's business, decided where the player is built; the browser only names the
video.
"""

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
