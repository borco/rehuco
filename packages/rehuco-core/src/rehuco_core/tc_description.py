"""Rewrites a description's embedded image references for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Given a `rehuco_core.tc_screenshots.scan_tc_screenshots` result, rewrites every Markdown
``![alt](url "title")`` reference in a description that names one of the scan's recognized old
filenames to that slot's new ``slugNN`` name -- so a description written against the legacy `.tc`
still points at the right screenshot once the conversion actually renames the files on disk. A pure
text transform: no filesystem access, no Qt dependency, matching every other core-side module here.
"""

import re
from collections.abc import Sequence
from typing import Final

from .tc_screenshots import ScreenshotRename


def rewrite_description_images(description: str, renames: Sequence[ScreenshotRename]) -> str:
    """Rewrite ``description``'s embedded image references per ``renames``.

    :param description: the document's current Markdown description.
    :param renames: a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` result.
    :returns: the description with every recognized reference rewritten; anything unrecognized (an
        already-current name, an external URL, a typo) is left untouched.
    """
    return TcDescriptionRewriter(renames).rewrite(description)


class TcDescriptionRewriter:  # pylint: disable=too-few-public-methods
    """Rewrites a description's embedded image references per one screenshot scan ([[acquisition-tooling#tc-to-rehu]]).

    Both a slot's winning and losing old filenames rewrite to the same new name -- the description
    may have been written against either variant, and both represent the same photo
    ([[field-schema#sources]]). A reference naming just the filename's stem, with no extension (a
    real pattern confirmed against an actual `.tc` description this session, e.g. ``![](cover)``),
    matches the same way a full filename would. Matching is case-insensitive (legacy filenames were
    never guaranteed consistent casing) and ignores any leading path a reference might carry (e.g.
    ``images/cover.jpg``) -- the rewritten name is always bare, since converted screenshots live
    directly alongside the ``.rehu``, not in a subdirectory.

    :param renames: a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` result.
    """

    __IMAGE_REFERENCE_RE: Final = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)')
    """A Markdown image reference: ``![alt](url "optional title")``."""

    def __init__(self, renames: Sequence[ScreenshotRename]) -> None:
        self.__lookup: Final = self.__build_lookup(renames)

    def rewrite(self, description: str) -> str:
        """Rewrite every recognized image reference in ``description``.

        :param description: the Markdown text to rewrite.
        :returns: the rewritten text.
        """
        return self.__IMAGE_REFERENCE_RE.sub(self.__replacement, description)

    def __replacement(self, match: re.Match[str]) -> str:
        """Build one reference's replacement text, or its original text if unrecognized.

        :param match: one ``__IMAGE_REFERENCE_RE`` match.
        :returns: the replacement (or original, unchanged) reference text.
        """
        alt, url, title = match.group(1), match.group(2), match.group(3)
        new_name = self.__lookup.get(self.__bare_name(url).lower())
        return match.group(0) if new_name is None else f"![{alt}]({new_name}{title})"

    @staticmethod
    def __bare_name(reference: str) -> str:
        """The filename a reference's URL portion names, dropping any leading path.

        :param reference: the raw URL text inside ``(...)``.
        :returns: its final path segment.
        """
        return reference.rsplit("/", 1)[-1]

    @staticmethod
    def __build_lookup(renames: Sequence[ScreenshotRename]) -> dict[str, str]:
        """Map every recognized old filename -- and its extension-less stem -- to its new name.

        :param renames: a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` result.
        :returns: ``{lowercased old name or stem: new name}``.
        """
        table: dict[str, str] = {}
        for rename in renames:
            for old_name in rename.recognized_filenames:
                table[old_name.lower()] = rename.new_name
                stem = old_name.rsplit(".", 1)[0] if "." in old_name else old_name
                table[stem.lower()] = rename.new_name
        return table
