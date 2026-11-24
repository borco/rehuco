"""A count a store states as a range, and the text it is stored as ([[assets#block]], #701).

A store gives some figures as a band, not a number: Fab's triangle count of a format is ``[12, 13)``, a texture's
longest side ``[1024, 2049)``. The record keeps them as the text a person reads at a glance and types by hand,
**inclusive** at both ends: ``12``, ``1024-2048``, and several values or bands apart as a comma list, ``12,40-60``.
Text is what a ``.rehu`` file holds; this module is the one place that writes it and reads it back, so a search can
compare a field (``advertised_triangles<15``) by the bounds of whatever the user typed or a scan wrote, and match
when **any** value of the range does.

A value is a non-negative whole number of at most :data:`MAX_DIGITS` digits: a triangle count, a side in pixels.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

BAND_SEPARATOR: Final = "-"
"""What sits between the two ends of a band, ``1024-2048``."""

LIST_SEPARATOR: Final = ","
"""What sits between the values and bands of a list, ``12,40-60``."""

MAX_DIGITS: Final = 18
"""The most digits a value has: a count a store states is far below it, and a longer number would not fit the cache's
integer columns (SQLite's reach nine quintillion), where one such text would stop a whole root's scan."""

SPAN_PATTERN: Final = re.compile(rf"(\d{{1,{MAX_DIGITS}}})(?:{BAND_SEPARATOR}(\d{{1,{MAX_DIGITS}}}))?")
"""One value or one band, the digits of each end captured."""


@dataclass(frozen=True, order=True)
class ValueSpan:
    """One value, or the band between two, both ends included.

    :param lower: the smallest value.
    :param upper: the largest; the same as ``lower`` for a single value.
    :raises ValueError: an end is negative, or ``lower`` is above ``upper``.
    """

    lower: int
    upper: int

    def __post_init__(self) -> None:
        if self.lower < 0 or self.upper < self.lower:
            raise ValueError(f"Not a range of non-negative whole numbers: {self.lower} to {self.upper}")

    def __str__(self) -> str:
        return str(self.lower) if self.lower == self.upper else f"{self.lower}{BAND_SEPARATOR}{self.upper}"

    @staticmethod
    def from_bounds(lower: int | None, upper: int | None, bounds: str = "[)") -> ValueSpan | None:
        """The span a store's bounded range holds, as a database range type states it.

        :param lower: the range's lower end; ``None`` when the store states none.
        :param upper: the range's upper end; ``None`` when the store states none.
        :param bounds: whether each end is in the range: ``[`` or ``(`` for the lower, ``]`` or ``)`` for the upper;
            Fab's are ``[)``.
        :returns: the span; ``None`` for a range with an end missing, one that holds no whole number, or bounds that
            are not two of those four characters.
        """
        if lower is None or upper is None or len(bounds) != 2 or bounds[0] not in "[(" or bounds[1] not in "])":
            return None
        first = lower if bounds[0] == "[" else lower + 1
        last = upper if bounds[1] == "]" else upper - 1
        return ValueSpan(first, last) if 0 <= first <= last else None


@dataclass(frozen=True)
class ValueRange:
    """The values a field holds: one or more spans, in ascending order, none twice.

    Built by :meth:`of` or :meth:`parse`, which put them in that order; its text is :meth:`__str__`.

    :param spans: the spans, ascending.
    """

    spans: tuple[ValueSpan, ...]

    @property
    def lower(self) -> int:
        """The smallest value of the range -- what ``field < n`` is decided by.

        :returns: the lower end of its first span.
        """
        return self.spans[0].lower

    @property
    def upper(self) -> int:
        """The largest value of the range -- what ``field > n`` is decided by.

        :returns: the upper end of its last span.
        """
        return max(span.upper for span in self.spans)

    def __str__(self) -> str:
        return LIST_SEPARATOR.join(str(span) for span in self.spans)

    @staticmethod
    def of(spans: Iterable[ValueSpan]) -> ValueRange | None:
        """The range holding ``spans``, put in order and without repeats.

        :param spans: the spans, in any order.
        :returns: the range; ``None`` when there are none.
        """
        ordered = tuple(sorted(set(spans)))
        return ValueRange(ordered) if ordered else None

    @staticmethod
    def bounds(text: str | None) -> tuple[int | None, int | None]:
        """The smallest and the largest value of a stored text, as a search compares a field by them.

        :param text: a range field's stored text, or ``None``.
        :returns: its lower and upper bound; both ``None`` for no text or text that is no range.
        """
        found = None if text is None else ValueRange.parse(text)
        return (None, None) if found is None else (found.lower, found.upper)

    @staticmethod
    def parse(text: str) -> ValueRange | None:
        """Read a range from the text :meth:`__str__` writes, or one typed by hand in that form.

        :param text: the text, spaces around a value or a comma allowed.
        :returns: the range; ``None`` for empty text or any part that is not a value or a band whose ends rise.
        """
        spans: list[ValueSpan] = []
        for part in text.split(LIST_SEPARATOR):
            found = SPAN_PATTERN.fullmatch(part.strip())
            if found is None:
                return None
            lower = int(found.group(1))
            upper = lower if found.group(2) is None else int(found.group(2))
            if upper < lower:
                return None
            spans.append(ValueSpan(lower, upper))
        return ValueRange.of(spans)
