"""Tests for the seek slider that ticks its bookmarks (#573)."""

from PySide6.QtWidgets import QStyle, QStyleOptionSlider
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.bookmark_slider import BookmarkSlider


def make_slider(qtbot: QtBot) -> BookmarkSlider:
    """A shown horizontal slider over 0 to 100 000.

    :param qtbot: pytest-qt fixture.
    :returns: the slider.
    """
    slider = BookmarkSlider()
    slider.setOrientation(slider.orientation().Horizontal)
    qtbot.addWidget(slider)
    slider.setRange(0, 100_000)
    slider.resize(400, 24)
    slider.show()
    return slider


def test_marks_are_kept_sorted_and_once(qtbot: QtBot) -> None:
    """**Test steps:**

    * mark positions out of order and twice
    * verify they are kept sorted, once each
    """
    slider = make_slider(qtbot)

    slider.set_marks([60_000, 20_000, 20_000])

    assert slider.marks == (20_000, 60_000)


def test_ticks_are_placed_along_the_groove_in_order_and_those_out_of_range_are_not_drawn(qtbot: QtBot) -> None:
    """**Test steps:**

    * mark the start, the middle, the end and a value past the end
    * verify three ticks (each a pair, above and below the groove), increasing, the middle one near the middle
    """
    slider = make_slider(qtbot)
    slider.set_marks([0, 50_000, 100_000, 150_000])

    positions = [rect.x() for rect in slider.tick_rects()[::2]]

    assert len(positions) == 3
    assert positions == sorted(positions)
    assert abs(positions[1] - slider.width() // 2) <= 6


def test_a_slider_with_no_range_has_no_ticks(qtbot: QtBot) -> None:
    """**Test steps:**

    * mark a position on a slider whose range is empty
    * verify no tick is placed
    """
    slider = make_slider(qtbot)
    slider.setRange(0, 0)
    slider.set_marks([10])

    assert not slider.tick_rects()


def test_the_ticks_are_painted_under_the_handle_and_a_repeated_mark_set_changes_nothing(qtbot: QtBot) -> None:
    """**Test steps:**

    * mark positions and grab the slider
    * set the same marks again and verify they are unchanged
    """
    slider = make_slider(qtbot)
    slider.set_marks([20_000, 60_000])

    picture = slider.grab()
    slider.set_marks([60_000, 20_000])

    assert not picture.isNull()
    assert slider.marks == (20_000, 60_000)


def test_each_mark_has_a_tick_above_the_groove_and_one_below_it_and_none_cross_it(qtbot: QtBot) -> None:
    """**Test steps:**

    * mark one position
    * verify two ticks at the same x, the first wholly above the groove and the second wholly below it, both inside
      the widget
    """
    slider = make_slider(qtbot)
    slider.set_marks([50_000])
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    groove = slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, slider
    )

    above, below = slider.tick_rects()

    assert above.x() == below.x()
    assert above.bottom() < groove.top()
    assert below.top() > groove.bottom()
    assert above.top() >= 0
    assert below.bottom() < slider.height()
