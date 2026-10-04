"""The filter line's grammar (#398, [[plugins#rehuco-dock]]): free text and ``field:"value"`` tokens, read into the
:class:`~rehuco_core.CatalogQuery` a browser's rows come from and the columns it shows.

Words are separated by whitespace; a ``"..."`` run is one value, with ``\\"`` and ``\\\\`` its only escapes, and an
unclosed quote runs to the end of the line. A word that starts with a name and a colon is a token -- ``name:value``
or ``name:"quoted value"`` -- and every other word is free text. Tokens and the free text are ANDed.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from rehuco_core import CatalogField, CatalogQuery

COLUMNS_TOKEN: Final = "columns"
"""The token naming the columns a browser shows, comma-separated: ``columns:authors,title``."""

COLUMN_SEPARATOR: Final = ","

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

    :param query: the free text and every field token, in the line's order.
    :param columns: the column ids a ``columns:`` token names, the known ones only, in its order; ``None`` while
        the line has no such token, or names no column there is.
    :param problems: one sentence per word that was not applied -- an unknown field or column. The rest of the
        line still applies.
    :param tokens: every ``name:value`` word, applied or not, so the line can be rewritten around them.
    """

    query: CatalogQuery
    columns: tuple[str, ...] | None
    problems: tuple[str, ...]
    tokens: tuple[FilterToken, ...]


def parse_filter(text: str, column_ids: Sequence[str]) -> ParsedFilter:
    """Read a filter line.

    A token with an empty value is ignored without a word: it is what a token looks like while it is typed.

    :param text: the line.
    :param column_ids: the ids a ``columns:`` token may name.
    :returns: the query, the columns and what could not be applied.
    """
    free: list[str] = []
    tokens: list[FilterToken] = []
    fields: list[tuple[CatalogField, str]] = []
    columns: tuple[str, ...] | None = None
    problems: list[str] = []
    for name, value, start, end in split_words(text):
        if name is None:
            if value:
                free.append(value)
            continue
        tokens.append(FilterToken(name, value, start, end))
        if not value:
            continue
        if name == COLUMNS_TOKEN:
            named = dict.fromkeys(part.strip().lower() for part in value.split(COLUMN_SEPARATOR) if part.strip())
            problems.extend(f'Unknown column "{column}"' for column in named if column not in column_ids)
            known = tuple(column for column in named if column in column_ids)
            columns = known or None
            continue
        try:
            fields.append((CatalogField(name), value))
        except ValueError:
            problems.append(f'Unknown field "{name}"')
    return ParsedFilter(CatalogQuery(" ".join(free), tuple(fields)), columns, tuple(problems), tuple(tokens))


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


def with_token(text: str, column_ids: Sequence[str], name: str, value: str | None) -> str:
    """Set one token on a line: every word naming ``name`` goes, and the new one is appended.

    A click sets a field rather than adding to it -- one link, one filter -- and the rest of the line is kept as it
    was written.

    :param text: the line.
    :param column_ids: the ids a ``columns:`` token may name, as :func:`parse_filter` takes them.
    :param name: the token's name.
    :param value: its new value; ``None`` only removes the old ones.
    :returns: the rewritten line.
    """
    pieces: list[str] = []
    position = 0
    for token in parse_filter(text, column_ids).tokens:
        if token.name == name:
            pieces.append(text[position : token.start])
            position = token.end
    pieces.append(text[position:])
    kept = [piece.strip() for piece in pieces if piece.strip()]
    if value is not None:
        kept.append(format_token(name, value))
    return " ".join(kept)


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


def read_value(text: str, position: int) -> tuple[str, int]:
    """Read one value: a quoted run, or everything up to the next whitespace.

    :param text: the line.
    :param position: where the value starts.
    :returns: the value and where it ends.
    """
    if position < len(text) and text[position] == '"':
        return read_quoted(text, position + 1)
    end = position
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[position:end], end


def read_quoted(text: str, position: int) -> tuple[str, int]:
    """Read a quoted run, its opening quote already consumed.

    :param text: the line.
    :param position: just past the opening quote.
    :returns: the unescaped value and where the run ends -- past the closing quote, or the end of the line.
    """
    chars: list[str] = []
    while position < len(text):
        char = text[position]
        if char == "\\" and position + 1 < len(text):
            chars.append(text[position + 1])
            position += 2
            continue
        if char == '"':
            return "".join(chars), position + 1
        chars.append(char)
        position += 1
    return "".join(chars), position
