"""Tests for a location replacement rule: when one is usable, and how a table of them applies (#350, #577)."""

from rehuco_core import (
    EMPTY_TEXT_PROBLEM,
    INVALID_REGEX_PROBLEM,
    ReplacementRule,
    apply_location_replacements,
    rule_problem,
)

# region rule_problem


def test_a_rule_with_text_is_fine() -> None:
    """A rule naming something to look for is usable."""
    assert rule_problem(ReplacementRule(": ", " - ")) == ""


def test_a_rule_with_no_text_is_a_problem() -> None:
    """An empty text cell would match everywhere, so it is flagged rather than acted on."""
    assert rule_problem(ReplacementRule("", " - ")) == EMPTY_TEXT_PROBLEM


def test_an_empty_replacement_is_fine() -> None:
    """Deleting the matched text outright is a legitimate rule, not a mistake."""
    assert rule_problem(ReplacementRule(":", "")) == ""


def test_a_well_formed_regex_is_fine() -> None:
    """A regex rule that compiles is usable."""
    assert rule_problem(ReplacementRule(r" *\| *", " - ", is_regex=True)) == ""


def test_an_unparsable_regex_is_a_problem() -> None:
    """An unbalanced group is refused up front rather than raising at replace time."""
    assert rule_problem(ReplacementRule("(", "-", is_regex=True)) == INVALID_REGEX_PROBLEM


def test_the_same_text_is_fine_as_a_literal_but_not_as_a_regex() -> None:
    """Whether text is a problem depends on the checkbox, not on the text alone."""
    assert rule_problem(ReplacementRule("(", "-", is_regex=False)) == ""


# endregion

# region apply_location_replacements


def test_a_later_rule_sees_what_an_earlier_one_left_behind() -> None:
    """Rules run left to right across the whole table, not independently against the original text."""
    rules = (ReplacementRule("a", "b"), ReplacementRule("b", "c"))

    assert apply_location_replacements("a", rules) == "c"


def test_an_empty_text_rule_is_skipped_rather_than_inserted_everywhere() -> None:
    """Replacing an empty string would insert the replacement between every character -- skipped instead."""
    assert apply_location_replacements("abc", (ReplacementRule("", "-"),)) == "abc"


def test_no_rules_returns_the_text_unchanged() -> None:
    """An empty rule table is a no-op, not an error."""
    assert apply_location_replacements("Foo: Bar", ()) == "Foo: Bar"


def test_a_regex_rule_collapses_the_spaces_it_matches() -> None:
    """The whole point of the shipped pipe rule: a regex can consume its own surrounding whitespace, so
    ``" | "`` becomes one `` - ``, not two doubled spaces either side of a literal replacement."""
    rule = ReplacementRule(r" *\| *", " - ", is_regex=True)

    assert apply_location_replacements("Foo | Bar", (rule,)) == "Foo - Bar"
    assert apply_location_replacements("Foo|Bar", (rule,)) == "Foo - Bar"


def test_a_regex_rules_replacement_may_use_backreferences() -> None:
    """Under ``is_regex``, ``replacement`` is `re.sub`'s own replacement string, backreferences included."""
    rule = ReplacementRule(r"(\w+)_(\w+)", r"\2 \1", is_regex=True)

    assert apply_location_replacements("Vol_2", (rule,)) == "2 Vol"


def test_an_unparsable_regex_rule_is_skipped() -> None:
    """A row `rule_problem` flags never reaches ``re.sub``, so it cannot raise."""
    rule = ReplacementRule("(", "-", is_regex=True)

    assert apply_location_replacements("(abc", (rule,)) == "(abc"


# endregion
