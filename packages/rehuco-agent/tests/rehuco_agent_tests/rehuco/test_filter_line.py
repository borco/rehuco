"""Tests for the filter line's grammar: free text and ``field:"value"`` tokens, read into a query (#398); the
``columns:`` token it once had is retired (#379); ``in:`` says where free text looks (#647)."""

import pytest
from rehuco_agent.rehuco.filter_line import format_token, parse_filter, with_token, without_retired_tokens
from rehuco_core import CatalogField, CatalogQuery, CatalogTextField


def test_free_text_only_is_one_term_per_word() -> None:
    """Words that are not tokens are free-text terms, one each, however they were spaced.

    **Test steps:**

    * parse two words with extra whitespace around and between them
    * verify the query holds them as two terms, with no tokens or problems
    """
    parsed = parse_filter("  blender    intro ")

    assert parsed.query == CatalogQuery(("blender", "intro"))
    assert (parsed.problems, parsed.tokens) == ((), ())


@pytest.mark.parametrize("field", list(CatalogField))
def test_each_field_token_compiles_to_its_catalog_field(field: CatalogField) -> None:
    """Every field the cache can filter on is reachable by its spelling.

    **Test steps:**

    * parse ``<field>:value`` for each field
    * verify the query carries that field and value, and no free text
    """
    assert parse_filter(f"{field.value}:value").query == CatalogQuery((), ((field, "value"),))


def test_tokens_only_leave_no_free_text() -> None:
    """A line of tokens filters on them alone.

    **Test steps:**

    * parse two tokens
    * verify both are in the query, in order, and the text is empty
    """
    parsed = parse_filter("type:tutorial tags:python")

    assert parsed.query == CatalogQuery((), ((CatalogField.TYPE, "tutorial"), (CatalogField.TAGS, "python")))


def test_free_text_and_tokens_mix_in_any_order() -> None:
    """Text before, between and after tokens is all free text.

    **Test steps:**

    * parse a word, a token, another word
    * verify the text joins both words and the token is kept
    """
    parsed = parse_filter("intro authors:Foo course")

    assert parsed.query == CatalogQuery(("intro", "course"), ((CatalogField.AUTHORS, "Foo"),))


def test_a_quoted_value_keeps_its_spaces_and_unescapes_quotes_and_backslashes() -> None:
    """A quoted value is one value, with ``\\"`` and ``\\\\`` its only escapes.

    **Test steps:**

    * parse a quoted authors value with a space, an escaped quote and an escaped backslash
    * verify the value as the cache is given it
    """
    parsed = parse_filter(r'authors:"Foo \"Bar\" \\ Co"')

    assert parsed.query.tokens == ((CatalogField.AUTHORS, 'Foo "Bar" \\ Co'),)


def test_quoted_free_text_is_one_phrase() -> None:
    """A quoted run with no name in front is free text, spaces and all.

    **Test steps:**

    * parse a quoted phrase, then an empty quoted run beside a word
    * verify the phrase is one term, and the empty run adds none
    """
    assert parse_filter('"blender  intro"').query == CatalogQuery(("blender  intro",))
    assert parse_filter('"" intro').query == CatalogQuery(("intro",))


def test_an_unclosed_quote_runs_to_the_end_of_the_line() -> None:
    """A quote still being typed takes the rest of the line.

    **Test steps:**

    * parse a token whose quote is never closed
    * verify its value is everything after the quote
    """
    assert parse_filter('folder:"Tutorials/Blender ba').query.tokens == ((CatalogField.FOLDER, "Tutorials/Blender ba"),)


def test_a_repeated_field_is_kept_twice() -> None:
    """Two tags mean a resource with both, as the cache ANDs every token.

    **Test steps:**

    * parse the tags field twice
    * verify both tokens are in the query
    """
    assert parse_filter("tags:a tags:b").query.tokens == (
        (CatalogField.TAGS, "a"),
        (CatalogField.TAGS, "b"),
    )


def test_a_field_name_is_matched_whatever_its_case() -> None:
    """``Authors:`` is the authors field.

    **Test steps:**

    * parse a token whose name is capitalized
    * verify it compiles to the authors field and the token is recorded lowercased
    """
    parsed = parse_filter("Authors:Foo")

    assert parsed.query.tokens == ((CatalogField.AUTHORS, "Foo"),)
    assert parsed.tokens[0].name == "authors"


def test_an_unknown_field_is_reported_and_the_rest_still_applies() -> None:
    """An unknown name is never silently dropped, nor allowed to spoil the rest of the line.

    **Test steps:**

    * parse free text, an unknown field and a known one
    * verify the problem names the field, and the text and the known token still apply
    """
    parsed = parse_filter("intro colour:red type:tutorial")

    assert parsed.problems == ('Unknown field "colour"',)
    assert parsed.query == CatalogQuery(("intro",), ((CatalogField.TYPE, "tutorial"),))


def test_a_token_with_no_value_yet_is_ignored_without_a_word() -> None:
    """``authors:`` is what a token looks like while it is typed: neither applied nor reported.

    **Test steps:**

    * parse a known and an unknown name, each with nothing after its colon
    * verify no field token and no problem
    """
    parsed = parse_filter('authors: colour:""')

    assert (parsed.query, parsed.problems) == (CatalogQuery(), ())
    assert [token.name for token in parsed.tokens] == ["authors", "colour"]


def test_a_columns_word_typed_now_is_an_unknown_field() -> None:
    """Columns are the header menu's alone: a ``columns:`` word is a field there is not, reported like any other.

    **Test steps:**

    * parse a line holding a columns word and a type token
    * verify the type applies and the columns word is reported
    """
    parsed = parse_filter("columns:title type:tutorial")

    assert parsed.query == CatalogQuery((), ((CatalogField.TYPE, "tutorial"),))
    assert parsed.problems == ('Unknown field "columns"',)


