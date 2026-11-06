"""Tests for the libvlc engine's subtitles: the tracks its keys visit, the choice applied once libvlc has listed them,
and the picture a change made while paused refreshes ([[plugins#in-app-player]], #618)."""

import sys
from typing import Any, Final
from unittest.mock import Mock

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from pytest import MonkeyPatch, fixture, mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.documents import vlc_media_player
from rehuco_agent.documents.vlc_media_player import VlcMediaPlayer
from rehuco_agent.documents.vlc_surface import VlcSurface
from rehuco_core import SubtitleChoice, SubtitlePreferences

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

from .test_vlc_media_player import (  # pylint: disable=unused-import
    EventType,
    FakeLibvlc,
    fixture_engine,  # noqa: F401
    fixture_library,  # noqa: F401
    fixture_libvlc,  # noqa: F401
    fixture_surface,  # noqa: F401
)

# region Subtitles

DESCRIBED: Final = [
    (-1, b"Disable"),
    (1, b"Track 1"),
    (2, b"Track 2 - [Romanian]"),
    (3, b"Track 3 - [French]"),
    (4, b"Track 4 - [English]"),
]
"""What libvlc lists for a video with a bare subtitle file and one each in Romanian, French and English."""

ENGLISH_ROMANIAN: Final = SubtitlePreferences(("English", "Romanian"), show_all=False)


def give_subtitles(libvlc: FakeLibvlc, described: list[tuple[int, Any]] | None = None, *, shown: int = -1) -> None:
    """Give the fake player subtitle tracks and a track shown, which ``video_set_spu`` changes as libvlc's does.

    :param libvlc: the fake.
    :param described: what ``video_get_spu_description`` answers.
    :param shown: the id shown to begin with.
    """
    libvlc.player.video_get_spu_description.return_value = DESCRIBED if described is None else described
    current = {"id": shown}
    libvlc.player.video_get_spu.side_effect = lambda: current["id"]

    def set_spu(track: int) -> int:
        """Show a track, as libvlc does."""
        current["id"] = track
        return 0

    libvlc.player.video_set_spu.side_effect = set_spu


def spu_calls(libvlc: FakeLibvlc) -> list[int]:
    """The tracks ``video_set_spu`` was asked for, in order.

    :param libvlc: the fake.
    :returns: the ids.
    """
    return [call.args[0] for call in libvlc.player.video_set_spu.call_args_list]


def chosen(engine: VlcMediaPlayer) -> list[SubtitleChoice]:
    """Listen to what the reader chooses.

    :param engine: the engine.
    :returns: the list the choices are appended to.
    """
    choices: list[SubtitleChoice] = []
    engine.subtitle_chosen.connect(choices.append)
    return choices


@fixture(name="quick_engine")
def fixture_quick_engine(library: Mock, surface: VlcSurface, delete_at_teardown: DeleteAtTeardown) -> VlcMediaPlayer:
    """An engine that reads the track list every few milliseconds, with a file opened.

    :param library: the proxy.
    :param surface: the widget.
    :param delete_at_teardown: deletes what is built bare.
    :returns: the engine.
    """
    engine = delete_at_teardown(VlcMediaPlayer(library, surface, subtitle_poll_ms=5))
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    return engine


def open_file(engine: VlcMediaPlayer) -> None:
    """Open a file, which is when the engine starts waiting for libvlc's track list.

    :param engine: the engine.
    """
    engine.setSource(QUrl.fromLocalFile("C:/clips/a.mp4" if sys.platform == "win32" else "/clips/a.mp4"))


def test_next_subtitle_cycles_through_none_and_the_languages_listed_in_their_order(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * list English then Romanian, only selected, over a video with a bare file, Romanian, French and English tracks
    * ask for the next one three times, from none
    * verify libvlc was given English, Romanian and none: the bare and French tracks are not visited
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)

    for _ in range(3):
        engine.next_subtitle()

    assert spu_calls(libvlc) == [4, 2, -1]


def test_previous_subtitle_walks_the_cycle_the_other_way(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * list English then Romanian, only selected, and ask for the previous track three times, from none
    * verify libvlc was given Romanian, English and none
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)

    for _ in range(3):
        engine.previous_subtitle()

    assert spu_calls(libvlc) == [2, 4, -1]


