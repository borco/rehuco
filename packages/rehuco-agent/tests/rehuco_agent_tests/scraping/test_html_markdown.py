"""Tests for HtmlMarkdown: HTML-to-Markdown conversion for a browser drop (#264)."""

from pytest import mark, param
from rehuco_agent.scraping.html_markdown import HtmlMarkdown

# A saved real-world fragment (Udemy/ArtStation course-overview shape): nested wrapper divs, a
# heading, non-breaking spaces used for layout padding, a `<br>` hard break followed by a doubled
# one, and stray leading/trailing whitespace around a paragraph -- everything the cleanup pass
# exists for at once.
MESSY_FRAGMENT: str = (
    "<div><div>\n"
    "<h2>Course Overview</h2>\n"
    "<p>Welcome&nbsp;&nbsp;to the course.<br>\n"
    "Second line.<br><br>\n"
    "</p>\n"
    "<div><p>Nested paragraph with   several   spaces.</p></div>\n"
    "<ul><li>Item one</li><li>Item&nbsp;two</li></ul>\n"
    "<p>   Leading and trailing spaces.   </p>\n"
    "</div></div>\n"
)

MESSY_FRAGMENT_EXPECTED: str = (
    "## Course Overview\n"
    "\n"
    "Welcome to the course.  \n"
    "Second line.\n"
    "\n"
    "Nested paragraph with several spaces.\n"
    "\n"
    "* Item one\n"
    "* Item two\n"
    "\n"
    "Leading and trailing spaces."
)


@mark.parametrize(
    ("html", "markdown"),
    [
        param("<h1>Title</h1>", "# Title", id="heading"),
        param(
            "<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>",
            "* a\n  * a1\n  * a2\n* b",
            id="nested-list",
        ),
        param(
            "<pre><code>def f():\n    return 1\n</code></pre>",
            "```\ndef f():\n    return 1\n```",
            id="code-block-keeps-indentation",
        ),
        param('<a href="https://example.com">example</a>', "[example](https://example.com)", id="link"),
        param('<img src="pic.png" alt="a pic">', "![a pic](pic.png)", id="image"),
        param("<p><code>a + b</code></p>", "`a + b`", id="inline-code"),
        param("<p>Line one<br>Line two</p>", "Line one  \nLine two", id="br-hard-break"),
    ],
)
def test_convert_html_element(html: str, markdown: str) -> None:
    """Each HTML element markdownify supports converts to the expected Markdown (#264).

    **Test steps:**

    * convert the fragment
    * verify it matches the expected Markdown exactly
    """
    assert HtmlMarkdown.convert(html) == markdown


def test_convert_messy_real_world_fragment() -> None:
    """A messy, real-world-shaped fragment -- nested wrapper divs, non-breaking spaces used for
    padding, a `<br>` hard break next to a doubled one, and stray whitespace around a paragraph --
    converts to clean Markdown, whitespace cleanup pinned exactly (#264).

    **Test steps:**

    * convert :data:`MESSY_FRAGMENT`
    * verify it matches :data:`MESSY_FRAGMENT_EXPECTED` exactly
    """
    assert HtmlMarkdown.convert(MESSY_FRAGMENT) == MESSY_FRAGMENT_EXPECTED


def test_non_breaking_spaces_are_normalized_to_regular_spaces() -> None:
    """A run of non-breaking spaces -- what a browser selection is full of -- collapses to a single
    regular space, not left as-is (#264).

    **Test steps:**

    * convert a fragment with a run of ``&nbsp;`` entities between two words
    * verify the result holds a single regular space, not the non-breaking character
    """
    assert HtmlMarkdown.convert("<p>a&nbsp;&nbsp;&nbsp;b</p>") == "a b"


def test_a_non_breaking_space_before_a_hard_break_keeps_the_break() -> None:
    """A non-breaking space sitting right before a `<br>` folds into the break's two trailing
    spaces rather than leaving three, or a lone non-breaking one (#264).

    **Test steps:**

    * convert a paragraph with ``&nbsp;<br>`` in it
    * verify the line ends in exactly two regular spaces
    """
    assert HtmlMarkdown.convert("<p>a&nbsp;<br>b</p>") == "a  \nb"


def test_runs_of_blank_lines_are_collapsed_to_one() -> None:
    """Several consecutive blank lines -- e.g. from nested wrapper `<div>`s -- collapse to exactly
    one, not left piled up (#264).

    **Test steps:**

    * convert two paragraphs separated by extra blank `<div>`s
    * verify exactly one blank line separates them
    """
    html = "<div><p>First.</p></div><div></div><div></div><p>Second.</p>"

    assert HtmlMarkdown.convert(html) == "First.\n\nSecond."
