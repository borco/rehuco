"""Tests for the Locations grammar: a pattern's problems, its placeholders, and how it renders (#322, #349,
#577).
"""

from pytest import mark
from rehuco_core import (
    BLANK_PATTERN_PROBLEM,
    EMPTY_GROUP_PROBLEM,
    KNOWN_PLACEHOLDERS,
    MALFORMED_PATTERN_PROBLEM,
    PLACEHOLDERS,
    PLUGIN_PLACEHOLDERS,
    STRAY_GROUP_MARKER_PROBLEM,
    UNKNOWN_PLACEHOLDER_PROBLEM,
    LocationPattern,
    known_placeholders_for,
    location_pattern_is_valid,
    location_pattern_problem,
    location_values,
    render_location_pattern,
)

# region location_pattern_problem


def test_a_blank_pattern_is_not_valid() -> None:
    """A blank pattern is unusable regardless of what it would otherwise parse as."""
    assert location_pattern_problem("") == BLANK_PATTERN_PROBLEM
    assert location_pattern_problem("   ") == BLANK_PATTERN_PROBLEM
    assert location_pattern_is_valid("") is False


@mark.parametrize(
    "pattern",
    ["{title", "title}", "{ti{tle}", "{title!}", "{title:>10}", "{title!r}", "{title:{}}", "{title:{series}}"],
    ids=[
        "unclosed",
        "unopened",
        "reopened",
        "conversion-cut-short",
        "spec",
        "conversion",
        "nested-spec",
        "nested-name",
    ],
)
def test_a_malformed_placeholder_is_refused(pattern: str) -> None:
    """A brace with no partner, a placeholder :meth:`str.format` itself cannot parse, or one carrying a
    spec or conversion a name never needs -- refused up front, since ``parse`` does not look inside a
    spec and ``{title:{series}}`` would otherwise pass here and raise at render time."""
    assert location_pattern_problem(pattern) == MALFORMED_PATTERN_PROBLEM
    assert render_location_pattern(pattern, SAMPLE) == ""


@mark.parametrize(
    "pattern",
    ["{} - {title}", "{0} - {title}", "{title} ({series})", "{{{series}}}"],
    ids=["blank", "positional", "unknown", "unknown-in-group"],
)
def test_a_placeholder_outside_the_known_four_is_refused(pattern: str) -> None:
    """A placeholder outside the four known fields is refused, not silently interpolated as empty --
    inside a group as much as outside one."""
    assert location_pattern_problem(pattern) == UNKNOWN_PLACEHOLDER_PROBLEM


@mark.parametrize("pattern", ["{title}{{ - }}", "{title}{{}}"], ids=["text-only", "empty"])
def test_a_group_naming_no_placeholder_is_refused(pattern: str) -> None:
    """A group that depends on nothing could never be left out, so it is a mistake rather than a
    literal."""
    assert location_pattern_problem(pattern) == EMPTY_GROUP_PROBLEM


@mark.parametrize(
    "pattern",
    ["{title}{{ [{year}]", "{title} [{year}]}}", "{{{{{authors} - }}}}", "{{{{{authors} - }} }}"],
    ids=["unclosed", "unopened", "nested-tight", "nested"],
)
def test_a_stray_or_nested_group_marker_is_refused(pattern: str) -> None:
    """Groups do not nest and every ``{{`` needs its ``}}``."""
    assert location_pattern_problem(pattern) == STRAY_GROUP_MARKER_PROBLEM


@mark.parametrize(
    "pattern",
    [
        "{title}",
        "{publisher} - {title}",
        "{title} [{year}]",
        "{authors} - {title}",
        "plain text, no placeholders",
        "{title}{{ [{year}]}}",
        "{{{authors} - }}{title}",
        "{{{authors}}}",
        "{{{publisher}: }}{title}{{ ({year})}}",
    ],
)
def test_a_well_formed_pattern_is_valid(pattern: str) -> None:
    """A pattern naming only known placeholders (or none at all), with every group naming one, is
    usable -- including a group that is nothing but its placeholder."""
    assert location_pattern_problem(pattern) == ""
    assert location_pattern_is_valid(pattern) is True


def test_count_is_refused_by_default_but_accepted_when_declared() -> None:
    """``{count}`` is not one of the base four, so it is refused unless the caller's known-placeholder
    set includes it -- gated on the type declaring ``advertised_count`` (#349).

    **Test steps:**

    * check ``{count}`` against the default (base-four) known placeholders
    * check it again against a set that includes ``count``
    """
    assert location_pattern_problem("{title} ({count})") == UNKNOWN_PLACEHOLDER_PROBLEM
    assert location_pattern_problem("{title} ({count})", KNOWN_PLACEHOLDERS | {"count"}) == ""
    assert location_pattern_is_valid("{title} ({count})", KNOWN_PLACEHOLDERS | {"count"}) is True


# endregion

# region known_placeholders_for


def test_known_placeholders_for_is_the_base_four_without_advertised_count() -> None:
    """A type that declares no count field gets only the base four (#349)."""
    assert known_placeholders_for(("rating", "favorite")) == KNOWN_PLACEHOLDERS


def test_known_placeholders_for_adds_count_when_advertised_count_is_declared() -> None:
    """A type declaring ``advertised_count`` (ReferenceImages) also accepts ``{count}`` (#349)."""
    assert known_placeholders_for(("advertised_count", "current_count")) == KNOWN_PLACEHOLDERS | {"count"}


# endregion

