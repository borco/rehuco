"""A video's note read as lines, and the bookmark a line may carry ([[field-schema#video-notes]], #572).

Qt-free: the agent's video tree lists a note's lines under its video, and the notes panel's link dispatch (#573) reads
the same ``rehuco-video:`` links.
"""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, unquote

VIDEO_LINK_SCHEME: Final = "rehuco-video:"
"""What a link to a video of the tutorial starts with; ``#t=<seconds>`` after the key seeks."""

LINK_PATTERN: Final = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
"""A markdown link: its label, and its target."""

LEAD_PATTERN: Final = re.compile(r"^(?:#{1,6}(?:\s+|$)|>\s*|[-*+](?:\s+|$)|\d+[.)](?:\s+|$))*(?:\[[ xX]\](?:\s+|$))?")
"""What a line starts with that is markup rather than text: heading marks, a quote, a list marker, a task box."""

FENCE_PATTERN: Final = re.compile(r"^\s*(?:```|~~~)")
"""A code fence's line."""


@dataclass(frozen=True)
class NoteLine:
    """One line of a note.

    :param text: the line as a reader sees it: no list marker or heading marks, a link reduced to its label.
    :param key: the content key of the video the line's first ``rehuco-video:`` link names, else ``None``.
    :param seconds: the time that link seeks to, else ``None`` -- also when it has no valid ``#t``.
    """

    text: str
    key: str | None = None
    seconds: float | None = None


def note_lines(text: str) -> list[NoteLine]:
    """Split a note into its lines.

    :param text: the note's markdown.
    :returns: one entry per line that has text left once its markup is removed; fence lines are skipped.
    """
    lines = []
    for raw in text.splitlines():
        if FENCE_PATTERN.match(raw):
            continue
        stripped = LEAD_PATTERN.sub("", raw.strip(), count=1)
        shown = LINK_PATTERN.sub(lambda found: found.group(1), stripped).strip()
        if not shown:
            continue
        key, seconds = video_link(stripped)
        lines.append(NoteLine(shown, key, seconds))
    return lines


def insert_bookmark(text: str, line: str, seconds: float) -> tuple[str, int]:
    """Put a bookmark line beside the bookmarks nearest it in time, whatever order a note's lines are in.

    A note is the user's to edit, and its bookmarks may be in any order, so the ones already there are anchors rather
    than a sorted list: the line goes after the latest bookmark at or before its time -- and after the lines that follow
    that bookmark up to the next one, which belong to it -- else just before the earliest bookmark after it, else at the
    end. No other line moves.

    :param text: the note.
    :param line: the bookmark line, without its newline.
    :param seconds: the time it seeks to.
    :returns: the note with the line in it, and where the line ends in it, as a character offset.
    """
    lines = text.split("\n")
    times = [video_link(raw)[1] for raw in lines]
    marked = [(at, index) for index, at in enumerate(times) if at is not None]
    earlier = [(at, index) for at, index in marked if at <= seconds]
    later = [(at, index) for at, index in marked if at > seconds]
    position: int | None = None
    if earlier:
        _, anchor = max(earlier)
        position = next((index for index in range(anchor + 1, len(lines)) if times[index] is not None), None)
    elif later:
        _, position = min(later)
    if position is None:
        lead = "" if not text or text.endswith("\n") else "\n"
        joined = f"{text}{lead}{line}"
        return joined, len(joined)
    lines.insert(position, line)
    return "\n".join(lines), len("\n".join(lines[: position + 1]))


def video_link(markdown: str) -> tuple[str | None, float | None]:
    """The first link of a text that names a video.

    :param markdown: the text.
    :returns: the video's content key and the time to seek to, each ``None`` when the text has no such link or the
        link has no valid ``#t``.
    """
    for found in LINK_PATTERN.finditer(markdown):
        parsed = parse_video_href(found.group(2))
        if parsed is not None:
            return parsed
    return None, None


def parse_video_href(href: str) -> tuple[str, float | None] | None:
    """The video a link's target names.

    :param href: a link's target, such as ``rehuco-video:01%20Basics/03%20Brushes.mp4#t=754``.
    :returns: the video's content key and the time to seek to -- ``None`` when the target has no valid ``#t`` -- or
        ``None`` when the target is not a ``rehuco-video:`` link or names no key.
    """
    if not href.startswith(VIDEO_LINK_SCHEME):
        return None
    key, _, fragment = href[len(VIDEO_LINK_SCHEME) :].partition("#")
    key = unquote(key)
    if not key:
        return None
    return key, seek_seconds(fragment)


def video_href(key: str, seconds: float | None = None) -> str:
    """The target of a link to a video.

    :param key: the video's content key.
    :param seconds: the time the link seeks to, rounded down; none for a link that only loads the video.
    :returns: the link's target, which :func:`parse_video_href` reads back.
    """
    href = f"{VIDEO_LINK_SCHEME}{quote(key)}"
    if seconds is None:
        return href
    return f"{href}#t={int(seconds)}"


def seek_seconds(fragment: str) -> float | None:
    """The seconds a link's fragment seeks to.

    :param fragment: what follows the ``#``, such as ``t=754``.
    :returns: the time, or ``None`` for anything but a finite, non-negative ``t=<number>``.
    """
    name, _, value = fragment.partition("=")
    if name != "t":
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds < float("inf") else None
