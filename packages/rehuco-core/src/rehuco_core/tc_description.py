"""Rewrites a description's embedded image references for `.tc` conversion ([[acquisition-tooling#tc-to-rehu]]).

Given a `rehuco_core.tc_screenshots.scan_tc_screenshots` result, rewrites every Markdown
``![alt](url "title")`` reference in a description that names a file the conversion renames to that
file's new ``slugNN`` name -- so a description written against the legacy `.tc` still points at the
right screenshot once the conversion actually renames the files on disk. A pure text transform: no
filesystem access, no Qt dependency, matching every other core-side module here.
"""

import re
from collections.abc import Sequence
from typing import Final

from .tc_screenshots import ScreenshotRename


def rewrite_description_images(description: str, renames: Sequence[ScreenshotRename]) -> str:
    """Rewrite ``description``'s embedded image references per ``renames``.

    :param description: the document's current Markdown description.
    :param renames: the renames a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` plan carries.
    :returns: the description with every reference to a renamed file rewritten; anything else (an
        already-current name, an image the conversion left alone, an external URL, a typo) is left
        untouched.
    """
    return TcDescriptionRewriter(renames).rewrite(description)


class TcDescriptionRewriter:  # pylint: disable=too-few-public-methods
    """Rewrites a description's embedded image references per one screenshot scan ([[acquisition-tooling#tc-to-rehu]]).

    **Only a file the conversion renames is rewritten**, and a reference keeps the form it was written
    in (#288): ``![](image-01)`` becomes ``![](info01)`` and ``![](image-01.jpg)`` becomes
    ``![](info01.jpg)``. A reference naming just the filename's stem, with no extension (a real pattern
    confirmed against an actual `.tc` description, e.g. ``![](cover)``), was always the common form and
    stays extension-less. A reference to a name that is still on disk under that name -- an image whose
    slot was taken, so the conversion left it alone -- is left as it was, since it still resolves.

    Matching is case-insensitive (legacy filenames were never guaranteed consistent casing) and ignores
    any leading path a reference might carry (e.g. ``images/cover.jpg``) -- the rewritten name is always
    bare, since converted screenshots live directly alongside the ``.rehu``, not in a subdirectory.

    :param renames: the renames a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` plan carries.
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

    def __build_lookup(self, renames: Sequence[ScreenshotRename]) -> dict[str, str]:
        """Map each renamed file -- as a full filename and as a bare stem -- to its new spelling.

        Two entries per rename rather than one, so a reference is answered in its own form: the
        extension-full key maps to the extension-full new name, the bare stem to the bare new stem.

        :param renames: the renames a :func:`rehuco_core.tc_screenshots.scan_tc_screenshots` plan
            carries.
        :returns: ``{lowercased old name or stem: the new name in the same form}``.
        """
        table: dict[str, str] = {}
        for rename in renames:
            old_name, new_name = rename.source_filename, rename.new_name
            table[old_name.lower()] = new_name
            table[self.__stem_of(old_name).lower()] = self.__stem_of(new_name)
        return table

    @staticmethod
    def __stem_of(filename: str) -> str:
        """``filename`` without its extension.

        :param filename: a bare filename.
        :returns: everything before the last dot, or the whole name when it carries none.
        """
        return filename.rsplit(".", 1)[0] if "." in filename else filename
