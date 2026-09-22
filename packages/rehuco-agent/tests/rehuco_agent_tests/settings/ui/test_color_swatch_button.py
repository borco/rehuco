"""Tests for ColorSwatchButton: a push button that is its own colour swatch (#221, #342)."""

from PySide6.QtGui import QColor
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.ui.color_swatch_button import ColorSwatchButton


def test_set_color_normalizes_and_shows_the_hex_text(qtbot: QtBot) -> None:
    """The button's text is the normalized ``#rrggbb`` form, whatever `QColor`-acceptable string is given.

    **Test steps:**

    * set a named colour
    * verify the text and :meth:`color` both read back the normalized hex form
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("swatch")

    button.set_color("orange")

    assert button.color() == QColor("orange").name()
    assert button.text() == QColor("orange").name()


def test_the_stylesheet_rule_is_scoped_to_this_buttons_own_objectname(qtbot: QtBot) -> None:
    """A bare ``QPushButton {...}`` type selector is global the moment any widget sets one -- Qt's
    stylesheet-aware style then paints *every* push button in the app with it, including a dialog
    this button opens. Scoping the rule to an ID selector (``QPushButton#name``) is what keeps it to
    this one widget.

    **Test steps:**

    * name the button and set a colour
    * verify the stylesheet names this button's own objectName, not a bare ``QPushButton`` selector
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("lightbox_backdrop_button")

    button.set_color("#336699")

    assert button.styleSheet() == "QPushButton#lightbox_backdrop_button { background-color: #336699; color: #ffffff; }"
    assert "QPushButton {" not in button.styleSheet()


def test_a_button_with_no_objectname_yet_gets_no_stylesheet(qtbot: QtBot) -> None:
    """Before ``uic`` assigns an objectName (during this class's own ``__init__``), there is no name
    to scope an ID selector to -- so no stylesheet is set at all, rather than falling back to the
    leaky type selector this class exists to avoid.

    **Test steps:**

    * build a button and immediately set a colour, with no objectName given
    * verify the text is shown but the stylesheet stays empty
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)

    button.set_color("#336699")

    assert button.text() == "#336699"
    assert button.styleSheet() == ""


def test_the_text_color_flips_for_readability(qtbot: QtBot) -> None:
    """A dark swatch gets white text, a light one black, so the hex name stays legible either way.

    **Test steps:**

    * set a very dark colour, then a very light one
    * verify the stylesheet's text colour follows
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("swatch")

    button.set_color("#000000")
    assert "color: #ffffff" in button.styleSheet()

    button.set_color("#ffffff")
    assert "color: #000000" in button.styleSheet()


def test_clicking_opens_the_picker_on_the_staged_colour_and_stages_what_it_returns(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Clicking asks the colour dialog, seeded with the current colour, and stages whatever valid
    colour it returns.

    **Test steps:**

    * make the dialog return a colour, click the button
    * verify the dialog was opened on the staged colour and the button now shows the chosen one
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("swatch")
    button.set_color("#111111")
    picker = mocker.patch("rehuco_agent.settings.ui.color_swatch_button.QColorDialog.getColor")
    picker.return_value = QColor("#336699")

    button.click()

    assert picker.call_args.args[0] == QColor("#111111")
    assert button.color() == "#336699"


def test_a_cancelled_pick_leaves_the_colour_unchanged(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Cancelling the dialog (an invalid returned colour) stages nothing.

    **Test steps:**

    * make the dialog return an invalid colour, click the button
    * verify the colour is unchanged
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("swatch")
    button.set_color("#111111")
    mocker.patch("rehuco_agent.settings.ui.color_swatch_button.QColorDialog.getColor", return_value=QColor())

    button.click()

    assert button.color() == "#111111"


def test_settings_value_and_set_settings_value_round_trip(qtbot: QtBot) -> None:
    """The `ValueControl` half of the seam: what one reads, the other restores (#342).

    **Test steps:**

    * set a colour, read it back through ``settings_value``
    * write a different value through ``set_settings_value``
    * verify the button shows what was written
    """
    button = ColorSwatchButton()
    qtbot.addWidget(button)
    button.setObjectName("swatch")
    button.set_color("#336699")

    assert button.settings_value() == "#336699"

    button.set_settings_value("#aabbcc")

    assert button.color() == "#aabbcc"
    assert button.text() == "#aabbcc"
