"""Searching text the way a person types it: every word must be found, a ``"..."`` run is one phrase, and case and
diacritics are ignored both ways -- "jose" finds "José" and "José" finds "Jose".

Both sides go through :func:`fold`, the search terms and the text searched, so whichever spelling is typed or stored
the two meet. A search box holds a :class:`TextMatcher` built from its text and asks it about each row; a database
stores each searched text folded and compares those columns against folded terms.

A stored folded copy is only as good as the :func:`fold` that wrote it. The cache keeps a fingerprint of the
:func:`fold` it last wrote with and writes the copies again, from the real columns, when it opens under a different
one -- so :func:`fold` can change without a version bump or a migration.

Words are separated by whitespace; a ``"..."`` run is one term, with ``\\"`` and ``\\\\`` its only escapes, and an
unclosed quote runs to the end of the line.
"""

import unicodedata
from dataclasses import dataclass
from typing import Self


def fold(text: str) -> str:
    """``text`` as a search compares it: compatibility-decomposed, case-folded and without combining marks.

    NFKD takes a precomposed letter apart (``é`` → ``e`` + ``´``) and a compatibility form to its plain one (``ﬁ`` →
    ``fi``); ``casefold`` is the full Unicode case fold (``ß`` → ``ss``). Each can undo the other -- casefolding
    ``İ`` brings back a combining dot, decomposing ``ℌ`` an uppercase ``H`` -- so the text is decomposed both before
    and after the fold, and only then are the marks dropped.

    :param text: any text.
    :returns: its folded form; two texts that differ only in case, accents or compatibility forms fold alike.
    """
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", text).casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def search_terms(text: str) -> tuple[str, ...]:
    """Split a search into its terms: whitespace-separated words, a quoted run being one.

    :param text: the search as typed.
    :returns: the terms, unquoted and unescaped, in order; an empty quoted run is no term.
    """
    terms: list[str] = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        term, position = read_value(text, position)
        if term:
            terms.append(term)
    return tuple(terms)


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


@dataclass(frozen=True, slots=True)
class TextMatcher:
    """A search, ready to be asked about text: matches when every term is found somewhere in it.

    :param terms: the search's terms, already folded.
    """

    terms: tuple[str, ...] = ()

    @classmethod
    def of(cls, text: str) -> Self:
        """The matcher a search box's text reads as.

        :param text: the search as typed.
        :returns: its matcher; one with no terms, which matches everything, for blank text.
        """
        return cls(tuple(fold(term) for term in search_terms(text)))

    def __bool__(self) -> bool:
        """Whether there is anything to search for."""
        return bool(self.terms)

    def matches(self, *haystacks: str) -> bool:
        """Whether every term is found in at least one of ``haystacks`` -- a row's title and its path, say, each term
        free to match in either.

        :param haystacks: the texts to search, as they are shown; folded here.
        :returns: ``True`` when every term is found, and always for a matcher with no terms.
        """
        folded = [fold(haystack) for haystack in haystacks]
        return all(any(term in haystack for haystack in folded) for term in self.terms)
