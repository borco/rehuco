"""Tests for the search helpers: folding, splitting a search into terms, and matching text against them."""

import pytest
from borco_core import TextMatcher, fold, read_value, search_terms


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("José", "jose"),
        ("José", "jose"),  # decomposed (NFD) spelling
        ("STRAßE", "strasse"),
        ("ﬁle", "file"),  # the fi ligature, by NFKD
        ("İstanbul", "istanbul"),  # casefold brings a combining dot back
        ("ℌello", "hello"),  # NFKD brings an uppercase letter back
        ("plain", "plain"),
        ("", ""),
    ],
)
def test_fold_ignores_case_diacritics_and_compatibility_forms(text: str, folded: str) -> None:
    """Folding is what makes "jose" and "José" meet.

    **Test steps:**

    * fold a spelling with an accent, a decomposed accent, ``ß``, a ligature and two letters that undo a fold
    * verify each reads as its plain lower-case form
    """
    assert fold(text) == folded


@pytest.mark.parametrize(
    ("text", "terms"),
    [
        ("foo bar", ("foo", "bar")),
        ("  foo    bar ", ("foo", "bar")),
        ('"foo bar" baz', ("foo bar", "baz")),
        ('"foo bar" "foo baz" abc', ("foo bar", "foo baz", "abc")),
        ('"a \\"b\\" c"', ('a "b" c',)),
        ('"unclosed phrase', ("unclosed phrase",)),
        ('"" foo', ("foo",)),
        ("", ()),
        ("   ", ()),
    ],
)
def test_search_terms_split_on_whitespace_and_keep_a_quoted_run_whole(text: str, terms: tuple[str, ...]) -> None:
    """A word is a term, a quoted run is one term, an empty run is none.

    **Test steps:**

    * split words, phrases, escaped quotes, an unclosed quote, an empty quoted run and blank text
    * verify the terms
    """
    assert search_terms(text) == terms


def test_read_value_reads_a_bare_word_up_to_whitespace() -> None:
    """A value that is not quoted ends at the next whitespace, and says where.

    **Test steps:**

    * read from the middle of a line
    * verify the word and the position just past it
    """
    assert read_value("ab cd", 3) == ("cd", 5)
    assert read_value("ab cd", 0) == ("ab", 2)


def test_read_value_unescapes_a_quoted_run() -> None:
    """``\\"`` and ``\\\\`` are the quoted run's only escapes.

    **Test steps:**

    * read a quoted run holding both escapes
    * verify the unescaped value and the position past the closing quote
    """
    assert read_value(r'"a\"b\\c" rest', 0) == ('a"b\\c', 9)


def test_every_term_must_be_found_in_any_order() -> None:
    """``foo bar`` matches "bar then foo"; a quoted phrase does not.

    **Test steps:**

    * match two words against text holding them in the other order, then a phrase against the same text
    * verify the words match and the phrase does not
    """
    assert TextMatcher.of("foo bar").matches("bar then foo")
    assert not TextMatcher.of('"foo bar"').matches("bar then foo")
    assert TextMatcher.of('"foo bar"').matches("a foo bar b")
    assert not TextMatcher.of('"foo bar" "foo baz" abc').matches("foo bar abc")
    assert TextMatcher.of('"foo bar" "foo baz" abc').matches("foo bar abc", "foo baz")


def test_a_term_may_be_found_in_any_of_the_texts() -> None:
    """One term in a title and another in a path is a match.

    **Test steps:**

    * match two words against two texts that hold one each
    * verify they match, and that a missing word still fails
    """
    matcher = TextMatcher.of("intro blender")

    assert matcher.matches("Intro", "tutorials/blender")
    assert not TextMatcher.of("intro zbrush").matches("Intro", "tutorials/blender")


def test_matching_ignores_case_and_diacritics_both_ways() -> None:
    """ "jose" finds "José" and "José" finds "Jose".

    **Test steps:**

    * match each spelling against the other
    * verify both match
    """
    assert TextMatcher.of("jose").matches("José Pérez")
    assert TextMatcher.of("JOSÉ").matches("jose perez")
    assert TextMatcher.of("strasse").matches("Straße")


def test_a_blank_search_is_falsy_and_matches_everything() -> None:
    """No terms means nothing to narrow by.

    **Test steps:**

    * build a matcher from blank text and one from a word
    * verify only the second is truthy, and the blank one matches any text, even none
    """
    assert not TextMatcher.of("  ")
    assert TextMatcher.of("a")
    assert TextMatcher.of("").matches("anything")
    assert TextMatcher().matches()
