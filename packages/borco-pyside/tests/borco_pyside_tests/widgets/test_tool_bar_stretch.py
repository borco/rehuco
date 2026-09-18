"""Tests for ToolBarStretch: an expanding widget standing in for a QToolBar stretch item."""

from borco_pyside.widgets import ToolBarStretch
from PySide6.QtWidgets import QSizePolicy
from pytestqt.qtbot import QtBot


def test_expands_in_both_directions(qtbot: QtBot) -> None:
    """The widget's size policy is ``Expanding`` on both axes, so it takes the spare room of a toolbar
    in either orientation.

    **Test steps:**

    * build a ToolBarStretch
    * verify both its horizontal and vertical policies are ``Expanding``
    """
    stretch = ToolBarStretch()
    qtbot.addWidget(stretch)

    assert stretch.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert stretch.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
