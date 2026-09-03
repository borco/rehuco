"""Tests for TextListString: the one comma-separated split/join both comma editors round-trip through."""

from collections.abc import Iterable

from pytest import mark
from rehuco_agent.fields.text_list_string import TextListString


@mark.parametrize(
    ("text", "expected"),
    [
        ("Alice, Bob", ["Alice", "Bob"]),
        ("Alice,Bob", ["Alice", "Bob"]),
        ("  Alice ,  Bob  ", ["Alice", "Bob"]),
        ("Alice", ["Alice"]),
        ("Alice Smith, Bob", ["Alice Smith", "Bob"]),
        ("Bob, Alice, Bob", ["Bob", "Alice", "Bob"]),
    ],
)
def test_text_list_string_split_parses_comma_separated_text(text: str, expected: list[str]) -> None:
    """``split`` breaks on the comma, trims each entry, and preserves order, internal spaces, and duplicates.

    **Test steps:**

    * split a comma-separated string
    * verify each entry is trimmed while its internal spacing and the list's order/duplicates survive
    """
    assert TextListString.split(text) == expected


@mark.parametrize(
    ("text", "expected"),
    [
        ("Alice, Bob, ", ["Alice", "Bob"]),
        ("Alice,, Bob", ["Alice", "Bob"]),
        ("", []),
        ("   ", []),
        (", , ,", []),
    ],
)
def test_text_list_string_split_drops_empty_entries(text: str, expected: list[str]) -> None:
    """``split`` drops entries that are empty or whitespace-only -- a trailing comma, a doubled comma,
    or an all-blank string never yields a blank entry.

    **Test steps:**

    * split text carrying trailing/doubled/all-blank separators
    * verify no empty entry survives
    """
    assert TextListString.split(text) == expected


@mark.parametrize(
    ("items", "expected"),
    [
        (["Alice", "Bob"], "Alice, Bob"),
        (["Alice"], "Alice"),
        ([], ""),
        (["Bob", "Alice", "Bob"], "Bob, Alice, Bob"),
    ],
)
def test_text_list_string_join_renders_comma_space_separated_text(items: list[str], expected: str) -> None:
    """``join`` renders entries separated by a comma **and a space**, preserving order and duplicates.

    **Test steps:**

    * join a list of entries
    * verify the ``, `` separator, with order and duplicates intact
    """
    assert TextListString.join(items) == expected


def test_text_list_string_join_accepts_any_iterable() -> None:
    """``join`` takes any :class:`~collections.abc.Iterable`, not only a list -- a generator joins the same.

    **Test steps:**

    * join a generator of entries
    * verify it renders identically to the list form
    """
    generator: Iterable[str] = (name for name in ["Alice", "Bob"])
    assert TextListString.join(generator) == "Alice, Bob"


def test_text_list_string_join_then_split_round_trips_a_clean_list() -> None:
    """A comma-free, untrimmed list survives ``join`` -> ``split`` unchanged -- the lossless case both
    editors rely on ([[field-schema#authors]], #95).

    **Test steps:**

    * join a clean list, then split the result back
    * verify the original list is recovered exactly
    """
    names = ["Alice", "Bob", "Carol"]
    assert TextListString.split(TextListString.join(names)) == names


def test_text_list_string_split_then_join_normalizes_spacing() -> None:
    """``split`` -> ``join`` collapses a user's own irregular spacing to the canonical ``, `` form.

    **Test steps:**

    * split loosely-spaced text, then join the parsed list
    * verify the round-trip normalizes the separators
    """
    assert TextListString.join(TextListString.split("  Alice ,Bob ,  Carol ")) == "Alice, Bob, Carol"
