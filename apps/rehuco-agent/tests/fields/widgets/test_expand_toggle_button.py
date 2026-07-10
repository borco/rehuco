"""Tests for ExpandToggleButton: a square checkable [+]/[-] Phosphor toggle."""

from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.expand_toggle_button import ExpandToggleButton
from rehuco_agent.glyphs import COLLAPSE_ACTION_GLYPH, EXPAND_ACTION_GLYPH


def test_starts_unchecked_showing_the_expand_glyph(qtbot: QtBot) -> None:
    """A fresh toggle is unchecked (collapsed) and shows the expand glyph.

    **Test steps:**

    * build an ``ExpandToggleButton``
    * verify it is checkable, unchecked, and shows the expand glyph
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)

    assert toggle.isCheckable() is True
    assert toggle.isChecked() is False
    assert toggle.text() == EXPAND_ACTION_GLYPH.codepoint


def test_checking_swaps_to_the_collapse_glyph(qtbot: QtBot) -> None:
    """Checking (expanding) swaps the glyph to collapse, and unchecking swaps back.

    **Test steps:**

    * build the toggle, check it and verify the collapse glyph
    * uncheck it and verify the expand glyph returns
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)

    toggle.setChecked(True)
    assert toggle.text() == COLLAPSE_ACTION_GLYPH.codepoint

    toggle.setChecked(False)
    assert toggle.text() == EXPAND_ACTION_GLYPH.codepoint


def test_is_square(qtbot: QtBot) -> None:
    """The toggle is fixed to a square size.

    **Test steps:**

    * build the toggle
    * verify its fixed width equals its fixed height
    """
    toggle = ExpandToggleButton()
    qtbot.addWidget(toggle)

    assert toggle.width() == toggle.height()
