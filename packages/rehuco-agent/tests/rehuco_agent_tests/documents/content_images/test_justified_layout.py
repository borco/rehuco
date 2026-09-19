"""Tests for the justified-row packing pass (#221)."""

from typing import Final

from rehuco_agent.documents.content_images.justified_layout import (
    PLACEHOLDER_ASPECT,
    LayoutItem,
    PackedLayout,
    pack_rows,
)

WIDTH: Final = 1000
MIN_HEIGHT: Final = 100
MAX_HEIGHT: Final = 200
SPACING: Final = 0
BANNER_HEIGHT: Final = 20


def pack(items: list[LayoutItem], width: int = WIDTH) -> PackedLayout:
    """Pack ``items`` under the module's clamp with no spacing, so widths are exact.

    :param items: what to pack.
    :param width: the available width.
    :returns: the layout.
    """
    return pack_rows(items, width, MIN_HEIGHT, MAX_HEIGHT, SPACING, BANNER_HEIGHT)


def test_a_row_whose_flush_height_is_inside_the_clamp_lands_flush() -> None:
    """Three 2:1 images over 1000 px flush at 167 px, inside ``[100, 200]``: the row closes there and
    is rescaled to land exactly on the right edge.

    **Test steps:**

    * pack three 2:1 items
    * verify one row at 167 px whose last item ends at the width
    """
    layout = pack([LayoutItem(2.0)] * 3)

    assert len(layout.rows) == 1
    assert layout.rows[0].height == 167
    assert [rect[1] for rect in layout.rects] == [0, 0, 0]
    last_x, _, last_width, _ = layout.rects[2]
    assert last_x + last_width == WIDTH


def test_a_row_closes_as_soon_as_its_flush_height_comes_inside_the_clamp() -> None:
    """Rows are greedy: the fourth 2:1 image is not squeezed into a row that already fits, it starts
    the next one.

    **Test steps:**

    * pack four 2:1 items
    * verify two rows -- three flush at 167 px, then one alone
    """
    layout = pack([LayoutItem(2.0)] * 4)

    assert [(row.first, row.last, row.height) for row in layout.rows] == [(0, 2, 167), (3, 3, 167)]


def test_a_ragged_row_takes_the_height_of_the_flush_row_above_it() -> None:
    """A short last row reads as one more row of the same grid, not a taller one: it is closed at the
    last flush row's height rather than the clamp's maximum.

    **Test steps:**

    * pack three 2:1 items (flush at 167 px) and one 1:1 item that closes ragged
    * verify the ragged row is 167 px tall and its item 167 px wide
    """
    layout = pack([LayoutItem(2.0)] * 3 + [LayoutItem(1.0)])

    assert layout.rows[1].height == 167
    assert layout.rects[3] == (0, 167 + SPACING, 167, 167)


def test_a_row_is_left_ragged_rather_than_squeezed_under_the_clamp() -> None:
    """A 4:1 image alone flushes at 250 px, above the clamp; adding an 8:1 one would flush the pair at
    83 px, under it. The pair is never squeezed: the first closes ragged at the maximum, and the
    second is judged on its own -- flush at 125 px.

    **Test steps:**

    * pack a 4:1 then an 8:1 item
    * verify the first row is ragged at 200 px, short of the edge, and the second flush at 125 px
    """
    layout = pack([LayoutItem(4.0), LayoutItem(8.0)])

    assert [(row.first, row.last, row.height) for row in layout.rows] == [(0, 0, MAX_HEIGHT), (1, 1, 125)]
    assert layout.rects[0] == (0, 0, 800, MAX_HEIGHT)
    assert layout.rects[1] == (0, MAX_HEIGHT + SPACING, WIDTH, 125)


def test_a_trailing_row_is_ragged_at_the_maximum() -> None:
    """A ragged row with no flush row before it stays at the maximum -- never stretched.

    **Test steps:**

    * pack a single 1:1 item, which flushes at 1000 px
    * verify it sits at the maximum height and the width its aspect gives it
    """
    layout = pack([LayoutItem(1.0)])

    assert layout.rows[0].height == MAX_HEIGHT
    assert layout.rects[0] == (0, 0, MAX_HEIGHT, MAX_HEIGHT)


