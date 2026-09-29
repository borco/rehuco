"""Tests for web_search_query: a name's words with the punctuation dropped (#388)."""

from pytest import mark
from rehuco_agent.documents.web_search_query import web_search_query


@mark.parametrize(
    ("text", "query"),
    [
        ("SomePublisher - SomeTitle - SomeAuthor (300+) [2025]", "SomePublisher SomeTitle SomeAuthor 300+ 2025"),
        ("C++ Tricks — Part 1", "C++ Tricks Part 1"),
        ("Sci-Fi Kitbash (Vol. 2)", "Sci-Fi Kitbash Vol 2"),
        ("Learning C# | Basics", "Learning C# Basics"),
        ("The Artist's “Brush” {Pack} <v1.2>", "The Artist's Brush Pack v1.2"),
        ("  lots    of \t spaces  ", "lots of spaces"),
        ("Tom & Jerry: Redux!", "Tom Jerry Redux"),
        ("---  ...  (())", ""),
        ("", ""),
    ],
    ids=[
        "the-issue-example",
        "em-dash-and-plus",
        "trailing-dot",
        "hash-kept",
        "inner-apostrophe-and-quotes",
        "spaces-collapse",
        "edge-punctuation",
        "only-punctuation",
        "empty",
    ],
)
def test_web_search_query_keeps_the_words(text: str, query: str) -> None:
    """The words survive, the punctuation around them does not.

    **Test steps:**

    * reduce each text
    * verify the query, including the ones that come out empty
    """
    assert web_search_query(text) == query
