"""The words a web search for a resource's name is made of (#388).

A location name carries a publisher, a title, an author, a size and a year, joined by the punctuation a
filename convention wants and a search engine does not: ``SomePublisher - SomeTitle - SomeAuthor (300+)
[2025]``. `web_search_query` keeps the words and drops that punctuation, so the same name searches the
same way however it happens to be decorated.
"""

from typing import Final

REMOVED_CHARACTERS: Final = str.maketrans("", "", '()[]{}<>"“”„«»‹›')
"""Dropped wherever they occur in a word: every kind of bracket and the double quotes. A single quote is
not here, since inside a word it is an apostrophe (``Artist's``) -- at a word's edge
:data:`EDGE_PUNCTUATION` takes it."""

EDGE_PUNCTUATION: Final = "-–—―,;:.!?|/\\&*~_=@^%$`'‘’…•·"
"""Stripped from both ends of a word and kept inside it (``Sci-Fi``, ``v1.2``). ``+`` and ``#`` are
deliberately absent: ``300+``, ``C++`` and ``C#`` are the words themselves."""


def web_search_query(text: str) -> str:
    """``text``'s words with the punctuation dropped, ready to be searched for.

    Applied per whitespace-separated word: brackets and double quotes are removed wherever they are,
    :data:`EDGE_PUNCTUATION` is stripped from the word's edges, and a word left empty is dropped -- which
    is what removes a standalone `` - `` separator. The words are joined by single spaces.

    :param text: what to search for -- a location name, or any other text.
    :returns: the query, empty when ``text`` holds no word at all.
    """
    words = (word.translate(REMOVED_CHARACTERS).strip(EDGE_PUNCTUATION) for word in text.split())
    return " ".join(word for word in words if word)