def test_a_panoramas_height_is_not_what_a_later_ragged_row_copies() -> None:
    """A lone panorama fits the width below the clamp; a ragged row after it takes the last *grid*
    row's height, not the panorama's.

    **Test steps:**

    * pack three 2:1 items (flush at 167 px), a 20:1 panorama (50 px), then a lone 1:1 item
    * verify the last row is 167 px, not 50
    """
    layout = pack([LayoutItem(2.0)] * 3 + [LayoutItem(20.0), LayoutItem(1.0)])

    assert [row.height for row in layout.rows] == [167, 50, 167]


def test_a_lone_panorama_fits_the_width_under_the_minimum() -> None:
    """One 20:1 image would flush at 50 px, under the minimum: alone, it fits the width at that height,
    since a single item has no ragged edge to be left with.

    **Test steps:**

    * pack a 20:1 item
    * verify its rect spans the width at 50 px
    """
    layout = pack([LayoutItem(20.0)])

    assert layout.rects[0] == (0, 0, WIDTH, 50)


def test_a_banner_takes_a_full_width_row_and_forces_a_break() -> None:
    """A banner closes the open row ragged, takes a row of its own, and the next item starts fresh.

    **Test steps:**

    * pack two 2:1 items, the second carrying a banner
    * verify three rows: item, banner, item -- and the banner row carries its text
    """
    layout = pack([LayoutItem(2.0), LayoutItem(2.0, "[pack.zip]")])

    assert [row.banner for row in layout.rows] == [None, "[pack.zip]", None]
    assert layout.rows[1].height == BANNER_HEIGHT
    assert layout.rects[1][1] == layout.rows[1].y + BANNER_HEIGHT + SPACING
    assert layout.height == layout.rows[2].y + layout.rows[2].height


def test_a_hidden_item_keeps_its_banner_and_loses_its_cell() -> None:
    """A collapsed group's images are left out of the rows while the banner still takes its row; a
    hidden item's rect is empty and the next visible item starts fresh under the banner.

    **Test steps:**

    * pack a bannered hidden item, another hidden one, then a bannered visible one
    * verify two banner rows, one image row, and an empty rect for each hidden item
    """
    layout = pack([LayoutItem(2.0, "a", hidden=True), LayoutItem(2.0, hidden=True), LayoutItem(2.0, "b")])

    assert [row.banner for row in layout.rows] == ["a", "b", None]
    assert layout.rects[0] == (0, 0, 0, 0)
    assert layout.rects[1] == (0, 0, 0, 0)
    assert layout.rects[2][1] == 2 * (BANNER_HEIGHT + SPACING)


def test_sequence_is_preserved_in_every_output() -> None:
    """Items are placed left to right, top to bottom, in the order given -- never reordered to pack
    better.

    **Test steps:**

    * pack a mix of wide and tall items
    * verify each rect starts at or after the previous one in reading order
    """
    layout = pack([LayoutItem(aspect) for aspect in (3.0, 0.5, 2.0, 1.0, 4.0, 0.7, 1.5, 2.5)])

    positions = [(y, x) for x, y, _, _ in layout.rects]
    assert positions == sorted(positions)


def test_an_unknown_aspect_packs_at_the_placeholder() -> None:
    """An item whose header is unread packs at the placeholder proportion, so a first paint lays out
    rows before a single header has been read.

    **Test steps:**

    * pack one unknown item
    * verify its width is the placeholder times its height
    """
    layout = pack([LayoutItem(None)])

    _, _, width, height = layout.rects[0]
    assert width == round(height * PLACEHOLDER_ASPECT)


def test_rows_between_returns_the_rows_a_viewport_touches() -> None:
    """The visible-range lookup returns exactly the rows intersecting a vertical span.

    **Test steps:**

    * pack nine 2:1 items (three rows of three at 167 px) and ask for the span 170-340
    * verify the second and third rows come back
    """
    layout = pack([LayoutItem(2.0)] * 9)
    assert [row.y for row in layout.rows] == [0, 167, 334]

    assert [row.first for row in layout.rows_between(170, 340)] == [3, 6]
    assert [row.first for row in layout.rows_between(0, 1)] == [0]
    assert list(layout.rows_between(10_000, 10_100)) == [layout.rows[-1]]


def test_an_empty_sequence_packs_to_nothing() -> None:
    """No items: no rows, no height, nothing raised.

    **Test steps:**

    * pack nothing
    * verify the empty layout
    """
    layout = pack([])

    assert layout == PackedLayout((), (), 0)