# region render_location_pattern

SAMPLE: dict[str, str] = {"title": "Intro", "publisher": "Acme", "authors": "Jane, John", "year": "2025"}


def test_plain_placeholders_render_as_before() -> None:
    """Outside a group a pattern is an ordinary format string."""
    assert render_location_pattern("{publisher} - {title}", SAMPLE) == "Acme - Intro"


def test_a_group_is_kept_when_every_placeholder_inside_it_has_a_value() -> None:
    """A filled group renders its inner text verbatim, its own whitespace and punctuation included."""
    assert render_location_pattern("{title}{{ [{year}]}}", SAMPLE) == "Intro [2025]"
    assert render_location_pattern("{{{authors} - }}{title}", SAMPLE) == "Jane, John - Intro"


@mark.parametrize("year", ["", "   "], ids=["empty", "blank"])
def test_a_group_drops_out_when_a_placeholder_inside_it_is_empty(year: str) -> None:
    """The group's separator goes with it, which is the whole point: no ``Intro []``."""
    assert render_location_pattern("{title}{{ [{year}]}}", {**SAMPLE, "year": year}) == "Intro"


def test_a_group_needs_every_placeholder_inside_it() -> None:
    """One empty field is enough to drop a group naming two."""
    assert render_location_pattern("{title}{{ ({publisher}, {year})}}", {**SAMPLE, "year": ""}) == "Intro"


def test_a_pattern_whose_groups_all_drop_renders_to_nothing() -> None:
    """An all-optional pattern with nothing to say says nothing, for the caller to skip."""
    assert render_location_pattern("{{{authors}}}", {**SAMPLE, "authors": ""}) == ""


def test_an_invalid_pattern_renders_to_nothing() -> None:
    """Rendering never raises; the row is flagged elsewhere."""
    assert render_location_pattern("{title} ({series})", SAMPLE) == ""


# endregion


# region fallbacks, missing placeholders and a record's values

BARE: dict[str, str] = {"title": "Intro", "publisher": "", "authors": "", "year": ""}


def test_a_fallback_fills_a_blank_placeholder_outside_any_group() -> None:
    """Outside a group, a blank field renders as the fallback; a blank fallback is no fallback.

    **Test steps:**

    * render ``{authors} - {title}`` for a record with no authors, with a fallback for them, then a blank one
    * verify the fallback is used, then the field stays blank
    """
    pattern = LocationPattern("{authors} - {title}")

    assert pattern.render(BARE, {"authors": "Unknown"}) == "Unknown - Intro"
    assert pattern.render(BARE, {"authors": "  "}) == " - Intro"


def test_a_fallback_never_fills_a_group() -> None:
    """A group whose field is blank drops out, a fallback for it notwithstanding; outside it, the fallback is used.

    **Test steps:**

    * render ``{year} {title}{{ [{year}]}}`` for a record with no year, with a fallback for the year
    * verify the plain year takes the fallback and the group is left out
    """
    assert LocationPattern("{year} {title}{{ [{year}]}}").render(BARE, {"year": "undated"}) == "undated Intro"


def test_a_fallback_for_a_field_the_record_fills_is_not_used() -> None:
    """The record's own value wins, and a fallback naming no placeholder is ignored.

    **Test steps:**

    * render ``{title}`` with fallbacks for the title and for a name no record has
    * verify the record's title
    """
    assert LocationPattern("{title}").render(BARE, {"title": "Untitled", "series": "x"}) == "Intro"


def test_missing_names_each_blank_placeholder_outside_a_group_once() -> None:
    """What would render blank outside every group, and only that, once each in pattern order.

    **Test steps:**

    * ask ``{authors}/{publisher}/{authors}{{ [{year}]}}`` what a record with only a title leaves blank
    * verify authors then publisher, the group's year not among them
    * verify a fallback for the publisher takes it off the list, and an invalid pattern names nothing
    """
    pattern = LocationPattern("{authors}/{publisher}/{authors}{{ [{year}]}}")

    assert pattern.missing(BARE) == ("authors", "publisher")
    assert pattern.missing(BARE, {"publisher": "Acme"}) == ("authors",)
    assert not LocationPattern("{series}").missing(BARE)


def test_location_values_spell_a_records_fields_as_placeholders() -> None:
    """Authors join under their names, the year is the release date's first four characters, and an absent date or
    count is empty.

    **Test steps:**

    * build the values of a record with mixed author entries, a date and a count, then of one with neither
    * verify each placeholder's value
    """
    full = location_values("Intro", "Acme", ["Jane", {"name": "John"}], "2025-03-01", "900+")
    empty = location_values("Intro", "", [], None, None)

    assert full == {"title": "Intro", "publisher": "Acme", "authors": "Jane, John", "year": "2025", "count": "900+"}
    assert empty == {"title": "Intro", "publisher": "", "authors": "", "year": "", "count": ""}


# endregion


def test_placeholders_list_every_placeholder_once_in_display_order() -> None:
    """``PLACEHOLDERS`` is the known four and the plugin ones, each once (#637).

    **Test steps:**

    * read ``PLACEHOLDERS``
    * verify it has no repeat, equals the known and plugin names together, and starts with the title
    """
    assert len(set(PLACEHOLDERS)) == len(PLACEHOLDERS)
    assert set(PLACEHOLDERS) == KNOWN_PLACEHOLDERS | PLUGIN_PLACEHOLDERS.keys()
    assert PLACEHOLDERS[0] == "title"
