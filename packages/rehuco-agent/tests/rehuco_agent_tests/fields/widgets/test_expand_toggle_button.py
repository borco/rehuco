"""Tests for ExpandToggleButton: a square checkable toggle with a themed, state-swapped SVG icon."""

from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.expand_toggle_button import ExpandToggleButton


def test_starts_unchecked_with_an_icon(qtbot: QtBot) -> None:
    """A fresh toggle is unchecked (collapsed) and shows a non-null icon.

    **Test steps:**

    * build an ``ExpandToggleButton``
    * verify it is checkable, unchecked, and has an icon
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)

    assert toggle.isCheckable() is True
    assert toggle.isChecked() is False
    assert toggle.icon().isNull() is False


def test_checking_swaps_the_icon(qtbot: QtBot) -> None:
    """Checking (expanding) swaps to the collapse icon, and unchecking swaps back to the expand icon --
    a different icon each time, not the same one restyled.

    **Test steps:**

    * build the toggle and record its collapsed-state icon
    * check it and verify the icon changed
    * uncheck it and verify the icon changes again (back to the expand icon)
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)
    collapsed_icon = toggle.icon().cacheKey()

    toggle.setChecked(True)
    expanded_icon = toggle.icon().cacheKey()
    assert expanded_icon != collapsed_icon

    toggle.setChecked(False)
    assert toggle.icon().cacheKey() != expanded_icon


def test_is_square(qtbot: QtBot) -> None:
    """The toggle is fixed to a square size.

    **Test steps:**

    * build the toggle
    * verify its fixed width equals its fixed height
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)

    assert toggle.width() == toggle.height()
