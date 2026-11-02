"""Tests for what the player's info panel says about the video loaded (#574)."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QSize
from pytest import mark, param
from rehuco_agent.documents.player_info import player_info_text
from rehuco_agent.documents.player_playlist import PlayerPlaylist

PLAYLIST: Final = [("intro.mp4", Path("intro.mp4")), ("part/two.mp4", Path("part/two.mp4"))]


@mark.parametrize(
    ("size", "length_ms", "position_ms", "expected"),
    [
        param(
            QSize(1920, 1080),
            3_725_000,
            930_000,
            "part/two.mp4\n1920 × 1080 px\n1:02:05\n15:30 (24 %)\n[2/2]",
            id="known",
        ),
        param(None, 0, 65_000, "part/two.mp4\nsize unknown\nlength unknown\n1:05\n[2/2]", id="unknown"),
        param(QSize(), 100_000, 150_000, "part/two.mp4\nsize unknown\n1:40\n2:30 (100 %)\n[2/2]", id="past the end"),
    ],
)
def test_the_info_names_the_video_its_size_length_position_and_place(
    size: QSize | None, length_ms: int, position_ms: int, expected: str
) -> None:
    """**Test steps:**

    * describe the second video of two with the size, length and position given
    * verify the lines: the key, the size or that it is unknown, the length or that it is unknown, the position with
      its share of a known length (never past 100 %), and the place in the playlist
    """
    playlist = PlayerPlaylist(PLAYLIST, "part/two.mp4")

    assert player_info_text(playlist, size, length_ms, position_ms) == expected
