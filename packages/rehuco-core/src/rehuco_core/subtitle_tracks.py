"""Which subtitle tracks a video's player visits, in which order, and which one a remembered choice means
([[plugins#in-app-player]], #618).

Qt-free and libvlc-free: a track is an id and the language libvlc's description names, so the rules are testable
without a player. libvlc's description is ``Track 2 - [Romanian]``; a track whose file says nothing of its language is
``Track 1``, and its language is *unknown*.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

UNKNOWN_ENTRY: Final = "Unknown"
"""The entry of the user's language list that stands for the tracks with no language information. Not the name of a
language, so it never meets one in :data:`~rehuco_core.subtitle_languages.LANGUAGES`."""

LANGUAGE_PATTERN: Final = re.compile(r" - \[([^\]]+)\]$")
"""The language libvlc appends to a track's description."""

SHOWN_KEY: Final = "shown"
LANGUAGE_KEY: Final = "language"
UNKNOWN_KEY: Final = "unknown"


def language_key(language: str) -> str:
    """What two spellings of a language are compared by.

    :param language: a language name.
    :returns: the name without surrounding space, case-folded.
    """
    return language.strip().casefold()


@dataclass(frozen=True)
class SubtitleTrack:
    """One of a video's subtitle tracks.

    :param track_id: libvlc's id, which means something only within this video.
    :param language: the language libvlc names it for, or ``None`` when its file says none.
    """

    track_id: int
    language: str | None

    @classmethod
    def parse(cls, track_id: int, description: str) -> SubtitleTrack:
        """Read a track off libvlc's description of it.

        :param track_id: libvlc's id.
        :param description: the description, ``Track 2 - [Romanian]``.
        :returns: the track; its language is ``None`` when the description names none.
        """
        found = LANGUAGE_PATTERN.search(description)
        return cls(track_id, found.group(1).strip() if found is not None else None)


@dataclass(frozen=True)
class SubtitlePreferences:
    """Which languages the keys visit, and in what order -- the Videos page's list.

    :param entries: language names and :data:`UNKNOWN_ENTRY`, the most preferred first.
    :param show_all: whether a track the list does not name is visited too, after those it does.
    """

    entries: tuple[str, ...]
    show_all: bool


@dataclass(frozen=True)
class SubtitleChoice:
    """What was chosen for a rehu's videos: subtitles on or off, and the track they are, or were last, shown as.

    A track means a different id in each video, so it is kept as a language. When the subtitles are off, the track
    is the one turning them on again returns to; with none (``language`` ``None``, ``unknown`` false) it is the first
    the cycle has.

    :param shown: whether the subtitles are on.
    :param language: the language of the track, or ``None`` for none or an unknown one.
    :param unknown: whether the track is one with no language.
    """

    shown: bool = True
    language: str | None = None
    unknown: bool = False

    @classmethod
    def of_track(cls, track: SubtitleTrack, *, shown: bool = True) -> SubtitleChoice:
        """The choice that says a track is the one shown.

        :param track: the track.
        :param shown: whether the subtitles are on.
        :returns: the choice.
        """
        return cls(shown, track.language, track.language is None)

    def to_state(self) -> dict[str, Any]:
        """The choice as plain values, for a layout.

        :returns: a dict of a bool, a string or ``None``, and a bool.
        """
        return {SHOWN_KEY: self.shown, LANGUAGE_KEY: self.language, UNKNOWN_KEY: self.unknown}

    @classmethod
    def from_state(cls, state: object) -> SubtitleChoice | None:
        """Read what :meth:`to_state` wrote.

        :param state: the stored value.
        :returns: the choice, or ``None`` when the value is not one -- then the settings' default applies.
        """
        if not isinstance(state, dict):
            return None
        shown, language, unknown = state.get(SHOWN_KEY), state.get(LANGUAGE_KEY), state.get(UNKNOWN_KEY)
        if not isinstance(shown, bool) or not isinstance(unknown, bool):
            return None
        if language is not None and not isinstance(language, str):
            return None
        return cls(shown, language, unknown)


