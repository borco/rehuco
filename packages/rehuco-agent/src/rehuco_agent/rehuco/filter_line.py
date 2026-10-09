"""The filter line's grammar (#398, [[plugins#rehuco-dock]]): free text and ``field:"value"`` tokens, read into the
:class:`~rehuco_core.CatalogQuery` a browser's rows come from. Which columns show is the header's alone (#379).

Words are separated by whitespace; a ``"..."`` run is one value, with ``\\"`` and ``\\\\`` its only escapes, and an
unclosed quote runs to the end of the line -- :func:`borco_core.read_value`, the quoting every search box shares. A
word that starts with a name and a colon is a token -- ``name:value`` or ``name:"quoted value"`` -- and every other
word is a free-text term: ``foo bar`` finds what holds both, in any order, and ``"foo bar"`` the phrase. Every term and
every token must match.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from borco_core import read_value
from rehuco_core import CatalogField, CatalogQuery

RETIRED_TOKENS: Final = ("columns",)
"""Tokens an older build wrote into a browser's remembered line and this one no longer reads: ``columns:`` named the
columns shown until #379 left that to the header menu. Dropped from a line on load, without a word."""

NAME_PATTERN: Final = re.compile(r"([A-Za-z_]+):")
"""A token's name and its colon, at the start of a word; matched case-insensitively against the known names."""


@dataclass(frozen=True, slots=True)
class FilterToken:
    """One ``name:value`` word as it stands in the line.

    :param name: the name, lowercased.
    :param value: the value, unquoted and unescaped; empty while it is still being typed.
    :param start: where the word starts in the line.
    :param end: where it ends, exclusive.
    """

    name: str
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ParsedFilter:
    """What a filter line says.

    :param query: the free-text terms and every field token, in the line's order.
    :param problems: one sentence per word that was not applied -- an unknown field. The rest of the line still
        applies.
    :param tokens: every ``name:value`` word, applied or not, so the line can be rewritten around them.
    """

    query: CatalogQuery
    problems: tuple[str, ...]
    tokens: tuple[FilterToken, ...]


def parse_filter(text: str) -> ParsedFilter:
    """Read a filter line.

    A token with an empty value is ignored without a word: it is what a token looks like while it is typed.

    :param text: the line.
    :returns: the query and what could not be applied.
    """
    terms: list[str] = []
    tokens: list[FilterToken] = []
    fields: list[tuple[CatalogField, str]] = []
    problems: list[str] = []
    for name, value, start, end in split_words(text):
        if name is None:
            if value:
                terms.append(value)
            continue
        tokens.append(FilterToken(name, value, start, end))
        if not value:
            continue
        try:
            fields.append((CatalogField(name), value))
        except ValueError:
            problems.append(f'Unknown field "{name}"')
    return ParsedFilter(CatalogQuery(tuple(terms), tuple(fields)), tuple(problems), tuple(tokens))


def format_token(name: str, value: str) -> str:
    """Write one token as the line reads it back: bare when it can be, quoted when it must.

    :param name: the token's name.
    :param value: its value.
    :returns: ``name:value``, or ``name:"value"`` for a value that is empty, holds whitespace or starts with a
        quote -- with ``\\`` and ``"`` escaped inside the quotes.
    """
    if value and not value.startswith('"') and not any(char.isspace() for char in value):
        return f"{name}:{value}"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{name}:"{escaped}"'


def with_token(text: str, name: str, value: str | None) -> str:
    """Set one token on a line: every word naming ``name`` goes, and the new one is appended.

    A click sets a field rather than adding to it -- one link, one filter -- and the rest of the line is kept as it
    was written.

    :param text: the line.
    :param name: the token's name.
    :param value: its new value; ``None`` only removes the old ones.
    :returns: the rewritten line.
    """
    pieces: list[str] = []
    position = 0
    for token in parse_filter(text).tokens:
        if token.name == name:
            pieces.append(text[position : token.start])
            position = token.end
    pieces.append(text[position:])
    kept = [piece.strip() for piece in pieces if piece.strip()]
    if value is not None:
        kept.append(format_token(name, value))
    return " ".join(kept)


def without_retired_tokens(text: str) -> str:
    """A remembered line with every :data:`RETIRED_TOKENS` word taken out -- for a line saved by an older build, as it
    is loaded; one typed now that names one is an unknown field like any other.

    :param text: the line as it was saved.
    :returns: the line without them; ``text`` itself when it held none.
    """
    names = {token.name for token in parse_filter(text).tokens}
    for name in RETIRED_TOKENS:
        if name in names:
            text = with_token(text, name, None)
    return text


def split_words(text: str) -> Iterator[tuple[str | None, str, int, int]]:
    """Split a line into its words.

    :param text: the line.
    :returns: per word its token name (lowercased, ``None`` for free text), its value, start and end.
    """
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        start = position
        name = None
        matched = NAME_PATTERN.match(text, position)
        if matched is not None:
            name = matched.group(1).lower()
            position = matched.end()
        value, position = read_value(text, position)
        yield name, value, start, position