def test_a_remembered_columns_word_is_dropped_without_a_word() -> None:
    """A line an older build saved loses its ``columns:`` word as it is loaded; the rest is kept as written.

    **Test steps:**

    * strip a saved line holding a columns word between other words, and one holding none
    * verify the first loses only that word and parses without a problem, and the second is unchanged
    """
    stripped = without_retired_tokens('intro columns:"title, authors" type:tutorial')

    assert stripped == "intro type:tutorial"
    assert not parse_filter(stripped).problems
    assert without_retired_tokens('intro  "a  phrase"') == 'intro  "a  phrase"'


@pytest.mark.parametrize(
    ("value", "written"),
    [
        ("tutorial", "type:tutorial"),
        ("Foo Bar", 'type:"Foo Bar"'),
        ("", 'type:""'),
        ('"quoted', 'type:"\\"quoted"'),
        ('a "b" \\ c', 'type:"a \\"b\\" \\\\ c"'),
    ],
)
def test_a_token_is_written_bare_when_it_can_be_and_quoted_when_it_must(value: str, written: str) -> None:
    """What is written reads back as the same value.

    **Test steps:**

    * format a token
    * verify the text, and that parsing it gives the value back
    """
    assert format_token("type", value) == written
    parsed = parse_filter(written)
    assert parsed.tokens[0].value == value


def test_setting_a_token_replaces_every_word_of_its_field_and_keeps_the_rest() -> None:
    """A click sets a field rather than adding to it, and leaves what was typed alone.

    **Test steps:**

    * set authors on a line with two authors tokens between free text and another token
    * verify both old ones are gone, the rest kept as written, and the new one appended quoted
    """
    line = 'intro authors:Old  "a  phrase" authors:"Older One" type:tutorial'

    assert with_token(line, "authors", "Foo Bar") == ('intro "a  phrase" type:tutorial authors:"Foo Bar"')


def test_setting_a_token_on_an_empty_line_is_the_token_alone() -> None:
    """Nothing typed yet is the simplest line.

    **Test steps:**

    * set a token on an empty line
    * verify the line is that token
    """
    assert with_token("", "folder", "Tutorials/Blender") == "folder:Tutorials/Blender"


def test_a_token_set_to_none_is_removed() -> None:
    """``None`` only takes the field's words out.

    **Test steps:**

    * remove the authors token from a line that has one
    * verify the rest of the line is left
    """
    assert with_token("intro authors:Ann type:x", "authors", None) == "intro type:x"


# region Where free text looks (#647)


def test_free_text_looks_everywhere_by_default() -> None:
    """With no ``in:``, a term is looked for in every place.

    **Test steps:**

    * parse a word alone
    * verify the query's scope is every place
    """
    assert parse_filter("owl").query.scope == frozenset(CatalogTextField)


@pytest.mark.parametrize(
    ("line", "scope"),
    [
        ("owl in:title", {CatalogTextField.TITLE}),
        ("in:authors,publishers owl", {CatalogTextField.AUTHORS, CatalogTextField.PUBLISHERS}),
        ("in:title owl in:tags", {CatalogTextField.TITLE, CatalogTextField.TAGS}),
        ("owl In:TITLE", {CatalogTextField.TITLE}),
        ('owl in:" path , tags "', {CatalogTextField.PATH, CatalogTextField.TAGS}),
    ],
    ids=["one", "a list", "two add up", "any case", "spaced"],
)
def test_in_keeps_free_text_to_the_places_it_names(line: str, scope: set[CatalogTextField]) -> None:
    """``in:`` names places as a comma list, in any case, and several ``in:`` words add up; the terms are unchanged.

    **Test steps:**

    * parse a word with each spelling of ``in:``
    * verify the term, no field token, no problem, and the places named
    """
    parsed = parse_filter(line)

    assert parsed.query == CatalogQuery(("owl",), (), frozenset(scope))
    assert not parsed.problems


def test_an_unknown_place_is_reported_and_the_rest_still_applies() -> None:
    """A place ``in:`` does not know is reported like an unknown field; the places it does know still apply.

    **Test steps:**

    * parse a word, an ``in:`` naming an unknown place and a known one, and a field token
    * verify the problem names the place, and the term, the known place and the token still apply
    """
    parsed = parse_filter("owl in:bogus,title type:tutorial")

    assert parsed.problems == ('Unknown place "bogus" for in:',)
    assert parsed.query == CatalogQuery(
        ("owl",), ((CatalogField.TYPE, "tutorial"),), frozenset({CatalogTextField.TITLE})
    )


@pytest.mark.parametrize("line", ["owl in:", "owl in:,", "owl in:bogus"])
def test_an_in_naming_no_known_place_leaves_every_place(line: str) -> None:
    """An ``in:`` still being typed, or naming no place there is, does not hide every row.

    **Test steps:**

    * parse a word beside an empty ``in:``, an empty list, and an unknown place
    * verify the scope is every place
    """
    assert parse_filter(line).query.scope == frozenset(CatalogTextField)


def test_an_in_word_is_a_token_the_line_can_be_rewritten_around() -> None:
    """``in:`` is a token like any other word with a name, so setting another field keeps it, and it can be set.

    **Test steps:**

    * set an authors token on a line holding ``in:``, then set ``in:`` itself
    * verify the first keeps the ``in:`` word, and the second replaces it
    """
    assert with_token("owl in:title", "authors", "Ann") == "owl in:title authors:Ann"
    assert with_token("owl in:title", "in", "tags") == "owl in:tags"


# endregion
