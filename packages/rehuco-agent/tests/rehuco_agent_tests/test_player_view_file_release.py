"""The one player test that plays for real and renames: a stopped player must let go of its video, or the OS refuses to
rename the resource's folder (#317).

Found by renaming a folder under a stopped ``QMediaPlayer`` on Windows -- a stopped player still holds its source, so
the file stays open until the source is cleared. ``test_player_view`` tests the player with Qt Multimedia's playing
methods patched; this plays the committed clip.
"""

import shutil
from pathlib import Path
from typing import Final

from PySide6.QtMultimedia import QMediaPlayer
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder

CLIP: Final = Path(__file__).resolve().parents[4] / "ci" / "playback-check.mp4"
"""The clip the release workflow plays, committed beside its scripts."""

WAIT_MS: Final = 15_000
"""The longest a cold start of FFmpeg is given to get a video playing."""


def test_a_stopped_player_lets_go_of_the_video_so_the_folder_can_be_renamed(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path
) -> None:
    """**Test steps:**

    * copy the clip into a folder and play it for real until it is playing
    * stop the player
    * verify the folder can be renamed, which the OS refuses while a video is open in it
    """
    folder = tmp_path / "tutorial"
    folder.mkdir()
    video = folder / "clip.mp4"
    shutil.copy(CLIP, video)
    model = mocker.create_autospec(RehuDocumentModel, instance=True)
    model.progress_of.return_value = None
    model.measured_videos.return_value = {}
    model.video_notes_of.return_value = ""
    model.notes_changed = mocker.Mock()
    model.path = folder / "info.rehu"
    model.rename_coordinator = None
    recorder = mocker.create_autospec(WatchProgressRecorder, instance=True)
    view = PlayerView(model, recorder)
    qtbot.addWidget(view)

    view.jump("clip.mp4")
    qtbot.waitUntil(lambda: view.findChild(QMediaPlayer) is not None, timeout=WAIT_MS)
    player = view.findChild(QMediaPlayer)
    assert isinstance(player, QMediaPlayer)
    qtbot.waitUntil(lambda: player.mediaStatus() == QMediaPlayer.MediaStatus.BufferedMedia, timeout=WAIT_MS)
    view.stop()

    folder.rename(tmp_path / "renamed")

    assert (tmp_path / "renamed" / "clip.mp4").is_file()
