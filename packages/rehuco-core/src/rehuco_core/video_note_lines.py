"""A video's note read as lines, and the bookmark a line may carry ([[field-schema#video-notes]], #572).

Qt-free: the agent's video tree lists a note's lines under its video, and the notes panel's link dispatch (#573) reads
the same ``rehuco-video:`` links.
"""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote

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


def video_link(markdown: str) -> tuple[str | None, float | None]:
    """The first link of a text that names a video.

    :param markdown: the text.
    :returns: the video's content key and the time to seek to, each ``None`` when the text has no such link or the
        link has no valid ``#t``.
    """
    for found in LINK_PATTERN.finditer(markdown):
        target = found.group(2)
        if not target.startswith(VIDEO_LINK_SCHEME):
            continue
        key, _, fragment = target[len(VIDEO_LINK_SCHEME) :].partition("#")
        key = unquote(key)
        if not key:
            continue
        return key, seek_seconds(fragment)
    return None, None


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
