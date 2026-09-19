"""The justified-row packing pass: geometry for a whole sequence, computed once (#221).

Rows are packed left to right in sequence order; each row's height is rescaled so its width lands flush
on the right edge, **within a clamp** -- a row whose flush height would fall outside it is left ragged
rather than distorted (a single panorama, a last short row). Masonry was rejected because column
placement depends on every column's current height rather than an item's position, so it cannot
guarantee sequence and images from neighbouring archives mingle at column borders. Row flow only ever
asks "does the next item fit", so order is preserved for free.

Pure: no widget, no Qt type. The view paints from the table this produces and looks up the visible
range through :meth:`PackedLayout.rows_between`.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

PLACEHOLDER_ASPECT: Final = 4 / 3
"""The width/height an item is packed at before its header has been read: the commonest reference
proportion, so a first paint's rows are close to their final shape and the repack that follows a
header's arrival moves little."""


@dataclass(frozen=True, slots=True)
class LayoutItem:
    """One thing to pack: an image of known or not-yet-known proportion, optionally preceded by a banner.

    :ivar aspect: the image's width/height, or ``None`` while unknown.
    :ivar banner: the banner text to put on its own full-width row before this item, or ``None``.
    """

    aspect: float | None = None
    banner: str | None = None


@dataclass(frozen=True, slots=True)
class Row:
    """One packed row.

    :ivar y: the row's top.
    :ivar height: the row's height.
    :ivar first: the index of its first item, or the index the banner precedes when it is a banner.
    :ivar last: the index of its last item (inclusive); equal to ``first`` for a banner row.
    :ivar banner: the banner text when this row is a banner row, else ``None``.
    """

    y: int
    height: int
    first: int
    last: int
    banner: str | None = None


@dataclass(frozen=True, slots=True)
class PackedLayout:
    """The packing pass's output.

    :ivar rects: ``(x, y, w, h)`` per item index.
    :ivar rows: the rows, top to bottom, banner rows included.
    :ivar height: the total height.
    """

    rects: tuple[tuple[int, int, int, int], ...]
    rows: tuple[Row, ...]
    height: int

    def rows_between(self, top: int, bottom: int) -> Sequence[Row]:
        """The rows intersecting the vertical span ``[top, bottom)`` -- a viewport's.

        :param top: the span's top.
        :param bottom: the span's bottom.
        :returns: the rows, in order.
        """
        tops = [row.y for row in self.rows]
        first = max(0, bisect_right(tops, top) - 1)
        last = bisect_right(tops, max(top, bottom - 1))
        return self.rows[first:last]


def pack_rows(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    items: Sequence[LayoutItem],
    width: int,
    min_height: int,
    max_height: int,
    spacing: int = 4,
    banner_height: int = 24,
) -> PackedLayout:
    """Pack ``items`` into justified rows ``width`` wide, each row's height clamped to
    ``[min_height, max_height]``.

    Greedy: items are added to the open row until its flush height -- the height at which the row's
    widths sum to ``width`` -- drops to ``max_height`` or below. If that flush height is at least
    ``min_height`` the row is flush at it; otherwise the last item did not fit and the row is closed
    without it, **ragged** (its flush height with one item fewer was above the clamp). A trailing row
    that never reached ``max_height`` is ragged too. A ragged row takes **the height of the last flush
    row before it**, so a short last row reads as one more row of the same grid rather than a taller
    one -- and ``max_height`` only when no flush row precedes it. A lone item whose own flush height
    is under ``min_height`` -- a panorama -- fits the width at that height, since a single item has no
    ragged edge to be left with. A banner closes the open row and takes a full-width row of
    ``banner_height`` of its own.

    :param items: what to pack, in sequence order.
    :param width: the available width.
    :param min_height: the shortest flush row.
    :param max_height: the tallest flush row.
    :param spacing: the gap between items, and between rows.
    :param banner_height: a banner row's height.
    :returns: the layout; sequence is preserved by construction.
    """
    max_height = max(max_height, 1)
    min_height = max(min(min_height, max_height), 1)
    rects: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * len(items)
    rows: list[Row] = []
    y = 0
    open_row: list[tuple[int, float]] = []
    # what a row that cannot be flush is closed at: the last flush row's height once there is one
    ragged_height = max_height

    def flush_height(row: list[tuple[int, float]]) -> float:
        aspects = sum(aspect for _, aspect in row)
        return (width - spacing * (len(row) - 1)) / aspects if aspects > 0 else max_height

    def close_row(row: list[tuple[int, float]], height: int, *, flush: bool) -> None:
        nonlocal y, ragged_height
        if not row:
            return
        x = 0
        for index, aspect in row:
            rects[index] = (x, y, max(1, round(height * aspect)), height)
            x += rects[index][2] + spacing
        if flush:
            # the last item absorbs the rounding, so a flush row lands exactly on the edge
            last_index, _ = row[-1]
            last_x = rects[last_index][0]
            rects[last_index] = (last_x, y, max(1, width - last_x), height)
            if height >= min_height:
                # a grid row's height, which a later ragged row copies -- not a lone panorama's,
                # which fits the width below the clamp and is no row height at all
                ragged_height = height
        rows.append(Row(y, height, row[0][0], row[-1][0]))
        y += height + spacing

    def close_ragged(row: list[tuple[int, float]]) -> None:
        close_row(row, ragged_height, flush=False)

    def settle() -> None:
        """Close the open row if its flush height has come inside (or under) the clamp."""
        nonlocal open_row
        flush = flush_height(open_row)
        if flush > max_height:
            return
        if flush >= min_height or len(open_row) == 1:
            # inside the clamp: flush. A lone item under it -- a panorama -- fits the width at
            # whatever height that takes, since a single item has no ragged edge to be left with
            close_row(open_row, max(1, round(flush)), flush=True)
            open_row = []
            return
        # the item just added pushed the row under the clamp: close the row without it, ragged (its
        # flush height with one item fewer was above the clamp), then judge that item on its own
        last = open_row.pop()
        close_ragged(open_row)
        open_row = [last]
        settle()

    for index, item in enumerate(items):
        if item.banner is not None:
            close_ragged(open_row)
            open_row = []
            rows.append(Row(y, banner_height, index, index, item.banner))
            y += banner_height + spacing
        aspect = item.aspect if item.aspect is not None and item.aspect > 0 else PLACEHOLDER_ASPECT
        open_row.append((index, aspect))
        settle()
    close_ragged(open_row)
    total = max(0, y - spacing) if rows else 0
    return PackedLayout(tuple(rects), tuple(rows), total)
