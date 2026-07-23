"""Comma-separated single-line text <-> trimmed string list: the shared shape the `text list` and
`authors` comma editors round-trip through ([[plugins#field-toolkit]], [[field-schema#authors]]).

Both fields present a single ``QLineEdit`` whose text is a comma-separated list. Keeping the split and
join in one place is what lets the #95 lossless-editor guard and the #92 string-or-record authors
entries stay behavior-identical across the two fields -- :class:`~rehuco_agent.fields.authors_field.AuthorsField`
only ever feeds :meth:`TextListString.join` / :meth:`TextListString.split` plain-string names (its
record and comma-in-name entries disable the editor upstream), so the two fields share exactly one
parsing rule.
"""

from collections.abc import Iterable
from typing import Final


class TextListString:
    """The comma-separated ``QLineEdit`` text of a `text list` / `authors` editor, and the one rule
    for parsing it to a list and rendering a list back to it ([[plugins#field-toolkit]]).

    Stateless: :meth:`split` and :meth:`join` are the inverse pair every comma editor shares, so the
    trimming and separator live in exactly one place rather than duplicated per field.
    """

    __JOIN_SEPARATOR: Final = ", "
    """What :meth:`join` puts between entries: a comma **and a space**, the readable form a user sees."""

    __SPLIT_SEPARATOR: Final = ","
    """What :meth:`split` splits on: a bare comma, so a user's own spacing around it is trimmed away
    rather than kept."""

    @classmethod
    def join(cls, items: Iterable[str]) -> str:
        """Join entries into their comma-separated text form.

        :param items: the entries to join.
        :returns: the joined text.
        """
        return cls.__JOIN_SEPARATOR.join(items)

    @classmethod
    def split(cls, text: str) -> list[str]:
        """Split comma-separated text into a list, trimming whitespace and dropping empty entries.

        :param text: the text to split.
        :returns: the parsed list.
        """
        return [item.strip() for item in text.split(cls.__SPLIT_SEPARATOR) if item.strip()]
