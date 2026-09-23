"""Tests for the scrape-result JSON contract (#340)."""

from typing import Any

from pytest import mark, param, raises
from rehuco_agent.scraping.results import (
    INTEGER_FIELD_NAMES,
    SCRAPE_RESULT_SCHEMA,
    SCRAPED_FIELD_NAMES,
    InvalidScrapeResultError,
    ScrapedImage,
    ScrapeResult,
)
from rehuco_core import CORE_FIELD_NAMES, DEFAULT_PLUGIN_REGISTRY

FULL_VOCABULARY = frozenset(CORE_FIELD_NAMES) | {name for spec in DEFAULT_PLUGIN_REGISTRY for name in spec.field_names}


# region round trip
def test_to_json_from_mapping_round_trips() -> None:
    """A result built by hand survives `to_json` then `from_mapping` unchanged."""
    result = ScrapeResult(
        fields={"title": "T", "authors": [{"name": "A", "url": "https://example.com/a"}]},
        description="d",
        images=(ScrapedImage(slot=0, url="https://example.com/i.jpg", referrer="https://example.com/"),),
    )

    assert ScrapeResult.from_mapping(result.to_json()) == result


def test_from_mapping_defaults_description_and_images_when_absent() -> None:
    """A minimal mapping with only `fields` -- what a bare-bones user script can return -- is accepted."""
    result = ScrapeResult.from_mapping({"fields": {"title": "T"}})

    assert result == ScrapeResult(fields={"title": "T"}, description=None, images=())


# endregion


# region rejections
def test_missing_fields_is_rejected_naming_the_key() -> None:
    """`fields` is required, and the message says which key is missing."""
    with raises(InvalidScrapeResultError, match="fields"):
        ScrapeResult.from_mapping({})


def test_non_int_slot_is_rejected() -> None:
    """A non-integer `slot` fails the schema, naming the path."""
    with raises(InvalidScrapeResultError) as excinfo:
        ScrapeResult.from_mapping({"fields": {}, "images": [{"slot": "0", "url": "https://example.com/i.jpg"}]})

    assert "images[0].slot" in excinfo.value.path


def test_unknown_top_level_key_is_rejected_naming_the_key() -> None:
    """A key outside `fields`/`description`/`images` is rejected, and the message names it."""
    with raises(InvalidScrapeResultError, match="bogus"):
        ScrapeResult.from_mapping({"fields": {}, "bogus": 1})


def test_an_integral_float_where_an_integer_belongs_is_read_as_that_integer() -> None:
    """JSON Schema's `integer` admits `3600.0`; the built result carries the `int` the document's own
    getter reads, for `advertised_duration` and for an image's `slot` alike."""
    result = ScrapeResult.from_mapping(
        {"fields": {"advertised_duration": 3600.0}, "images": [{"slot": 1.0, "url": "https://example.com/i.jpg"}]}
    )

    assert result.fields["advertised_duration"] == 3600
    assert isinstance(result.fields["advertised_duration"], int)
    assert result.images[0].slot == 1
    assert isinstance(result.images[0].slot, int)


@mark.parametrize(
    ("mapping", "expected_path_fragment"),
    [
        param({"fields": {"title": 1}}, "fields.title", id="wrong-typed-scalar"),
        param({"fields": {"authors": "Ann"}}, "fields.authors", id="non-list-authors"),
        param(
            {"fields": {"authors": [{"name": "Ann", "url": "javascript:alert(1)"}]}},
            "fields.authors[0].url",
            id="javascript-author-url",
        ),
        param({"fields": {"authors": [{"url": "https://example.com/a"}]}}, "fields.authors[0]", id="nameless-author"),
        param({"fields": {"level": ["expert"]}}, "fields.level[0]", id="level-outside-its-value-set"),
        param({"fields": {"advertised_tags": ["a", 1]}}, "fields.advertised_tags[1]", id="number-in-tag-list"),
        param({"fields": {"current_size": 5}}, "fields", id="unknown-field-key"),
        param({"fields": {"advertised_duration": True}}, "fields.advertised_duration", id="bool-is-not-an-int"),
    ],
)
def test_each_malformed_field_is_rejected_with_its_path(mapping: dict[str, Any], expected_path_fragment: str) -> None:
    """Each malformed `fields` entry is rejected, naming a path pointing at the offending key."""
    with raises(InvalidScrapeResultError) as excinfo:
        ScrapeResult.from_mapping(mapping)

    assert expected_path_fragment in excinfo.value.path


# endregion


# region vocabulary
def test_scraped_field_names_are_all_declared_by_the_vocabulary() -> None:
    """Every name `ScrapeResult` accepts is a real field somewhere -- a drift guard against a typo or a
    field renamed in `rehuco_core` without this list following."""
    assert set(SCRAPED_FIELD_NAMES) <= FULL_VOCABULARY


def test_schema_fields_keys_equal_scraped_field_names() -> None:
    """The schema's own `fields` property list matches `SCRAPED_FIELD_NAMES` exactly."""
    fields_schema = SCRAPE_RESULT_SCHEMA["properties"]["fields"]  # type: ignore[index]
    assert set(fields_schema["properties"]) == set(SCRAPED_FIELD_NAMES)


def test_integer_field_names_equal_the_schemas_integer_typed_fields() -> None:
    """`INTEGER_FIELD_NAMES` is spelled out by hand; this holds it to the schema's own `integer` typing."""
    fields_schema = SCRAPE_RESULT_SCHEMA["properties"]["fields"]["properties"]  # type: ignore[index]
    integer_typed = {name for name, spec in fields_schema.items() if "integer" in spec["type"]}

    assert integer_typed == INTEGER_FIELD_NAMES


def test_a_measured_field_is_not_in_the_scraped_vocabulary() -> None:
    """`current_size` (measured from local files, never claimed by a page) is not something a scrape may
    return -- see the rejection test above for the schema enforcing it."""
    assert "current_size" not in SCRAPED_FIELD_NAMES


def test_a_personal_field_is_not_in_the_scraped_vocabulary() -> None:
    """`hidden_images` (the user's own curation) is not something a scrape may return."""
    assert "hidden_images" not in SCRAPED_FIELD_NAMES


# endregion


# region coerce
def test_coerce_of_a_mapping_returns_the_same_result_as_the_equivalent_dataclass() -> None:
    """A script returning a JSON-shaped mapping directly yields the same `ScrapeResult` as one returning
    the dataclass (#340: both are accepted return forms of `SiteScraper.scrape_page`)."""
    dataclass_result = ScrapeResult(fields={"title": "T"}, description="d", images=())
    mapping_result = {"fields": {"title": "T"}, "description": "d", "images": []}

    assert ScrapeResult.coerce(dataclass_result) == ScrapeResult.coerce(mapping_result)


def test_coerce_of_a_dataclass_with_a_bad_slot_is_rejected() -> None:
    """A dataclass return is validated too, not only a mapping return."""
    bad_result = ScrapeResult(fields={}, description=None, images=(ScrapedImage(slot=-1, url="u", referrer=None),))

    with raises(InvalidScrapeResultError):
        ScrapeResult.coerce(bad_result)


def test_coerce_of_neither_a_result_nor_a_mapping_is_rejected() -> None:
    """A scraper returning something else entirely (a bug) is reported the same way as a bad shape."""
    with raises(InvalidScrapeResultError):
        ScrapeResult.coerce("not a result")


# endregion
