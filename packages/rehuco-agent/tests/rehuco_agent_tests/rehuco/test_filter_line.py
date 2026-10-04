"""Tests for the filter line's grammar: free text and ``field:"value"`` tokens, read into a query and the columns
shown (#398)."""

import pytest
from rehuco_agent.rehuco.catalog_table_model import COLUMN_IDS
from rehuco_agent.rehuco.filter_line import COLUMNS_TOKEN, format_token, parse_filter, with_token
from rehuco_core import CatalogField, CatalogQuery


def test_free_text_only_is_the_query_text_with_its_words_joined_by_one_space() -> None:
    """Words that are not tokens make up the free text, however they were spaced.

    **Test steps:**

    * parse two words with extra whitespace around and between them
    * verify the query's text joins them with one space, with no tokens, columns or problems
    """
    parsed = parse_filter("  blender    intro ", COLUMN_IDS)

    assert parsed.query == CatalogQuery("blender intro")
    assert (parsed.columns, parsed.problems, parsed.tokens) == (None, (), ())


@pytest.mark.parametrize("field", list(CatalogField))
def test_each_field_token_compiles_to_its_catalog_field(field: CatalogField) -> None:
    """Every field the cache can filter on is reachable by its spelling.

    **Test steps:**

    * parse ``<field>:value`` for each field
    * verify the query carries that field and value, and no free text
    """
    assert parse_filter(f"{field.value}:value", COLUMN_IDS).query == CatalogQuery("", ((field, "value"),))


def test_tokens_only_leave_no_free_text() -> None:
    """A line of tokens filters on them alone.

    **Test steps:**

    * parse two tokens
    * verify both are in the query, in order, and the text is empty
    """
    parsed = parse_filter("type:tutorial tags:python", COLUMN_IDS)

    assert parsed.query == CatalogQuery("", ((CatalogField.TYPE, "tutorial"), (CatalogField.TAGS, "python")))


def test_free_text_and_tokens_mix_in_any_order() -> None:
    """Text before, between and after tokens is all free text.

    **Test steps:**

    * parse a word, a token, another word
    * verify the text joins both words and the token is kept
    """
    parsed = parse_filter("intro authors:Foo course", COLUMN_IDS)

    assert parsed.query == CatalogQuery("intro course", ((CatalogField.AUTHORS, "Foo"),))


def test_a_quoted_value_keeps_its_spaces_and_unescapes_quotes_and_backslashes() -> None:
    """A quoted value is one value, with ``\\"`` and ``\\\\`` its only escapes.

    **Test steps:**

    * parse a quoted authors value with a space, an escaped quote and an escaped backslash
    * verify the value as the cache is given it
    """
    parsed = parse_filter(r'authors:"Foo \"Bar\" \\ Co"', COLUMN_IDS)

    assert parsed.query.tokens == ((CatalogField.AUTHORS, 'Foo "Bar" \\ Co'),)


def test_quoted_free_text_is_one_phrase() -> None:
    """A quoted run with no name in front is free text, spaces and all.

    **Test steps:**

    * parse a quoted phrase, then an empty quoted run beside a word
    * verify the phrase is the query's text, and the empty run adds nothing
    """
    assert parse_filter('"blender  intro"', COLUMN_IDS).query == CatalogQuery("blender  intro")
    assert parse_filter('"" intro', COLUMN_IDS).query == CatalogQuery("intro")


def test_an_unclosed_quote_runs_to_the_end_of_the_line() -> None:
    """A quote still being typed takes the rest of the line.

    **Test steps:**

    * parse a token whose quote is never closed
    * verify its value is everything after the quote
    """
    assert parse_filter('folder:"Tutorials/Blender ba', COLUMN_IDS).query.tokens == (
        (CatalogField.FOLDER, "Tutorials/Blender ba"),
    )


def test_a_repeated_field_is_kept_twice() -> None:
    """Two tags mean a resource with both, as the cache ANDs every token.

    **Test steps:**

    * parse the tags field twice
    * verify both tokens are in the query
    """
    assert parse_filter("tags:a tags:b", COLUMN_IDS).query.tokens == (
        (CatalogField.TAGS, "a"),
        (CatalogField.TAGS, "b"),
    )


