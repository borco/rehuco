"""The one test that plays for real: the clip the release workflow plays on a built bundle (#317).

``test_playback_check`` tests the check's logic with Qt Multimedia's playing methods patched; this is what that step
depends on, the committed clip decoding, showing a picture and moving, in whatever Qt this environment has.
"""

from pathlib import Path
from typing import Final

from pytestqt.qtbot import QtBot
from rehuco_agent.playback_check import check_playback

CLIP: Final = Path(__file__).resolve().parents[4] / "ci" / "playback-check.mp4"
"""The clip the release workflow plays, committed beside its scripts."""


def test_the_committed_clip_plays_through_qt_multimedia(qtbot: QtBot) -> None:
    """**Test steps:**

    * play the committed clip, with nothing patched
    * verify it showed a picture and moved: the check passed
    """
    del qtbot

    assert CLIP.is_file()
    assert check_playback(CLIP) == 0
