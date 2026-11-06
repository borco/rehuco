"""Tests for which subtitle tracks a player visits and which one a remembered choice means (#618)."""

from pytest import mark, param
from rehuco_core import (
    LANGUAGES,
    UNKNOWN_ENTRY,
    SubtitleChoice,
    SubtitlePreferences,
    SubtitleTrack,
    remembered_track,
    subtitle_cycle,
    subtitle_entries,
    subtitle_index,
    subtitle_labels,
    track_name,
)

ENGLISH = SubtitleTrack(1, "English")
ROMANIAN = SubtitleTrack(2, "Romanian")
FRENCH = SubtitleTrack(3, "French")
BARE = SubtitleTrack(4, None)
SECOND_ENGLISH = SubtitleTrack(5, "English")
SECOND_BARE = SubtitleTrack(6, None)

TRACKS = [BARE, ROMANIAN, FRENCH, ENGLISH, SECOND_ENGLISH, SECOND_BARE]
"""libvlc's order: a bare file first, then the named ones."""


@mark.parametrize(
    ("description", "language"),
    [
        param("Track 2 - [Romanian]", "Romanian", id="a language"),
        param("Track 1", None, id="none"),
        param("Track 3 - [Chinese; Mandarin]", "Chinese; Mandarin", id="a name with punctuation"),
        param("Track 4 - [ English ]", "English", id="spaces"),
        param("[English] Track 5", None, id="a bracket that is not libvlc's"),
    ],
)
def test_a_tracks_language_is_read_off_libvlcs_description(description: str, language: str | None) -> None:
    """**Test steps:**

    * parse a description
    * verify the language, or none when the description names none
    """
    assert SubtitleTrack.parse(7, description) == SubtitleTrack(7, language)


def test_only_selected_languages_visits_every_track_of_each_in_the_lists_order() -> None:
    """**Test steps:**

    * list Romanian then English, only selected, over tracks with two English ones, French and bare ones
    * verify Romanian comes first, then both English tracks in libvlc's order, and nothing else
    """
    preferences = SubtitlePreferences(("Romanian", "English"), show_all=False)

    assert subtitle_cycle(TRACKS, preferences) == [ROMANIAN, ENGLISH, SECOND_ENGLISH]


def test_unknown_stands_for_the_tracks_with_no_language_where_the_list_puts_it() -> None:
    """**Test steps:**

    * list English, Unknown, Romanian, only selected
    * verify the English tracks, then both bare ones, then Romanian; French is never visited
    """
    preferences = SubtitlePreferences(("English", UNKNOWN_ENTRY, "Romanian"), show_all=False)

    assert subtitle_cycle(TRACKS, preferences) == [ENGLISH, SECOND_ENGLISH, BARE, SECOND_BARE, ROMANIAN]


def test_unknown_may_come_before_the_known_languages() -> None:
    """**Test steps:**

    * list Unknown first, only selected
    * verify the bare tracks come before English
    """
    preferences = SubtitlePreferences((UNKNOWN_ENTRY, "English"), show_all=False)

    assert subtitle_cycle(TRACKS, preferences) == [BARE, SECOND_BARE, ENGLISH, SECOND_ENGLISH]


def test_a_language_not_listed_is_not_unknown() -> None:
    """**Test steps:**

    * list only Unknown, only selected
    * verify French and the rest are not in the cycle, only the bare tracks
    """
    assert subtitle_cycle(TRACKS, SubtitlePreferences((UNKNOWN_ENTRY,), show_all=False)) == [BARE, SECOND_BARE]


def test_show_all_adds_what_the_list_leaves_out_unknown_first_then_the_other_languages() -> None:
    """**Test steps:**

    * list Romanian, show all, over the tracks
    * verify Romanian, then the bare tracks, then the other known languages in libvlc's order
    """
    preferences = SubtitlePreferences(("Romanian",), show_all=True)

    assert subtitle_cycle(TRACKS, preferences) == [ROMANIAN, BARE, SECOND_BARE, FRENCH, ENGLISH, SECOND_ENGLISH]


def test_show_all_keeps_unknown_where_the_list_put_it() -> None:
    """**Test steps:**

    * list Unknown then Romanian, show all
    * verify the bare tracks, Romanian, then what the list does not name
    """
    preferences = SubtitlePreferences((UNKNOWN_ENTRY, "Romanian"), show_all=True)

    assert subtitle_cycle(TRACKS, preferences) == [BARE, SECOND_BARE, ROMANIAN, FRENCH, ENGLISH, SECOND_ENGLISH]


def test_languages_are_compared_by_name_without_regard_to_case_or_space() -> None:
    """**Test steps:**

    * list ``english`` in lower case with a space, only selected
    * verify the English tracks are found
    """
    assert subtitle_cycle(TRACKS, SubtitlePreferences((" english ",), show_all=False)) == [ENGLISH, SECOND_ENGLISH]


def test_a_video_with_no_track_of_the_list_has_an_empty_cycle() -> None:
    """**Test steps:**

    * list Romanian, only selected, over a video with only English
    * verify the cycle is empty, and so is the track a choice means
    """
    cycle = subtitle_cycle([ENGLISH], SubtitlePreferences(("Romanian",), show_all=False))

    assert not cycle
    assert remembered_track(cycle, SubtitleChoice()) is None