def subtitle_cycle(tracks: Sequence[SubtitleTrack], preferences: SubtitlePreferences) -> list[SubtitleTrack]:
    """The tracks the keys visit, in order, *none* not counted.

    Each entry of the list brings every track of its language -- two English tracks are both visited, in libvlc's
    order -- and :data:`UNKNOWN_ENTRY` every track with no language. With ``show_all``, what the list does not name
    follows: the unknown tracks when the list leaves them out, then the other languages, in libvlc's order.

    :param tracks: the video's subtitle tracks, in libvlc's order.
    :param preferences: the user's list.
    :returns: the tracks to visit.
    """
    entries = list(preferences.entries)
    if preferences.show_all and UNKNOWN_ENTRY not in entries:
        entries.append(UNKNOWN_ENTRY)
    cycle: list[SubtitleTrack] = []
    for entry in entries:
        for track in tracks:
            named = track.language is None if entry == UNKNOWN_ENTRY else is_language(track, entry)
            if named and track not in cycle:
                cycle.append(track)
    if preferences.show_all:
        cycle.extend(track for track in tracks if track not in cycle)
    return cycle


def remembered_track(cycle: Sequence[SubtitleTrack], choice: SubtitleChoice) -> SubtitleTrack | None:
    """The track a choice means in a video: the first of the cycle that is of its language, else the first.

    :param cycle: the tracks the keys visit (:func:`subtitle_cycle`).
    :param choice: the choice; whether it is on or off is not asked.
    :returns: the track, or ``None`` when the cycle is empty.
    """
    for track in cycle:
        if choice.unknown and track.language is None:
            return track
        if choice.language is not None and is_language(track, choice.language):
            return track
    return cycle[0] if cycle else None


def is_language(track: SubtitleTrack, language: str) -> bool:
    """Whether a track is of a language.

    :param track: the track.
    :param language: the language's name.
    :returns: whether they are the same language, by name.
    """
    return track.language is not None and language_key(track.language) == language_key(language)


def track_name(track: SubtitleTrack) -> str:
    """What a track is called to the reader: its language, or *Unknown* when its file names none.

    :param track: the track.
    :returns: the name.
    """
    return track.language if track.language is not None else UNKNOWN_ENTRY


def subtitle_entries(tracks: Sequence[SubtitleTrack], cycle: Sequence[SubtitleTrack]) -> list[SubtitleTrack]:
    """The tracks the subtitle menu offers: those the keys visit, in their order, then the rest of the video's, which
    the reader may still pick and the keys skip.

    :param tracks: the video's subtitle tracks, in libvlc's order.
    :param cycle: the tracks the keys visit (:func:`subtitle_cycle`).
    :returns: the tracks, the first ``len(cycle)`` of them those the keys visit.
    """
    return [*cycle, *(track for track in tracks if track not in cycle)]


def subtitle_labels(entries: Sequence[SubtitleTrack]) -> list[str]:
    """The entries of the menu that says which subtitle is on, and sets one: ``Subs: off``, then a track each --
    ``Subs: English`` -- with its place among those of its name -- ``Subs: English 2/3`` -- when the video has several.

    A silent stretch of a video shows no subtitle at all, so the reader has no other way to tell a track was set (#618).

    :param entries: the tracks the menu offers (:func:`subtitle_entries`).
    :returns: the entries, *none* first; empty when the video has no subtitle track at all.
    """
    if not entries:
        return []
    labels = ["Subs: off"]
    for track in entries:
        name = track_name(track)
        same = [other for other in entries if language_key(track_name(other)) == language_key(name)]
        labels.append(f"Subs: {name} {same.index(track) + 1}/{len(same)}" if len(same) > 1 else f"Subs: {name}")
    return labels


def subtitle_index(entries: Sequence[SubtitleTrack], current: SubtitleTrack | None) -> int:
    """Which entry of :func:`subtitle_labels` is on.

    :param entries: the tracks the menu offers.
    :param current: the track shown, or ``None`` for none.
    :returns: the entry's position: ``0`` for none, or for a track the video does not have.
    """
    return entries.index(current) + 1 if current is not None and current in entries else 0