def test_a_field_name_is_matched_whatever_its_case() -> None:
    """``Authors:`` is the authors field.

    **Test steps:**

    * parse a token whose name is capitalized
    * verify it compiles to the authors field and the token is recorded lowercased
    """
    parsed = parse_filter("Authors:Foo", COLUMN_IDS)

    assert parsed.query.tokens == ((CatalogField.AUTHORS, "Foo"),)
    assert parsed.tokens[0].name == "authors"


def test_an_unknown_field_is_reported_and_the_rest_still_applies() -> None:
    """An unknown name is never silently dropped, nor allowed to spoil the rest of the line.

    **Test steps:**

    * parse free text, an unknown field and a known one
    * verify the problem names the field, and the text and the known token still apply
    """
    parsed = parse_filter("intro colour:red type:tutorial", COLUMN_IDS)

    assert parsed.problems == ('Unknown field "colour"',)
    assert parsed.query == CatalogQuery("intro", ((CatalogField.TYPE, "tutorial"),))


def test_a_token_with_no_value_yet_is_ignored_without_a_word() -> None:
    """``authors:`` is what a token looks like while it is typed: neither applied nor reported.

    **Test steps:**

    * parse a known and an unknown name, each with nothing after its colon
    * verify no field token and no problem
    """
    parsed = parse_filter('authors: colour:""', COLUMN_IDS)

    assert (parsed.query, parsed.problems) == (CatalogQuery(), ())
    assert [token.name for token in parsed.tokens] == ["authors", "colour"]


def test_the_columns_token_names_the_columns_in_its_order() -> None:
    """``columns:`` picks columns by id, whatever their case and spacing, without becoming a field.

    **Test steps:**

    * parse a columns token naming two columns
    * verify the columns, in the token's order, and an empty query
    """
    parsed = parse_filter('columns:"Title, authors"', COLUMN_IDS)

    assert parsed.columns == ("title", "authors")
    assert parsed.query == CatalogQuery()


def test_an_unknown_column_is_reported_and_the_known_ones_still_apply() -> None:
    """A column name with no column behind it is reported, not dropped in silence.

    **Test steps:**

    * parse a columns token naming one real and one made-up column
    * then one naming only a made-up one
    * verify the first keeps the real column with a problem, the second names no columns
    """
    parsed = parse_filter("columns:title,colour", COLUMN_IDS)
    assert (parsed.columns, parsed.problems) == (("title",), ('Unknown column "colour"',))

    assert parse_filter("columns:colour", COLUMN_IDS).columns is None


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
    parsed = parse_filter(written, COLUMN_IDS)
    assert parsed.tokens[0].value == value


def test_setting_a_token_replaces_every_word_of_its_field_and_keeps_the_rest() -> None:
    """A click sets a field rather than adding to it, and leaves what was typed alone.

    **Test steps:**

    * set authors on a line with two authors tokens between free text and another token
    * verify both old ones are gone, the rest kept as written, and the new one appended quoted
    """
    line = 'intro authors:Old  "a  phrase" authors:"Older One" type:tutorial'

    assert with_token(line, COLUMN_IDS, "authors", "Foo Bar") == ('intro "a  phrase" type:tutorial authors:"Foo Bar"')


def test_setting_a_token_on_an_empty_line_is_the_token_alone() -> None:
    """Nothing typed yet is the simplest line.

    **Test steps:**

    * set a token on an empty line
    * verify the line is that token
    """
    assert with_token("", COLUMN_IDS, "folder", "Tutorials/Blender") == "folder:Tutorials/Blender"


def test_a_token_set_to_none_is_removed() -> None:
    """``None`` only takes the field's words out.

    **Test steps:**

    * remove the columns token from a line that has one
    * verify the rest of the line is left
    """
    assert with_token("intro columns:title type:x", COLUMN_IDS, COLUMNS_TOKEN, None) == "intro type:x"
