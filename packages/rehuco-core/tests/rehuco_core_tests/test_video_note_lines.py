"""Tests for a video's note read as lines and bookmarks ([[field-schema#video-notes]], #572)."""

from typing import Final

from pytest import mark
from rehuco_core import NoteLine, note_lines, seek_seconds, video_link

BOOKMARK: Final = "- [12:34](rehuco-video:01%20Basics/03%20Brushes.mp4#t=754) the smudge trick"


def test_a_bookmark_line_reads_as_its_label_and_text_and_carries_its_video_and_time() -> None:
    """The line the notes panel appends is the bookmark.

    **Test steps:**

    * read one bookmark line
    * verify the list marker and the link's target are gone from the text
    * verify the key is URL-decoded and the time parsed
    """
    assert note_lines(BOOKMARK) == [NoteLine("12:34 the smudge trick", "01 Basics/03 Brushes.mp4", 754.0)]


def test_a_bookmark_with_no_text_reads_as_its_time() -> None:
    """**Test steps:**

    * read a bookmark line that is only the link
    * verify the text is the label
    """
    assert note_lines("- [1:05](rehuco-video:a.mp4#t=65)") == [NoteLine("1:05", "a.mp4", 65.0)]


@mark.parametrize(
    ("line", "text"),
    [
        ("plain words", "plain words"),
        ("- a dash item", "a dash item"),
        ("* a star item", "a star item"),
        ("12. a numbered item", "a numbered item"),
        ("## A heading", "A heading"),
        ("> a quote", "a quote"),
        ("- [ ] a task", "a task"),
        ("- [x] a done task", "a done task"),
        ("see [the docs](https://example.com/x) now", "see the docs now"),
    ],
)
def test_a_line_loses_its_markup(line: str, text: str) -> None:
    """**Test steps:**

    * read a line wearing one kind of markup
    * verify the text without it, and no video
    """
    assert note_lines(line) == [NoteLine(text)]


def test_blank_lines_markers_alone_and_fences_are_skipped() -> None:
    """**Test steps:**

    * read a note with blank lines, a bare list marker and a fence line
    * verify only the lines with text remain, in order
    """
    note = "first\n\n-\n   \n```python\nsecond\n~~~"

    assert [line.text for line in note_lines(note)] == ["first", "second"]


def test_a_note_with_nothing_in_it_has_no_lines() -> None:
    """**Test steps:**

    * read an empty note
    * verify no lines
    """
    assert not note_lines("")


@mark.parametrize(
    ("markdown", "expected"),
    [
        ("[x](rehuco-video:a.mp4#t=5)", ("a.mp4", 5.0)),
        ("[x](rehuco-video:a.mp4#t=5.5)", ("a.mp4", 5.5)),
        ("[x](rehuco-video:a.mp4)", ("a.mp4", None)),
        ("[x](rehuco-video:a.mp4#t=soon)", ("a.mp4", None)),
        ("[x](rehuco-video:a.mp4#t=-3)", ("a.mp4", None)),
        ("[x](rehuco-video:a.mp4#t=inf)", ("a.mp4", None)),
        ("[x](rehuco-video:a.mp4#start=5)", ("a.mp4", None)),
        ("[x](rehuco-video:#t=5)", (None, None)),
        ("[x](https://example.com#t=5)", (None, None)),
        ("no link at all", (None, None)),
        ("[a](https://example.com) [b](rehuco-video:b.mp4#t=2)", ("b.mp4", 2.0)),
        ("[a](rehuco-video:a.mp4#t=1) [b](rehuco-video:b.mp4#t=2)", ("a.mp4", 1.0)),
    ],
)
def test_video_link_reads_the_first_link_that_names_a_video(
    markdown: str, expected: tuple[str | None, float | None]
) -> None:
    """**Test steps:**

    * read a text holding one shape of link
    * verify the key and the time, each ``None`` where the link does not give one
    """
    assert video_link(markdown) == expected


@mark.parametrize(("fragment", "expected"), [("t=12", 12.0), ("t=", None), ("", None), ("t", None)])
def test_seek_seconds_accepts_only_a_time(fragment: str, expected: float | None) -> None:
    """**Test steps:**

    * read a fragment
    * verify the time only for ``t=<number>``
    """
    assert seek_seconds(fragment) == expected
