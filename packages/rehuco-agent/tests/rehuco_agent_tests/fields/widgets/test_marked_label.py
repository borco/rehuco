"""Tests for MarkedLabel: a line of text with icons right after it (#649)."""

from borco_pyside.widgets import ElidedLabel
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import MarkedLabel
from rehuco_agent.fields.widgets.place_marker import PLACE_MARKER_ICONS, PlaceMarker

ICONS = [PLACE_MARKER_ICONS[marker] for marker in PlaceMarker]


def text_label(label: MarkedLabel) -> ElidedLabel:
    """Return the text label inside a row -- ``MarkedLabel`` exposes none.

    :param label: the row to inspect.
    :returns: its text label.
    """
    return label._MarkedLabel__label  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_an_icon_follows_the_text_for_each_path_given(qtbot: QtBot) -> None:
    """The icons are drawn in the order given, one per path, and none for an empty list.

    **Test steps:**

    * set a text with all the marker icons and check there are as many
    * set it again with one icon and check the others are gone
    * set it with none and check there is no icon
    """
    label = MarkedLabel()
    qtbot.addWidget(label)

    label.set_text("Tutorials: Jane/Foo", icons=ICONS)
    assert label.icon_count() == len(PlaceMarker)

    label.set_text("Tutorials: Jane/Foo", icons=ICONS[:1])
    assert label.icon_count() == 1

    label.set_text("Tutorials: Jane/Foo")
    assert label.icon_count() == 0


def test_the_text_takes_no_more_than_it_needs(qtbot: QtBot) -> None:
    """The icons sit right after the text, so the text is capped at its own width however wide the row is.

    **Test steps:**

    * show a short text in a row far wider than it
    * verify the text label is no wider than the text and a little slack
    """
    label = MarkedLabel()
    qtbot.addWidget(label)
    label.resize(800, 30)
    label.show()

    label.set_text("Foo", icons=ICONS[:1])

    assert text_label(label).maximumWidth() == label.fontMetrics().horizontalAdvance("Foo") + 2


def test_a_click_on_the_link_is_forwarded_with_its_target(qtbot: QtBot) -> None:
    """The row re-emits its text's link activation, so an owner connects to the row alone.

    **Test steps:**

    * set a text with a link target and activate it on the text label
    * verify the row emitted the target
    """
    label = MarkedLabel()
    qtbot.addWidget(label)
    label.set_text("Foo", href="#")

    with qtbot.waitSignal(label.linkActivated, timeout=1000) as blocker:
        text_label(label).linkActivated.emit("#")

    assert blocker.args == ["#"]


def test_the_tooltip_covers_the_icons_too(qtbot: QtBot) -> None:
    """Hovering an icon reads what hovering the text does.

    **Test steps:**

    * set a text with a tooltip and an icon
    * verify both the row and the text label carry the tooltip
    """
    label = MarkedLabel()
    qtbot.addWidget(label)

    label.set_text("Foo", tooltip="<b>where</b>", icons=ICONS[:1])

    assert label.toolTip() == text_label(label).toolTip() == "<b>where</b>"


def test_the_text_stays_at_the_left_edge_of_a_wide_row(qtbot: QtBot) -> None:
    """A text capped below the row's width is not centred in the row.

    **Test steps:**

    * show a short text with icons in a row far wider than it
    * verify the text label starts at the row's left edge
    """
    label = MarkedLabel()
    qtbot.addWidget(label)
    label.resize(800, 30)
    label.show()

    label.set_text("Foo", icons=ICONS[:2])

    assert text_label(label).x() == 0


def icon_colors(label: MarkedLabel) -> set[tuple[int, int, int]]:
    """Return the colors the first icon is drawn in, its transparent pixels left out.

    :param label: the row to inspect.
    :returns: the (red, green, blue) of every pixel that is fully opaque.
    """
    icons: list[QLabel] = label._MarkedLabel__icons  # type: ignore[attr-defined]  # pylint: disable=protected-access
    image = icons[0].pixmap().toImage()
    pixels = (image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height()))
    return {(pixel.red(), pixel.green(), pixel.blue()) for pixel in pixels if pixel.alpha() == 255}


def test_the_icons_are_drawn_in_the_text_color_and_follow_a_theme_switch(qtbot: QtBot) -> None:
    """An icon drawn as authored is black, which a dark theme hides: it takes the palette's text color instead.

    **Test steps:**

    * give the row a palette whose text is red, and set a text with an icon: the icon is red
    * switch the palette's text to green: the icon is green
    """
    label = MarkedLabel()
    qtbot.addWidget(label)
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 0, 0))
    label.setPalette(palette)

    label.set_text("Foo", icons=ICONS[:1])
    assert icon_colors(label) == {(255, 0, 0)}

    palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 255, 0))
    label.setPalette(palette)
    assert icon_colors(label) == {(0, 255, 0)}


def test_a_disabled_row_draws_its_icons_in_the_disabled_text_color(qtbot: QtBot) -> None:
    """Disabling the row redraws the icons in the palette's disabled text color.

    **Test steps:**

    * give the row a palette whose disabled text is blue, set a text with an icon and disable the row
    * verify the icon is blue
    """
    label = MarkedLabel()
    qtbot.addWidget(label)
    palette = label.palette()
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(0, 0, 255))
    label.setPalette(palette)
    label.set_text("Foo", icons=ICONS[:1])

    label.setEnabled(False)

    assert icon_colors(label) == {(0, 0, 255)}
