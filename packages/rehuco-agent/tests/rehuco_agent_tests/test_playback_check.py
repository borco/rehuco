"""Tests for the playback smoke test the release workflow runs on a built bundle (#317).

The logic is tested with the playing methods of Qt Multimedia patched on their classes and its signals emitted by hand;
playing the committed clip for real is ``test_playback_check_clip``'s.
"""

import os
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from PySide6.QtCore import QSize, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoFrameFormat, QVideoSink
from pytest import CaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.playback_check import PlaybackCheck, check_playback

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

SHORT_MS: Final = 10


@fixture(name="play", autouse=True)
def fixture_play(mocker: MockerFixture) -> Mock:
    """Patch what would start real playback, so the logic is tested with the signals a test emits.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``play``.
    """
    mocker.patch.object(QMediaPlayer, "setSource")
    mocker.patch.object(QMediaPlayer, "stop")
    return mocker.patch.object(QMediaPlayer, "play")


@fixture(name="check")
def fixture_check(delete_at_teardown: DeleteAtTeardown) -> PlaybackCheck:
    """A check of a clip, with a long wait.

    :param delete_at_teardown: deletes the bare check when the test ends.
    :returns: the check.
    """
    return delete_at_teardown(PlaybackCheck(Path("clip.mp4")))


def statuses(check: PlaybackCheck) -> list[int]:
    """Collect what a check reports.

    :param check: the check.
    :returns: the list its exit statuses are appended to.
    """
    reported: list[int] = []
    check.finished.connect(reported.append)
    return reported


def picture() -> QVideoFrame:
    """A frame the sink counts as a picture.

    :returns: a valid frame.
    """
    return QVideoFrame(QVideoFrameFormat(QSize(2, 2), QVideoFrameFormat.PixelFormat.Format_RGBX8888))


def sink_of(check: PlaybackCheck) -> QVideoSink:
    """The sink a check plays into.

    :param check: the check.
    :returns: its sink.
    """
    sink = check.findChild(QVideoSink)
    assert isinstance(sink, QVideoSink)
    return sink


def player_of(check: PlaybackCheck) -> QMediaPlayer:
    """The player a check plays with.

    :param check: the check.
    :returns: its player.
    """
    player = check.findChild(QMediaPlayer)
    assert isinstance(player, QMediaPlayer)
    return player


def test_starting_plays_the_clip(check: PlaybackCheck, play: Mock, mocker: MockerFixture) -> None:
    """**Test steps:**

    * start a check
    * verify the clip was made the source and played
    """
    set_source = mocker.patch.object(QMediaPlayer, "setSource")

    check.start()

    set_source.assert_called_once_with(QUrl.fromLocalFile("clip.mp4"))
    play.assert_called_once_with()


def test_a_picture_and_a_moving_position_pass_it(check: PlaybackCheck, capsys: CaptureFixture[str]) -> None:
    """Both are needed: a picture is what a missing decoder lacks, and the clock is what a stalled backend lacks.

    **Test steps:**

    * show a picture, then move the position
    * verify it reported 0 once, saying how many frames played, on stdout
    """
    reported = statuses(check)

    sink_of(check).videoFrameChanged.emit(picture())
    assert not reported
    player_of(check).positionChanged.emit(40)

    assert reported == [0]
    assert "played clip.mp4: 1 frames" in capsys.readouterr().out


def test_a_position_that_moves_before_any_picture_does_not_pass_it(check: PlaybackCheck) -> None:
    """AV1 on a machine with no decoder plays the clock and no picture.

    **Test steps:**

    * move the position without a picture
    * verify nothing was reported
    """
    reported = statuses(check)

    player_of(check).positionChanged.emit(40)

    assert not reported


def test_a_position_still_at_zero_does_not_count_as_moving(check: PlaybackCheck) -> None:
    """**Test steps:**

    * show a picture and report position 0
    * verify nothing was reported
    """
    reported = statuses(check)

    sink_of(check).videoFrameChanged.emit(picture())
    player_of(check).positionChanged.emit(0)

    assert not reported


def test_an_empty_frame_is_not_a_picture(check: PlaybackCheck) -> None:
    """**Test steps:**

    * give the sink an empty frame and move the position
    * verify nothing was reported
    """
    reported = statuses(check)

    sink_of(check).videoFrameChanged.emit(QVideoFrame())
    player_of(check).positionChanged.emit(40)

    assert not reported


def test_an_error_fails_it_with_qts_own_words(check: PlaybackCheck, capsys: CaptureFixture[str]) -> None:
    """**Test steps:**

    * let the player report an error
    * verify it reported 1 once, saying why, on stderr
    """
    reported = statuses(check)

    player_of(check).errorOccurred.emit(QMediaPlayer.Error.ResourceError, "no backend")

    assert reported == [1]
    assert "could not play clip.mp4: no backend" in capsys.readouterr().err


def test_a_clip_that_never_shows_fails_it_when_the_time_is_up(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown, capsys: CaptureFixture[str]
) -> None:
    """**Test steps:**

    * start a check that waits only a moment, with nothing ever played
    * wait for its report
    * verify it reported 1, saying nothing was seen
    """
    check = delete_at_teardown(PlaybackCheck(Path("clip.mp4"), SHORT_MS))

    with qtbot.waitSignal(check.finished, timeout=2000) as report:
        check.start()

    assert report.args == [1]
    assert "0 frames, position moved: False" in capsys.readouterr().err


def test_it_reports_once_however_much_more_happens(check: PlaybackCheck) -> None:
    """**Test steps:**

    * pass it, then let the player report an error
    * verify only the first report was made
    """
    reported = statuses(check)
    sink_of(check).videoFrameChanged.emit(picture())
    player_of(check).positionChanged.emit(40)

    player_of(check).errorOccurred.emit(QMediaPlayer.Error.ResourceError, "late")

    assert reported == [0]


def test_checking_runs_the_check_and_answers_its_status(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The offscreen platform is a default only: it is set when the environment names none.

    **Test steps:**

    * clear the platform and make a check report 7 as soon as it starts
    * run the check
    * verify its status was returned and the offscreen platform was defaulted
    """
    del qtbot
    mocker.patch.dict(os.environ)
    os.environ.pop("QT_QPA_PLATFORM", None)
    mocker.patch.object(PlaybackCheck, "start", autospec=True, side_effect=lambda check: check.finished.emit(7))

    assert check_playback(Path("clip.mp4")) == 7
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