def test_showing_all_languages_visits_the_unknown_and_the_unlisted_ones_after_the_listed(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * list Romanian, show all, and ask for the next track four times
    * verify Romanian, the bare file, French and English, in that order
    """
    engine.set_subtitle_preferences(SubtitlePreferences(("Romanian",), show_all=True))
    give_subtitles(libvlc)

    for _ in range(4):
        engine.next_subtitle()

    assert spu_calls(libvlc) == [2, 1, 3, 4]


def test_a_track_libvlc_shows_that_the_cycle_does_not_visit_is_left_for_the_first(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * have libvlc show the French track, which the list leaves out
    * ask for the next track
    * verify it is the cycle's first, English
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc, shown=3)

    engine.next_subtitle()

    assert spu_calls(libvlc) == [4]


def test_the_toggle_turns_off_and_returns_to_the_track_shown(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * show Romanian, then toggle twice
    * verify the subtitles went off and came back to Romanian, and that the choices say so
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc, shown=2)
    choices = chosen(engine)

    engine.toggle_subtitles()
    engine.toggle_subtitles()

    assert spu_calls(libvlc) == [-1, 2]
    assert choices == [SubtitleChoice(False, "Romanian", False), SubtitleChoice(True, "Romanian", False)]


def test_none_reached_by_cycling_forgets_the_track_so_the_toggle_starts_at_the_first(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * show Romanian, the last of the cycle, and go to the next, which is none
    * toggle
    * verify the first track, English, is shown, and that the choices say none was chosen and then English
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc, shown=2)
    choices = chosen(engine)

    engine.next_subtitle()
    engine.toggle_subtitles()

    assert spu_calls(libvlc) == [-1, 4]
    assert choices == [SubtitleChoice(shown=False), SubtitleChoice(True, "English", False)]


def test_a_track_with_no_language_is_chosen_as_unknown(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * list Unknown only, and ask for the next track
    * verify the bare file is shown and the choice says unknown, with no language
    """
    engine.set_subtitle_preferences(SubtitlePreferences(("Unknown",), show_all=False))
    give_subtitles(libvlc, [(-1, "Disable"), (1, "Track 1")])  # a description that is text, not bytes
    choices = chosen(engine)

    engine.next_subtitle()

    assert spu_calls(libvlc) == [1]
    assert choices == [SubtitleChoice(True, None, True)]


@mark.parametrize(
    "described",
    [param([], id="no list"), param(None, id="no answer"), param([(-1, b"Disable")], id="only none")],
)
def test_a_video_with_no_subtitles_makes_the_keys_do_nothing(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, described: list[tuple[int, bytes]] | None
) -> None:
    """**Test steps:**

    * give a video no subtitle track, in each way libvlc may say so
    * ask for the next, the previous and the toggle
    * verify libvlc was never asked to show a track
    """
    libvlc.player.video_get_spu_description.return_value = described
    libvlc.player.video_get_spu.return_value = -1
    choices = chosen(engine)

    engine.next_subtitle()
    engine.previous_subtitle()
    engine.toggle_subtitles()

    libvlc.player.video_set_spu.assert_not_called()
    assert not choices


def test_a_video_with_no_track_of_the_list_makes_the_keys_do_nothing(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * list Romanian only, over a video with English alone
    * ask for the next track
    * verify nothing was shown
    """
    engine.set_subtitle_preferences(SubtitlePreferences(("Romanian",), show_all=False))
    give_subtitles(libvlc, [(-1, b"Disable"), (4, b"Track 4 - [English]")])

    engine.next_subtitle()

    libvlc.player.video_set_spu.assert_not_called()


def test_the_choice_is_applied_once_libvlc_has_listed_the_tracks(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """The list is empty for seconds after a video starts and a sidecar's tracks come after the video's own, so the
    choice waits for two reads that agree.

    **Test steps:**

    * choose Romanian, and open a file whose list libvlc fills in and then keeps
    * verify nothing is shown until then, and Romanian is shown once, without a choice being reported
    """
    give_subtitles(libvlc, shown=1)
    reads = iter([[], [(-1, b"Disable"), (1, b"Track 1")]])
    libvlc.player.video_get_spu_description.side_effect = lambda: next(reads, DESCRIBED)
    quick_engine.set_subtitle_choice(SubtitleChoice(True, "Romanian"))
    choices = chosen(quick_engine)

    open_file(quick_engine)

    qtbot.waitUntil(lambda: spu_calls(libvlc) == [2], timeout=2000)
    qtbot.wait(50)
    assert spu_calls(libvlc) == [2]
    assert not choices


def test_a_choice_of_no_subtitles_turns_off_the_track_libvlc_chose(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose no subtitles, and open a file whose tracks libvlc lists with the bare file shown
    * verify libvlc is told to show none
    """
    give_subtitles(libvlc, shown=1)
    quick_engine.set_subtitle_choice(SubtitleChoice(shown=False))

    open_file(quick_engine)

    qtbot.waitUntil(lambda: spu_calls(libvlc) == [-1], timeout=2000)


def test_a_choice_for_a_language_the_video_lacks_shows_the_first_of_the_cycle(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose Spanish, which the video has no track of, with English then Romanian listed
    * verify English, the cycle's first, is shown
    """
    give_subtitles(libvlc)
    quick_engine.set_subtitle_choice(SubtitleChoice(True, "Spanish"))

    open_file(quick_engine)

    qtbot.waitUntil(lambda: spu_calls(libvlc) == [4], timeout=2000)


def test_a_choice_with_no_track_of_the_list_shows_none(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose subtitles on, for a video whose only track is one the list leaves out
    * verify libvlc is told to show none, since the track it chose is not one the reader asked for
    """
    give_subtitles(libvlc, [(-1, b"Disable"), (3, b"Track 3 - [French]")], shown=3)
    quick_engine.set_subtitle_choice(SubtitleChoice())

    open_file(quick_engine)

    qtbot.waitUntil(lambda: spu_calls(libvlc) == [-1], timeout=2000)


def test_a_key_pressed_before_the_tracks_are_listed_settles_the_matter(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose Romanian and open a file, then press the next-track key before libvlc has settled
    * verify the key's track is shown and the choice that was waiting is never applied
    """
    give_subtitles(libvlc)
    quick_engine.set_subtitle_choice(SubtitleChoice(True, "Romanian"))
    open_file(quick_engine)

    quick_engine.next_subtitle()
    qtbot.wait(100)

    assert spu_calls(libvlc) == [4]


def test_a_video_that_lists_no_tracks_is_given_up_on(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    """**Test steps:**

    * limit the reads to three, and open a file for which libvlc lists nothing
    * verify libvlc is read from three times, and no more
    """
    monkeypatch.setattr(vlc_media_player, "SUBTITLE_POLL_LIMIT", 3)
    libvlc.player.video_get_spu_description.return_value = []

    open_file(quick_engine)

    qtbot.waitUntil(lambda: libvlc.player.video_get_spu_description.call_count == 3, timeout=2000)
    qtbot.wait(50)
    assert libvlc.player.video_get_spu_description.call_count == 3


def test_letting_the_file_go_stops_the_wait_for_the_tracks(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose Romanian and open a file, then let it go at once
    * verify the choice is never applied
    """
    give_subtitles(libvlc)
    quick_engine.set_subtitle_choice(SubtitleChoice(True, "Romanian"))
    open_file(quick_engine)

    quick_engine.setSource(QUrl())
    qtbot.wait(100)

    libvlc.player.video_set_spu.assert_not_called()


def test_a_change_while_paused_seeks_to_where_it_is_and_hands_on_the_frame_that_shows_it(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """libvlc draws no subtitle on a paused picture until the position is sought again (measured); the seek is to the
    same position, and its frame is the picture the player shows.

    **Test steps:**

    * pause a playing video at 5.4 seconds, with tracks
    * ask for the next one
    * verify the position was set to where it is, and the first frame after it is handed on once, the next not
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)
    libvlc.player.get_time.return_value = 5400
    libvlc.fire(EventType.MediaPlayerPaused)
    qtbot.waitUntil(lambda: engine.playbackState() == QMediaPlayer.PlaybackState.PausedState)
    refreshed: list[QImage] = []
    engine.still_refreshed.connect(refreshed.append)

    engine.next_subtitle()

    libvlc.player.set_time.assert_called_once_with(5400)
    with qtbot.waitSignal(engine.still_refreshed, timeout=2000):
        libvlc.feed_frame(0x20)
    first = engine.grab_still()
    libvlc.feed_frame(0x30)
    qtbot.waitUntil(lambda: engine.grab_still() is not first)
    assert len(refreshed) == 1


def test_a_change_while_playing_seeks_nowhere_and_hands_nothing_on(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play a video with tracks and ask for the next one
    * feed a frame
    * verify nothing was sought and no refreshed frame was handed on
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)
    libvlc.fire(EventType.MediaPlayerPlaying)
    qtbot.waitUntil(lambda: engine.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
    refreshed: list[QImage] = []
    engine.still_refreshed.connect(refreshed.append)

    engine.next_subtitle()
    libvlc.feed_frame(0x20)
    qtbot.waitUntil(lambda: engine.grab_still() is not None)

    libvlc.player.set_time.assert_not_called()
    assert not refreshed


# endregion


def menus(engine: VlcMediaPlayer) -> list[tuple[list[str], int, int]]:
    """Listen to what the engine says its subtitle menu offers, which entry is on and how many the keys visit.

    :param engine: the engine.
    :returns: the list the entries, the position and the count are appended to.
    """
    said: list[tuple[list[str], int, int]] = []
    engine.subtitle_menu_changed.connect(lambda labels, index, visited: said.append((labels, index, visited)))
    return said


MENU: Final = ["Subs: off", "Subs: English", "Subs: Romanian", "Subs: Unknown", "Subs: French"]
"""What the menu offers for DESCRIBED with English then Romanian listed: the two the keys visit, then the others."""


def test_a_key_says_which_subtitle_is_on(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * list English then Romanian, only selected, and press next three times, then toggle twice
    * verify each key announced the same menu, with two entries the keys visit, and the entry that is on: English,
      Romanian, none; then the first toggle, from the none the cycle reached, English, and the second none
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)
    said = menus(engine)

    for _ in range(3):
        engine.next_subtitle()
    engine.toggle_subtitles()
    engine.toggle_subtitles()

    assert said == [(MENU, index, 2) for index in (1, 2, 0, 1, 0)]


def test_picking_an_entry_of_the_menu_shows_it_as_its_key_would_even_one_the_keys_skip(
    engine: VlcMediaPlayer, libvlc: FakeLibvlc
) -> None:
    """**Test steps:**

    * announce the menu with a key, then pick Romanian, none, French (which the keys skip), and entries outside it
    * verify libvlc was given English, Romanian, none and French, the choices say so, and the others did nothing
    * press next and verify the keys carry on from the start of the cycle, English
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)
    choices = chosen(engine)
    engine.next_subtitle()

    for index in (2, 0, 4, 5, -1):
        engine.select_subtitle(index)
    engine.next_subtitle()

    assert spu_calls(libvlc) == [4, 2, -1, 3, 4]
    assert choices == [
        SubtitleChoice(True, "English"),
        SubtitleChoice(True, "Romanian"),
        SubtitleChoice(shown=False),
        SubtitleChoice(True, "French"),
        SubtitleChoice(True, "English"),
    ]


def test_a_menu_that_was_never_announced_picks_nothing(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * pick an entry before any menu was announced
    * verify libvlc was not asked to show a track
    """
    give_subtitles(libvlc)

    engine.select_subtitle(1)

    libvlc.player.video_set_spu.assert_not_called()


def test_a_video_with_no_subtitle_has_no_menu(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * press a key for a video that lists no subtitle
    * verify nothing was announced
    """
    libvlc.player.video_get_spu_description.return_value = []
    said = menus(engine)

    engine.next_subtitle()

    assert not said


def test_the_applied_choice_is_announced_and_a_new_source_empties_the_menu(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose Romanian and open a file: verify the menu is emptied as it opens, then offered with Romanian on once
      applied
    * let the file go and verify the menu is emptied again
    """
    give_subtitles(libvlc, shown=1)
    quick_engine.set_subtitle_choice(SubtitleChoice(True, "Romanian"))
    said = menus(quick_engine)

    open_file(quick_engine)
    qtbot.waitUntil(lambda: said == [([], 0, 0), (MENU, 2, 2)], timeout=2000)

    quick_engine.setSource(QUrl())

    assert said[-1] == ([], 0, 0)


def test_a_video_whose_tracks_the_list_leaves_out_still_offers_them_in_the_menu(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot
) -> None:
    """**Test steps:**

    * choose subtitles on for a video whose only track the list leaves out
    * verify the menu offers none, which is on, and that track, with no entry the keys visit
    """
    give_subtitles(libvlc, [(-1, b"Disable"), (3, b"Track 3 - [French]")], shown=3)
    quick_engine.set_subtitle_choice(SubtitleChoice())
    said = menus(quick_engine)

    open_file(quick_engine)

    qtbot.waitUntil(lambda: (["Subs: off", "Subs: French"], 0, 0) in said, timeout=2000)


def test_stopping_empties_the_menu(engine: VlcMediaPlayer, libvlc: FakeLibvlc) -> None:
    """**Test steps:**

    * show a track, then stop
    * verify the last thing announced is an empty menu
    """
    engine.set_subtitle_preferences(ENGLISH_ROMANIAN)
    give_subtitles(libvlc)
    said = menus(engine)
    engine.next_subtitle()

    engine.stop()

    assert said == [(MENU, 1, 2), ([], 0, 0)]


def test_a_video_that_lists_no_tracks_says_so_when_given_up_on(
    quick_engine: VlcMediaPlayer, libvlc: FakeLibvlc, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    """**Test steps:**

    * limit the reads to three, and open a file for which libvlc lists nothing
    * verify the menu is emptied as the file opens, and then offers only the entry that says there are none
    """
    monkeypatch.setattr(vlc_media_player, "SUBTITLE_POLL_LIMIT", 3)
    libvlc.player.video_get_spu_description.return_value = []
    said = menus(quick_engine)

    open_file(quick_engine)

    qtbot.waitUntil(lambda: said == [([], 0, 0), (["Subs: none"], 0, 0)], timeout=2000)
