"""Tests for `ValueRange` and `ValueSpan`: a store's range as the text a record keeps (#701)."""

from pytest import mark, param, raises
from rehuco_core import ValueRange, ValueSpan


@mark.parametrize(
    ("lower", "upper", "bounds", "expected"),
    [
        param(12, 13, "[)", ValueSpan(12, 12), id="one value, half open"),
        param(1024, 2049, "[)", ValueSpan(1024, 2048), id="a band, half open"),
        param(12, 13, "[]", ValueSpan(12, 13), id="both ends in"),
        param(12, 14, "()", ValueSpan(13, 13), id="both ends out"),
        param(12, 14, "(]", ValueSpan(13, 14), id="lower end out"),
        param(0, 1, "[)", ValueSpan(0, 0), id="zero is a value"),
        param(12, 12, "[)", None, id="an empty range"),
        param(12, 13, "()", None, id="an exclusive range of no whole number"),
        param(13, 12, "[]", None, id="ends the wrong way round"),
        param(-5, 3, "[)", None, id="a negative end"),
        param(None, 13, "[)", None, id="no lower end"),
        param(12, None, "[)", None, id="no upper end"),
        param(12, 13, "[", None, id="one bounds character"),
        param(12, 13, "{}", None, id="not bounds"),
    ],
)
def test_a_stores_bounded_range_is_the_whole_numbers_it_holds(
    lower: int | None, upper: int | None, bounds: str, expected: ValueSpan | None
) -> None:
    """A bounded range reads as the whole numbers it holds, end to end, or as nothing stated (#701).

    **Test steps:**

    * read the span of a range with a lower end, an upper end and its bounds
    * verify the inclusive span, or ``None`` when the range holds no non-negative whole number or is not whole
    """
    assert ValueSpan.from_bounds(lower, upper, bounds) == expected


def test_a_span_refuses_ends_that_are_not_a_range() -> None:
    """A span's ends are non-negative and rise (#701).

    **Test steps:**

    * build a span with a negative end and one with its ends reversed
    * verify both are refused
    """
    with raises(ValueError, match="non-negative"):
        ValueSpan(-1, 3)
    with raises(ValueError, match="non-negative"):
        ValueSpan(5, 4)


@mark.parametrize(
    ("spans", "text"),
    [
        param([ValueSpan(12, 12)], "12", id="one value"),
        param([ValueSpan(1000, 4999)], "1000-4999", id="a band"),
        param([ValueSpan(2048, 2048), ValueSpan(1024, 1024)], "1024,2048", id="values, put in order"),
        param(
            [ValueSpan(40, 60), ValueSpan(12, 12), ValueSpan(12, 12)], "12,40-60", id="a value and a band, no repeat"
        ),
        param([ValueSpan(10, 20), ValueSpan(12, 13)], "10-20,12-13", id="overlapping spans stay as stated"),
    ],
)
def test_a_range_is_written_as_text_in_order(spans: list[ValueSpan], text: str) -> None:
    """A range is its spans, ascending and without repeats, a value alone and a band with a dash (#701).

    **Test steps:**

    * build a range from the spans
    * verify its text, and that reading the text gives the same range back
    """
    built = ValueRange.of(spans)

    assert built is not None
    assert str(built) == text
    assert ValueRange.parse(text) == built


def test_no_spans_is_no_range() -> None:
    """A range with nothing in it does not exist (#701).

    **Test steps:**

    * build a range from no spans
    * verify there is none
    """
    assert ValueRange.of([]) is None


@mark.parametrize(
    ("text", "lower", "upper"),
    [
        param("12", 12, 12, id="one value"),
        param("1-14", 1, 14, id="a band"),
        param("12-13", 12, 13, id="a narrow band"),
        param("10-20", 10, 20, id="a wide band"),
        param(" 1024 , 2048 ", 1024, 2048, id="spaces around values and commas"),
        param("12,40-60", 12, 60, id="the largest end is the last band's"),
        param("5-100,7", 5, 100, id="the largest end is an earlier band's"),
        param("0", 0, 0, id="zero"),
    ],
)
def test_a_range_is_decided_by_its_smallest_and_largest_value(text: str, lower: int, upper: int) -> None:
    """A comparison reads the range's ends: ``< n`` finds a range whose lowest value is below ``n``, ``> n`` one whose
    highest is above it, so ``< 15`` finds ``1-14``, ``12-13``, ``14`` and ``10-20`` alike (#701).

    **Test steps:**

    * read the text of a value, a band and a list
    * verify the smallest and the largest value it holds
    """
    parsed = ValueRange.parse(text)

    assert parsed is not None
    assert (parsed.lower, parsed.upper) == (lower, upper)


@mark.parametrize(
    "text",
    [
        param("", id="empty"),
        param("   ", id="blank"),
        param("many", id="words"),
        param("12-", id="an open band"),
        param("-12", id="a negative number"),
        param("14-12", id="a band running down"),
        param("12,", id="a trailing comma"),
        param("12;14", id="another separator"),
        param("1.5", id="a decimal"),
        param("12 14", id="two numbers with no separator"),
    ],
)
def test_text_that_is_not_a_range_reads_as_none(text: str) -> None:
    """Whatever a person typed that is not a value, a band or a comma list of them is no range, and nothing is
    guessed from it (#701).

    **Test steps:**

    * read each malformed text
    * verify none gives a range
    """
    assert ValueRange.parse(text) is None