@mark.parametrize(
    ("choice", "expected"),
    [
        param(SubtitleChoice(), ROMANIAN, id="none remembered: the first of the cycle"),
        param(SubtitleChoice(language="English"), ENGLISH, id="a language"),
        param(SubtitleChoice(language="english"), ENGLISH, id="by name, not by case"),
        param(SubtitleChoice(unknown=True), BARE, id="unknown"),
        param(SubtitleChoice(language="Spanish"), ROMANIAN, id="a language this video lacks: the first"),
        param(SubtitleChoice(unknown=True, shown=False), BARE, id="off, with the track it returns to"),
    ],
)
def test_a_choice_means_the_first_track_of_its_language_else_the_first_of_the_cycle(
    choice: SubtitleChoice, expected: SubtitleTrack
) -> None:
    """**Test steps:**

    * take a cycle of Romanian, English and the bare tracks
    * verify the track each choice means
    """
    cycle = subtitle_cycle(TRACKS, SubtitlePreferences(("Romanian", "English", UNKNOWN_ENTRY), show_all=False))

    assert remembered_track(cycle, choice) == expected


def test_a_choice_of_a_track_remembers_its_language_or_that_it_has_none() -> None:
    """**Test steps:**

    * make choices of an English track and of a bare one, on and off
    * verify the language, the unknown flag and the shown flag
    """
    assert SubtitleChoice.of_track(ENGLISH) == SubtitleChoice(True, "English", False)
    assert SubtitleChoice.of_track(BARE, shown=False) == SubtitleChoice(False, None, True)


@mark.parametrize("choice", [SubtitleChoice(), SubtitleChoice(False, "English"), SubtitleChoice(True, None, True)])
def test_a_choice_round_trips_through_its_state(choice: SubtitleChoice) -> None:
    """**Test steps:**

    * write a choice as state and read it back
    * verify it is the same
    """
    assert SubtitleChoice.from_state(choice.to_state()) == choice


@mark.parametrize(
    "state",
    [
        param(None, id="nothing"),
        param([1], id="not a mapping"),
        param({"shown": 1, "language": None, "unknown": False}, id="shown not a bool"),
        param({"shown": True, "language": None, "unknown": 0}, id="unknown not a bool"),
        param({"shown": True, "language": 5, "unknown": False}, id="language not a string"),
        param({}, id="empty"),
    ],
)
def test_a_state_that_is_not_a_choice_is_read_as_none(state: object) -> None:
    """**Test steps:**

    * read states that are not what a choice writes
    * verify none comes back, so the settings' default applies
    """
    assert SubtitleChoice.from_state(state) is None


def test_the_unknown_entry_is_not_a_language() -> None:
    """**Test steps:**

    * look for the unknown entry among the languages offered
    * verify it is not there, and that English and Romanian are, with no duplicate
    """
    assert UNKNOWN_ENTRY not in LANGUAGES
    assert {"English", "Romanian", "French"} <= set(LANGUAGES)
    assert len(set(LANGUAGES)) == len(LANGUAGES)


def test_the_menu_offers_the_tracks_the_keys_visit_then_the_others_in_libvlcs_order() -> None:
    """**Test steps:**

    * take a cycle of Romanian and the English tracks over the video's six tracks
    * verify the entries are those, then the bare tracks and French in libvlc's order, each once
    """
    cycle = subtitle_cycle(TRACKS, SubtitlePreferences(("Romanian", "English"), show_all=False))

    assert subtitle_entries(TRACKS, cycle) == [ROMANIAN, ENGLISH, SECOND_ENGLISH, BARE, FRENCH, SECOND_BARE]


def test_a_video_whose_tracks_the_keys_all_skip_still_has_a_menu() -> None:
    """**Test steps:**

    * list Romanian only, over a video with English alone
    * verify the cycle is empty and the menu still offers the English track
    """
    tracks = [ENGLISH]
    cycle = subtitle_cycle(tracks, SubtitlePreferences(("Romanian",), show_all=False))

    assert not cycle
    assert subtitle_entries(tracks, cycle) == [ENGLISH]


@mark.parametrize(
    ("entries", "labels"),
    [
        param([ENGLISH, ROMANIAN], ["Subs: off", "Subs: English", "Subs: Romanian"], id="languages"),
        param([BARE], ["Subs: off", "Subs: Unknown"], id="no language"),
        param(
            [ENGLISH, SECOND_ENGLISH, ROMANIAN],
            ["Subs: off", "Subs: English 1/2", "Subs: English 2/2", "Subs: Romanian"],
            id="the place of a name that is shared",
        ),
        param(
            [BARE, SECOND_BARE, ENGLISH],
            ["Subs: off", "Subs: Unknown 1/2", "Subs: Unknown 2/2", "Subs: English"],
            id="unknown is shared too",
        ),
        param([], [], id="no subtitle track: no menu"),
    ],
)
def test_the_menu_offers_none_and_a_track_each(entries: list[SubtitleTrack], labels: list[str]) -> None:
    """**Test steps:**

    * make the labels of the menu for some entries
    * verify none comes first, then a track each with its place when its name is shared, and nothing at all when
      the video has no subtitle track
    """
    assert subtitle_labels(entries) == labels


@mark.parametrize(
    ("current", "index"),
    [
        param(None, 0, id="none shown"),
        param(ENGLISH, 1, id="the first track"),
        param(FRENCH, 3, id="a track the keys skip"),
        param(BARE, 0, id="a track the video does not have counts as none"),
    ],
)
def test_the_menu_entry_that_is_on_is_the_track_shown(current: SubtitleTrack | None, index: int) -> None:
    """**Test steps:**

    * find the entry of a menu of English, Romanian and French for the track shown
    * verify its position, with none, and a track that is not there, at the first
    """
    assert subtitle_index([ENGLISH, ROMANIAN, FRENCH], current) == index


def test_a_track_is_named_by_its_language_or_unknown() -> None:
    """**Test steps:**

    * name a track with a language and one without
    * verify the language, and Unknown
    """
    assert track_name(ENGLISH) == "English"
    assert track_name(BARE) == UNKNOWN_ENTRY
