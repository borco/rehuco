"""Tests for HorizontalLine: a QFrame configured as a sunken horizontal rule."""

from borco_pyside.widgets import HorizontalLine
from PySide6.QtWidgets import QFrame
from pytestqt.qtbot import QtBot


def test_is_shaped_as_a_sunken_horizontal_line(qtbot: QtBot) -> None:
    """The widget uses the ``HLine`` shape with a sunken shadow.

    **Test steps:**

    * build a HorizontalLine
    * verify its frame shape is ``HLine`` and its shadow is ``Sunken``
    """
    line = HorizontalLine()
    qtbot.addWidget(line)

    assert line.frameShape() == QFrame.Shape.HLine
    assert line.frameShadow() == QFrame.Shadow.Sunken
