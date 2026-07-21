"""Tests for the Rating widget: sign-split stylesheet/text styling and value tracking."""

from borco_pyside.widgets import Rating
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot


def internal_label(rating: Rating) -> object:
    """Return the widget's private internal label -- ``Rating`` deliberately exposes no accessor of its own.

    :param rating: the widget to inspect.
    :returns: the internal ``QLabel``.
    """
    return rating._Rating__label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def label_text(rating: Rating) -> str:
    """Read the private internal label's text.

    :param rating: the widget to inspect.
    :returns: the internal label's current text.
    """
    return internal_label(rating).text()  # type: ignore[attr-defined]


def label_font_family(rating: Rating) -> str:
    """Read the private internal label's font family, as resolved by its stylesheet.

    Qt's style engine applies ``setStyleSheet`` lazily on polish (normally triggered by the widget
    being shown), not synchronously -- ``ensurePolished()`` forces that resolution so ``font()``
    reflects it here too, same as it would once the widget is actually on screen.

    :param rating: the widget to inspect.
    :returns: the internal label's current font family.
    """
    label = internal_label(rating)
    label.ensurePolished()  # type: ignore[attr-defined]
    return label.font().family()  # type: ignore[attr-defined]


def label_color(rating: Rating) -> QColor:
    """Read the private internal label's window-text palette color, as resolved by its stylesheet.

    See :func:`label_font_family` for why ``ensurePolished()`` is needed here too.

    :param rating: the widget to inspect.
    :returns: the internal label's current text color.
    """
    label = internal_label(rating)
    label.ensurePolished()  # type: ignore[attr-defined]
    return label.palette().color(label.foregroundRole())  # type: ignore[attr-defined]


def test_rating_starts_empty_by_default(qtbot: QtBot) -> None:
    """A freshly built ``Rating`` with no starting value is unrated (``None``,
    [[field-schema#deferred-items]]) and shows nothing.

    **Test steps:**

    * build a default ``Rating``
    * verify its value is ``None`` and its text is empty
    """
    rating = Rating()
    qtbot.addWidget(rating)

    assert rating.value is None
    assert label_text(rating) == ""


def test_rating_shows_the_starting_value(qtbot: QtBot) -> None:
    """The ``value`` constructor argument renders immediately.

    **Test steps:**

    * build a ``Rating`` with a positive starting value
    * verify the label shows that many positive characters
    """
    rating = Rating(value=3)
    qtbot.addWidget(rating)

    assert label_text(rating) == "★★★"


def test_rating_shows_default_char_for_positive_and_negative(qtbot: QtBot) -> None:
    """Positive and negative values use the default ``★``/``☆`` characters (repeated ``|value|`` times).

    **Test steps:**

    * build a default ``Rating``
    * set a positive value and verify the filled-star text
    * set a negative value and verify the outline-star text
    """
    rating = Rating()
    qtbot.addWidget(rating)

    rating.value = 2
    assert label_text(rating) == "★★"

    rating.value = -3
    assert label_text(rating) == "☆☆☆"


def test_rating_shows_nothing_for_zero(qtbot: QtBot) -> None:
    """A zero value shows nothing, even after showing stars before.

    **Test steps:**

    * build a ``Rating``, set a positive value, then set it back to zero
    * verify the label is empty again
    """
    rating = Rating()
    qtbot.addWidget(rating)

    rating.value = 2
    rating.value = 0

    assert label_text(rating) == ""


def test_rating_shows_nothing_for_none(qtbot: QtBot) -> None:
    """``None`` (unrated, [[field-schema#deferred-items]]) shows nothing, the same as a genuine zero
    -- even after showing stars before.

    **Test steps:**

    * build a ``Rating``, set a positive value, then set it back to ``None``
    * verify the label is empty again
    """
    rating = Rating()
    qtbot.addWidget(rating)

    rating.value = 2
    rating.value = None

    assert label_text(rating) == ""


def test_rating_uses_explicit_positive_and_negative_texts(qtbot: QtBot) -> None:
    """Explicit ``positive_text``/``negative_text`` override the defaults.

    **Test steps:**

    * build a ``Rating`` with custom characters for both signs
    * verify positive and negative values render with the custom characters
    """
    rating = Rating(positive_text="+", negative_text="-", value=2)
    qtbot.addWidget(rating)
    assert label_text(rating) == "++"

    rating.value = -3
    assert label_text(rating) == "---"


def test_rating_applies_explicit_stylesheets_by_sign(qtbot: QtBot) -> None:
    """An explicit ``positive_style``/``negative_style`` is applied for its sign.

    **Test steps:**

    * build a ``Rating`` with distinct positive/negative stylesheets setting the font family
    * verify the internal label's font family matches the stylesheet for each sign
    """
    rating = Rating(positive_style='font-family: "Courier New";', negative_style='font-family: "Times New Roman";')
    qtbot.addWidget(rating)

    rating.value = 1
    assert label_font_family(rating) == "Courier New"

    rating.value = -1
    assert label_font_family(rating) == "Times New Roman"


def test_rating_stylesheet_can_set_color_alongside_font(qtbot: QtBot) -> None:
    """A stylesheet can set color and font-family together, and only affects its own sign.

    **Test steps:**

    * build a ``Rating`` with a negative stylesheet setting both font-family and color
    * verify a negative value picks up both, and a positive value (no stylesheet) does not
    """
    rating = Rating(negative_style='font-family: "Courier New"; color: red;')
    qtbot.addWidget(rating)

    rating.value = -1
    assert label_font_family(rating) == "Courier New"
    assert label_color(rating) == QColor("red")

    rating.value = 1
    assert label_color(rating) != QColor("red")


def test_rating_empty_style_restores_inherited(qtbot: QtBot) -> None:
    """After showing an explicitly-styled value, a value whose sign has no override restores inheritance.

    **Test steps:**

    * build a ``Rating`` with an explicit negative stylesheet but no positive stylesheet
    * set a negative value (applies the explicit style), then a positive value
    * verify the font/color revert to the label's inherited defaults, not the negative style
    """
    default_rating = Rating()
    qtbot.addWidget(default_rating)
    default_font_family = label_font_family(default_rating)
    default_color = label_color(default_rating)

    rating = Rating(negative_style='font-family: "Courier New"; color: red;')
    qtbot.addWidget(rating)

    rating.value = -1
    assert label_font_family(rating) == "Courier New"

    rating.value = 1
    assert label_font_family(rating) == default_font_family
    assert label_color(rating) == default_color


def test_rating_value_property_reflects_current_value(qtbot: QtBot) -> None:
    """The ``value`` property reads back what was last set.

    **Test steps:**

    * build a ``Rating``, set its value
    * verify the ``value`` property reflects it
    """
    rating = Rating()
    qtbot.addWidget(rating)

    rating.value = 4
    assert rating.value == 4


def test_rating_set_value_slot_updates_the_display(qtbot: QtBot) -> None:
    """``set_value`` (the SimpleProperty-synthesized slot) updates the display, usable for signal binding.

    **Test steps:**

    * build a ``Rating``
    * call ``set_value`` directly, as a bound-signal connection would
    * verify the display updated
    """
    rating = Rating()
    qtbot.addWidget(rating)

    rating.set_value(2)  # type: ignore[attr-defined]

    assert label_text(rating) == "★★"
