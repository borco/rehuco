"""Tests for what the filter line reads of an asset (#678): the ``kind``, ``license`` and ``formats`` tokens, the
empty kind, and comparisons of the advertised ranges by their bounds."""

import pytest
from rehuco_agent.rehuco.filter_line import format_token, parse_filter, with_token
from rehuco_core import CatalogComparison, CatalogField, CatalogOperator, CatalogQuery, CatalogRangeField

TRIANGLES = CatalogRangeField.ADVERTISED_TRIANGLES
TEXTURES = CatalogRangeField.ADVERTISED_TEXTURE_SIZE


@pytest.mark.parametrize(
    ("word", "operator"),
    [
        ("advertised_triangles<15", CatalogOperator.LESS),
        ("advertised_triangles<=15", CatalogOperator.LESS_OR_EQUAL),
        ("advertised_triangles>15", CatalogOperator.GREATER),
        ("advertised_triangles>=15", CatalogOperator.GREATER_OR_EQUAL),
        ("ADVERTISED_Triangles>=15", CatalogOperator.GREATER_OR_EQUAL),
    ],
)
def test_a_range_field_and_a_number_make_a_comparison(word: str, operator: CatalogOperator) -> None:
    """Each of the four operators reads, the two-character ones whole, whatever the case of the field.

    **Test steps:**

    * parse a comparison of the advertised triangles with each operator
    * verify the query holds that comparison and no free text, and nothing is reported

    :param word: the comparison as typed.
    :param operator: the operator it holds.
    """
    parsed = parse_filter(word)

    assert parsed.query == CatalogQuery(comparisons=(CatalogComparison(TRIANGLES, operator, 15),))
    assert not parsed.problems
    assert not parsed.tokens


def test_comparisons_mix_with_text_and_tokens_and_each_must_hold() -> None:
    """Both range fields can be compared, twice over, in any place of a line.

    **Test steps:**

    * parse a line of a word, a token and three comparisons
    * verify the text, the token and the comparisons are all kept, in order
    """
    parsed = parse_filter(
        "rock advertised_triangles>10 kind:model advertised_triangles<100 advertised_texture_size>=2048"
    )

    assert parsed.query.terms == ("rock",)
    assert parsed.query.tokens == ((CatalogField.KIND, "model"),)
    assert parsed.query.comparisons == (
        CatalogComparison(TRIANGLES, CatalogOperator.GREATER, 10),
        CatalogComparison(TRIANGLES, CatalogOperator.LESS, 100),
        CatalogComparison(TEXTURES, CatalogOperator.GREATER_OR_EQUAL, 2048),
    )


@pytest.mark.parametrize("word", ["advertised_triangles<", "advertised_texture_size>="])
def test_a_comparison_with_no_number_yet_is_ignored_while_it_is_typed(word: str) -> None:
    """Half a comparison filters nothing and says nothing, as a token with no value does.

    **Test steps:**

    * parse a comparison with no number
    * verify the query is empty and nothing is reported

    :param word: the comparison as far as typed.
    """
    parsed = parse_filter(word)

    assert parsed.query == CatalogQuery()
    assert not parsed.problems


@pytest.mark.parametrize("number", ["many", "1.5", "-3", "12-14", "1" * 19, "²"])
def test_a_number_that_is_not_a_whole_number_is_reported_and_not_applied(number: str) -> None:
    """What a range is compared to is a whole number the cache can hold: anything else is named as a problem.

    **Test steps:**

    * parse a comparison to a text that is no whole number, and a word beside it
    * verify the comparison was not applied, the word still is, and one problem names the number

    :param number: what the field is compared to.
    """
    parsed = parse_filter(f"rock advertised_triangles<{number}")

    assert parsed.query == CatalogQuery(("rock",))
    assert parsed.problems == (f'"{number}" is not a whole number to compare advertised_triangles with',)


@pytest.mark.parametrize(
    "line",
    ['"advertised_triangles<15"', "triangles<15", "texture_size>1", "advertised_size<15", "advertised_triangles=15"],
)
def test_a_word_that_is_no_comparison_of_a_range_field_stays_free_text(line: str) -> None:
    """A quoted phrase, the measured counts and any other name are searched for as words, as they always were.

    **Test steps:**

    * parse the line
    * verify it is one free-text term and no comparison

    :param line: the line.
    """
    parsed = parse_filter(line)

    assert not parsed.query.comparisons
    assert parsed.query.terms == (line.strip('"'),)


@pytest.mark.parametrize("field", ["kind", "licenses", "formats"])
def test_an_asset_token_matches_a_whole_value(field: str) -> None:
    """The three tokens an asset adds are field tokens like the others.

    **Test steps:**

    * parse each token with a value
    * verify the query carries it
    """
    assert parse_filter(f'{field}:"Fab Standard"').query.tokens == ((CatalogField(field), "Fab Standard"),)


def test_an_empty_kind_in_quotes_asks_for_a_record_with_none_and_no_other_empty_token_does() -> None:
    """``kind:""`` is the one empty value that means something: the assets whose block names no kind. A token still
    being typed, and any other empty one, is ignored as before.

    **Test steps:**

    * parse ``kind:""`` and verify it is a kind token with no value
    * parse ``kind:``, ``kind:"`` and ``licenses:""`` and verify none is applied
    """
    assert parse_filter('kind:""').query.tokens == ((CatalogField.KIND, ""),)
    assert not parse_filter("kind:").query.tokens
    assert not parse_filter('kind:"').query.tokens
    assert not parse_filter('licenses:""').query.tokens


def test_an_empty_kind_is_written_and_replaced_as_a_quoted_token() -> None:
    """The line writes an empty value in quotes, so a click on it reads back as the same token.

    **Test steps:**

    * format an empty kind and replace the kind of a line with it
    * verify the quoted token, and that it reads back
    """
    assert format_token("kind", "") == 'kind:""'
    assert with_token("rock kind:model", "kind", "") == 'rock kind:""'
    assert parse_filter(with_token("rock kind:model", "kind", "")).query.tokens == ((CatalogField.KIND, ""),)
