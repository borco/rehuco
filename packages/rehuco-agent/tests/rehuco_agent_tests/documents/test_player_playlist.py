"""Tests for the playlist a player steps through, and where each video starts (#317)."""

from pathlib import Path
from typing import Final

from pytest import mark, param, raises
from rehuco_agent.documents.player_playlist import PlayerPlaylist, PlaylistVideo
from rehuco_core import ProgressEntry

FOLDER: Final = Path("/fake/tutorial")
VIDEOS: Final = [(name, FOLDER / name) for name in ("01.mp4", "02.mp4", "03.mp4")]


def test_the_playlist_opens_on_the_clicked_video() -> None:
    """**Test steps:**

    * open a playlist of three videos on the second
    * verify the second is current and both neighbours exist
    """
    playlist = PlayerPlaylist(VIDEOS, "02.mp4")

    assert playlist.current == PlaylistVideo("02.mp4", FOLDER / "02.mp4")
    assert playlist.has_previous is True
    assert playlist.has_next is True


def test_a_video_that_is_not_in_the_list_cannot_be_opened() -> None:
    """**Test steps:**

    * open a playlist on a key it does not hold
    * verify it is refused naming the key
    """
    with raises(ValueError, match="gone.mp4"):
        PlayerPlaylist(VIDEOS, "gone.mp4")


def test_stepping_walks_the_list_in_order() -> None:
    """**Test steps:**

    * open on the first video and step forward twice, then back once
    * verify each step answers the video it moved to
    """
    playlist = PlayerPlaylist(VIDEOS, "01.mp4")

    assert playlist.step(1) == PlaylistVideo("02.mp4", FOLDER / "02.mp4")
    assert playlist.step(1) == PlaylistVideo("03.mp4", FOLDER / "03.mp4")
    assert playlist.step(-1) == PlaylistVideo("02.mp4", FOLDER / "02.mp4")
    assert playlist.current.key == "02.mp4"


def test_stepping_stops_at_the_last_video() -> None:
    """The last video is the end of the list, not a way round to the first.

    **Test steps:**

    * open on the last video and step forward
    * verify nothing moved and there is no next
    """
    playlist = PlayerPlaylist(VIDEOS, "03.mp4")

    assert playlist.step(1) is None
    assert playlist.current.key == "03.mp4"
    assert playlist.has_next is False
    assert playlist.has_previous is True


def test_stepping_stops_at_the_first_video() -> None:
    """**Test steps:**

    * open on the first video and step back
    * verify nothing moved and there is no previous
    """
    playlist = PlayerPlaylist(VIDEOS, "01.mp4")

    assert playlist.step(-1) is None
    assert playlist.current.key == "01.mp4"
    assert playlist.has_previous is False
    assert playlist.has_next is True


def test_a_step_past_the_end_moves_nothing_even_when_it_would_land_on_a_video_again() -> None:
    """A step is all or nothing: a jump of two from the second video does not stop on the third.

    **Test steps:**

    * open on the second of three and step by two
    * verify nothing moved
    """
    playlist = PlayerPlaylist(VIDEOS, "02.mp4")

    assert playlist.step(2) is None
    assert playlist.current.key == "02.mp4"


def test_a_step_of_zero_moves_nothing() -> None:
    """**Test steps:**

    * step by zero
    * verify nothing is answered
    """
    assert PlayerPlaylist(VIDEOS, "02.mp4").step(0) is None


def test_a_single_video_has_neither_neighbour() -> None:
    """**Test steps:**

    * open a playlist of one video
    * verify there is no previous or next, and stepping either way moves nothing
    """
    playlist = PlayerPlaylist(VIDEOS[:1], "01.mp4")

    assert (playlist.has_previous, playlist.has_next) == (False, False)
    assert playlist.step(1) is None
    assert playlist.step(-1) is None


@mark.parametrize(
    ("entry", "expected"),
    [
        param(None, 0.0, id="never opened"),
        param(ProgressEntry(0.0), 0.0, id="opened and left at the start"),
        param(ProgressEntry(42.5, 100.0), 42.5, id="partly watched"),
        param(ProgressEntry(99.5, 100.0, viewed=True), 0.0, id="watched to the end"),
        param(ProgressEntry(10.0, None, viewed=True), 0.0, id="viewed by hand"),
    ],
)
def test_a_video_resumes_where_it_was_left_unless_it_was_watched(entry: ProgressEntry | None, expected: float) -> None:
    """**Test steps:**

    * ask where a video starts for each kind of progress
    * verify a partial one resumes, and an unopened or viewed one starts at 0
    """
    assert PlayerPlaylist.start_position(entry) == expected
