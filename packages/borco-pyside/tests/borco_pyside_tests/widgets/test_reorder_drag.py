"""Tests for the shadow a list reordered by dragging shows: one place, where the dragged item would land."""

from borco_pyside.widgets import ReorderDrag, drop_slot, paint_drag_ghost
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from pytest import mark


def shown(drag: ReorderDrag, count: int) -> list[int | None]:
    """What a list of ``count`` items shows, place by place; ``None`` is the shadow.

    :param drag: the drag.
    :param count: how many items the list has.
    :returns: each place's item row, or ``None``.
    """
    return [drag.source_at(row) for row in range(count)]


def test_an_idle_drag_shows_every_item_where_it_is() -> None:
    """With nothing dragged, each place shows its own item.

    **Test steps:**

    * build a drag and read what three places show
    * verify they are the items in order, and the drag reads idle
    """
    drag = ReorderDrag()

    assert shown(drag, 3) == [0, 1, 2]
    assert not drag.active
    assert (drag.dragged, drag.slot) == (-1, -1)


def test_the_dragged_items_place_becomes_the_shadow_at_once() -> None:
    """Beginning a drag puts the single shadow where the item was; beginning again changes nothing.

    **Test steps:**

    * begin dragging the middle item, then begin dragging another
    * verify the middle place is the shadow and the second begin was refused
    """
    drag = ReorderDrag()

    assert drag.begin(1)
    assert not drag.begin(2)

    assert shown(drag, 3) == [0, None, 2]
    assert (drag.dragged, drag.slot) == (1, 1)


@mark.parametrize(
    ("dragged", "slot", "expected"),
    [
        (0, 2, [1, 2, None]),
        (0, 1, [1, None, 2]),
        (2, 0, [None, 0, 1]),
        (2, 1, [0, None, 1]),
        (1, 1, [0, None, 2]),
    ],
)
def test_the_other_items_close_up_around_the_one_shadow(dragged: int, slot: int, expected: list[int | None]) -> None:
    """Wherever the shadow stands, the dragged item is shown nowhere and every other item once, in order around it.

    **Test steps:**

    * drag an item and place its shadow
    * verify what each place shows
    """
    drag = ReorderDrag()
    drag.begin(dragged)

    drag.place(slot)

    assert shown(drag, 3) == expected


def test_placing_reports_a_move_and_leaving_goes_back_to_the_own_place() -> None:
    """Placing says whether the shadow moved; leaving the list puts it back where the item was; ending forgets it.

    **Test steps:**

    * place the shadow of a drag elsewhere, again at the same place, then leave and end
    * verify which calls moved it, and the places shown after each
    """
    drag = ReorderDrag()
    assert not drag.place(1)
    drag.begin(0)

    assert drag.place(2)
    assert not drag.place(2)
    assert drag.leave()
    assert shown(drag, 3) == [None, 1, 2]

    drag.end()

    assert shown(drag, 3) == [0, 1, 2]
    assert not drag.active


def test_the_landing_place_is_how_many_other_items_are_above_the_pointer() -> None:
    """The drop rule: count the other items whose middle is above the pointer.

    **Test steps:**

    * ask for the place at heights above, between and below three middles
    * verify 0, 1, 2 and 3
    """
    centers = [10.0, 30.0, 50.0]

    assert [drop_slot(y, centers) for y in (5, 20, 40, 60)] == [0, 1, 2, 3]


def test_the_shadow_is_a_faint_fill_inside_a_highlight_outline() -> None:
    """The shadow is drawn in the palette's highlight: a solid edge and a faint inside.

    **Test steps:**

    * paint a shadow on a white image with a red highlight
    * verify the edge is strongly red and the middle only faintly so
    """
    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("red"))
    painter = QPainter(image)
    paint_drag_ghost(painter, QRectF(0, 0, 40, 20), palette)
    painter.end()

    edge, middle = QColor(image.pixel(20, 0)), QColor(image.pixel(20, 10))
    assert edge.green() < 128
    assert middle.green() > 200
    assert middle.red() > middle.green()
