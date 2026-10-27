"""Tests for what a player reads of a video before playing it: its codec and scan type (#317)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Final

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import VideoFormat, read_video_format

MODULE: Final = "rehuco_core.video_format"

VIDEO: Final = Path("/fake/tutorial/01 Intro.mp4")


def parsed(mocker: MockerFixture, *tracks: SimpleNamespace) -> None:
    """Make ``MediaInfo.parse`` answer with ``tracks``.

    :param mocker: pytest-mock fixture.
    :param tracks: the parsed tracks.
    """
    mocker.patch(f"{MODULE}.MediaInfo.parse", return_value=SimpleNamespace(tracks=list(tracks)))


@mark.parametrize(
    ("codec", "scan_type", "expected"),
    [
        param("AVC", "Progressive", VideoFormat("AVC", False), id="progressive"),
        param("HEVC", None, VideoFormat("HEVC", False), id="no scan type"),
        param("AVC", "Interlaced", VideoFormat("AVC", True), id="interlaced"),
        param("AVC", "MBAFF", VideoFormat("AVC", True), id="mbaff"),
        param("MPEG Video", "Mixed", VideoFormat("MPEG Video", True), id="mixed"),
        param("AVC", "interlaced", VideoFormat("AVC", True), id="case is ignored"),
        param(None, "Progressive", VideoFormat(None, False), id="no codec"),
        param("", "Progressive", VideoFormat(None, False), id="empty codec"),
    ],
)
def test_the_first_video_tracks_codec_and_scan_type_are_read(
    mocker: MockerFixture, codec: str | None, scan_type: str | None, expected: VideoFormat
) -> None:
    """Interlaced in whole (``Interlaced``, ``Mixed``) or in part (``MBAFF``) counts as interlaced; anything else,
    and a track that names no scan type at all, does not.

    **Test steps:**

    * parse a file whose General track precedes a Video track carrying the codec and scan type
    * verify the format names the codec, or ``None`` when it is missing or empty, and whether it is interlaced
    """
    parsed(
        mocker,
        SimpleNamespace(track_type="General", format="MPEG-4"),
        SimpleNamespace(track_type="Video", format=codec, scan_type=scan_type),
    )

    assert read_video_format(VIDEO) == expected


def test_only_the_first_video_track_is_read(mocker: MockerFixture) -> None:
    """A second video track (a cover picture, an alternate angle) is not what plays.

    **Test steps:**

    * parse a file with two video tracks
    * verify the first one answers
    """
    parsed(
        mocker,
        SimpleNamespace(track_type="Video", format="AVC", scan_type="Progressive"),
        SimpleNamespace(track_type="Video", format="AV1", scan_type="Interlaced"),
    )

    assert read_video_format(VIDEO) == VideoFormat("AVC", False)


def test_a_track_without_the_attributes_reads_as_unknown(mocker: MockerFixture) -> None:
    """pymediainfo gives a track only the fields MediaInfo reported for it.

    **Test steps:**

    * parse a file whose Video track carries neither a format nor a scan type
    * verify the format knows no codec and is not interlaced
    """
    parsed(mocker, SimpleNamespace(track_type="Video"))

    assert read_video_format(VIDEO) == VideoFormat(None, False)


def test_a_file_without_a_video_track_has_no_format(mocker: MockerFixture) -> None:
    """**Test steps:**

    * parse a file carrying only audio
    * verify nothing is answered
    """
    parsed(mocker, SimpleNamespace(track_type="General"), SimpleNamespace(track_type="Audio"))

    assert read_video_format(VIDEO) is None


@mark.parametrize("error", [RuntimeError("bad file"), OSError("share gone"), FileNotFoundError()])
def test_a_file_that_cannot_be_parsed_has_no_format(mocker: MockerFixture, error: Exception) -> None:
    """Whatever the library and the layer under it raise, the player simply plays without a notice.

    **Test steps:**

    * make the parse raise
    * verify nothing is answered and nothing is raised
    """
    mocker.patch(f"{MODULE}.MediaInfo.parse", side_effect=error)

    assert read_video_format(VIDEO) is None


@mark.parametrize(
    ("codec", "expected"),
    [("AV1", True), ("av1", True), ("AVC", False), ("HEVC", False), (None, False)],
)
def test_av1_is_told_by_its_codec_name(codec: str | None, expected: bool) -> None:
    """**Test steps:**

    * build formats of several codecs
    * verify only AV1, in either case, is AV1
    """
    assert VideoFormat(codec, False).is_av1 is expected
