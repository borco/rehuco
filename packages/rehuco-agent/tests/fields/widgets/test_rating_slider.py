"""Tests for RatingSlider: the value-widget contract, None-mapping, and echo guard."""

from PySide6.QtWidgets import QSlider
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.rating_slider import RatingSlider


def test_rating_slider_is_a_slider_over_the_given_range(qtbot: QtBot) -> None:
    """A `RatingSlider` is a horizontal ``QSlider`` bounded to the given range.

    **Test steps:**

    * build a slider over a range
    * verify it is a ``QSlider`` with that minimum and maximum
    """
    slider = RatingSlider(-5, 5)
    qtbot.addWidget(slider)

    assert isinstance(slider, QSlider)
    assert (slider.minimum(), slider.maximum()) == (-5, 5)


def test_moving_the_slider_emits_value_changed(qtbot: QtBot) -> None:
    """A user move emits ``value_changed`` with the new integer rating.

    **Test steps:**

    * record ``value_changed`` emissions, then set the slider's value
    * verify the signal fired once with that value
    """
    slider = RatingSlider(-5, 5)
    qtbot.addWidget(slider)
    seen: list[int] = []
    slider.value_changed.connect(seen.append)

    slider.setValue(3)

    assert seen == [3]


def test_set_value_maps_none_to_zero_without_re_emitting(qtbot: QtBot) -> None:
    """``set_value(None)`` shows the unrated position (``0``) without re-emitting ``value_changed``
    (the echo guard).

    **Test steps:**

    * move the slider off zero, then record emissions
    * call ``set_value(None)``
    * verify the slider sits at ``0`` and no ``value_changed`` fired
    """
    slider = RatingSlider(-5, 5)
    qtbot.addWidget(slider)
    slider.setValue(4)
    seen: list[int] = []
    slider.value_changed.connect(seen.append)

    slider.set_value(None)

    assert slider.value() == 0
    assert not seen


def test_set_value_writes_a_concrete_rating_without_re_emitting(qtbot: QtBot) -> None:
    """``set_value`` with an int moves the slider without bouncing ``value_changed`` back out.

    **Test steps:**

    * record emissions, then ``set_value`` a concrete rating
    * verify the slider moved but no ``value_changed`` fired (echo guard)
    """
    slider = RatingSlider(-5, 5)
    qtbot.addWidget(slider)
    seen: list[int] = []
    slider.value_changed.connect(seen.append)

    slider.set_value(-2)

    assert slider.value() == -2
    assert not seen
