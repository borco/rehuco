"""Tests for the ``.rehu``/``.tc`` parse sanity caps (#88, [[data-model#write-integrity]])."""

from rehuco_core.rehu_parse_limits import (
    MAX_COLLECTION_LENGTH,
    MAX_FILE_BYTES,
    MAX_JSON_NESTING_DEPTH,
    MAX_STRING_LENGTH,
    excessive_entry_reason,
    excessive_nesting_reason,
    oversized_file_reason,
)

# region oversized_file_reason


def test_oversized_file_reason_accepts_a_size_at_the_cap() -> None:
    """A file exactly at :data:`MAX_FILE_BYTES` is within bounds."""
    assert oversized_file_reason(MAX_FILE_BYTES) is None


def test_oversized_file_reason_refuses_a_size_past_the_cap() -> None:
    """A file one byte over :data:`MAX_FILE_BYTES` is refused, naming both numbers."""
    reason = oversized_file_reason(MAX_FILE_BYTES + 1)
    assert reason is not None
    assert str(MAX_FILE_BYTES + 1) in reason
    assert str(MAX_FILE_BYTES) in reason


# endregion


# region excessive_nesting_reason


def test_excessive_nesting_reason_accepts_depth_at_the_cap() -> None:
    """Nesting exactly :data:`MAX_JSON_NESTING_DEPTH` deep is within bounds."""
    text = "{" * MAX_JSON_NESTING_DEPTH + "}" * MAX_JSON_NESTING_DEPTH
    assert excessive_nesting_reason(text) is None


def test_excessive_nesting_reason_refuses_depth_past_the_cap() -> None:
    """Nesting one level past :data:`MAX_JSON_NESTING_DEPTH` is refused."""
    text = "{" * (MAX_JSON_NESTING_DEPTH + 1) + "}" * (MAX_JSON_NESTING_DEPTH + 1)
    reason = excessive_nesting_reason(text)
    assert reason is not None
    assert str(MAX_JSON_NESTING_DEPTH + 1) in reason


def test_excessive_nesting_reason_ignores_braces_inside_strings() -> None:
    """A brace inside a JSON string literal is ordinary text, not structure -- a naive brace count
    would refuse this, but it must not.
    """
    text = '{"description": "' + "{" * (MAX_JSON_NESTING_DEPTH * 2) + '"}'
    assert excessive_nesting_reason(text) is None


def test_excessive_nesting_reason_handles_an_escaped_quote_inside_a_string() -> None:
    """A ``\\"`` inside a string does not end the string early, so a brace right after it still counts
    as inside the string rather than as structure.
    """
    text = '{"title": "a \\" ' + "{" * (MAX_JSON_NESTING_DEPTH * 2) + '"}'
    assert excessive_nesting_reason(text) is None


# endregion


# region excessive_entry_reason


def test_excessive_entry_reason_accepts_a_list_at_the_cap() -> None:
    """A list with exactly :data:`MAX_COLLECTION_LENGTH` entries is within bounds."""
    assert excessive_entry_reason({"sources": ["x"] * MAX_COLLECTION_LENGTH}) is None


def test_excessive_entry_reason_refuses_a_list_past_the_cap() -> None:
    """A list one entry past :data:`MAX_COLLECTION_LENGTH` is refused."""
    reason = excessive_entry_reason({"sources": ["x"] * (MAX_COLLECTION_LENGTH + 1)})
    assert reason is not None
    assert "list" in reason


def test_excessive_entry_reason_refuses_an_object_past_the_cap() -> None:
    """A ``dict`` with more than :data:`MAX_COLLECTION_LENGTH` keys is refused, not just a list."""
    reason = excessive_entry_reason({str(i): i for i in range(MAX_COLLECTION_LENGTH + 1)})
    assert reason is not None
    assert "object" in reason


def test_excessive_entry_reason_refuses_a_deeply_nested_offender() -> None:
    """The walk is not limited to the top level -- an offending collection nested inside otherwise
    ordinary structure is still caught.
    """
    reason = excessive_entry_reason({"core": {"sources": ["x"] * (MAX_COLLECTION_LENGTH + 1)}})
    assert reason is not None


def test_excessive_entry_reason_accepts_a_string_at_the_cap() -> None:
    """A string with exactly :data:`MAX_STRING_LENGTH` characters is within bounds."""
    assert excessive_entry_reason({"description": "x" * MAX_STRING_LENGTH}) is None


def test_excessive_entry_reason_refuses_a_string_past_the_cap() -> None:
    """A string one character past :data:`MAX_STRING_LENGTH` is refused."""
    reason = excessive_entry_reason({"description": "x" * (MAX_STRING_LENGTH + 1)})
    assert reason is not None
    assert "string" in reason


def test_excessive_entry_reason_accepts_ordinary_data() -> None:
    """A small, ordinary payload passes untouched."""
    assert excessive_entry_reason({"core": {"sources": [{"title": "x"}], "authors": ["a", "b"]}}) is None


def test_excessive_entry_reason_refuses_a_mapping_key_past_the_cap() -> None:
    """A mapping *key* is a string like any other -- a single giant key must not slip past the string
    cap just because it is not a value.
    """
    reason = excessive_entry_reason({"k" * (MAX_STRING_LENGTH + 1): 1})
    assert reason is not None
    assert "string" in reason


def test_excessive_entry_reason_walks_a_shared_dag_in_linear_time() -> None:
    """An aliased YAML payload parses into a shared DAG whose *logical* entry count is exponential in
    its byte size (the billion-laughs shape); the walk must visit each physical container once, or the
    check itself becomes the wedge it exists to prevent.

    Built directly as shared references rather than through ``yaml.safe_load``, so this asserts on the
    walk alone. 40 levels of 10-way sharing is ~10^40 logical entries -- a tree walk would outlive the
    universe, a per-container walk finishes instantly.
    """
    layer: list[object] = ["x"] * 10
    for _ in range(40):
        layer = [layer] * 10
    assert excessive_entry_reason({"a": layer}) is None


def test_excessive_entry_reason_terminates_on_a_cyclic_structure() -> None:
    """A self-referencing YAML anchor (``a: &x {b: *x}``) parses into a genuine cycle; the walk must
    terminate on it rather than looping forever on a fifteen-byte file.
    """
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    assert excessive_entry_reason({"a": cyclic, "b": [cyclic]}) is None


# endregion
