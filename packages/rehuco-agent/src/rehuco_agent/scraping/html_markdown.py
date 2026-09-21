"""Converts a browser selection's `text/html` into Markdown for the description editor drop
([[acquisition-tooling#drag-drop-aids]], #264): `markdownify` followed by tc4's cleanup pass over
what a browser's clipboard actually hands over. Pure function over strings, no Qt involved.
"""

import re
from typing import Final

from markdownify import ATX, MarkdownConverter

UNICODE_SPACES: Final = re.compile(r"[ \t]*[^\S \t\n]+[ \t]*")
"""A run of non-ASCII spaces -- the non-breaking spaces a browser selection is full of -- together
with any ASCII spaces touching it, collapsed to a single regular space. Runs of plain ASCII spaces
are left alone on purpose: they are the indentation nested lists and code blocks depend on."""

TRAILING_SPACE: Final = re.compile(r" +\n")
"""Any trailing space(s) left before a line break, normalized to exactly two -- Markdown's hard-break
marker."""

BLANK_LINE_PADDING: Final = re.compile(r" *\n *\n")
"""Spaces sitting on either side of a blank line, removed before the run itself is collapsed."""

BLANK_LINE_RUN: Final = re.compile(r"\n\s*\n")
"""A run of two or more blank lines, collapsed to exactly one."""


class HtmlMarkdown:  # pylint: disable=too-few-public-methods
    """Converts an HTML fragment to Markdown, cleaning up what a real browser selection carries
    ([[acquisition-tooling#drag-drop-aids]]): ATX headings, `*` bullets, non-breaking spaces folded
    to regular ones, hard breaks kept at exactly two trailing spaces, and runs of blank lines
    collapsed to one.
    """

    @staticmethod
    def convert(html: str) -> str:
        """Convert an HTML fragment to cleaned-up Markdown.

        :param html: the fragment, e.g. a browser drop's `text/html`.
        :returns: the converted Markdown.
        """
        converter = MarkdownConverter(heading_style=ATX, bullets="*")
        text = converter.convert(html)
        text = UNICODE_SPACES.sub(" ", text)
        text = TRAILING_SPACE.sub("  \n", text)
        text = BLANK_LINE_PADDING.sub("\n\n", text)
        text = BLANK_LINE_RUN.sub("\n\n", text.strip())
        return text
