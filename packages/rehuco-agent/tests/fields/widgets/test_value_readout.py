"""Tests for ValueReadout: the framed, read-only number both measure rows show a measurement in."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.value_readout import ValueReadout


def test_a_readout_is_framed_so_an_empty_one_is_still_visible(qtbot: QtBot) -> None:
    """The border is the whole point: a computed readout is empty until Compute is pressed, and an
    unframed empty label reads as a missing widget rather than as one waiting for an answer.

    **Test steps:**

    * build a readout and leave it empty, as it is before any measurement
    * verify it carries a frame
    """
    readout = ValueReadout("what this shows")
    qtbot.addWidget(readout)

    assert readout.text() == ""
    assert readout.frameShape() == QFrame.Shape.StyledPanel


def test_a_readout_is_selectable_but_not_editable(qtbot: QtBot) -> None:
    """A reading of a value, never a second place to enter one -- and selectable, so an exact byte count
    can be copied out to somewhere it can be compared.

    **Test steps:**

    * build a readout
    * verify its text is selectable by mouse and by nothing else
    """
    readout = ValueReadout("what this shows")
    qtbot.addWidget(readout)

    assert readout.textInteractionFlags() == Qt.TextInteractionFlag.TextSelectableByMouse


def test_a_readout_names_what_it_shows(qtbot: QtBot) -> None:
    """It carries no label of its own, so the tooltip is what says which number it is.

    **Test steps:**

    * build a readout with a tooltip
    * verify the tooltip is the one given
    """
    readout = ValueReadout("The measured size, in bytes")
    qtbot.addWidget(readout)

    assert readout.toolTip() == "The measured size, in bytes"
