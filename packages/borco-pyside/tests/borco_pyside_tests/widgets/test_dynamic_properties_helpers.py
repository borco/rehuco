"""Tests for dynamic_properties_helpers: toggling a QSS-selector-driving dynamic property on a widget."""

from borco_pyside.widgets.dynamic_properties_helpers import toggle_dynamic_property
from PySide6.QtWidgets import QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


def test_toggle_dynamic_property_sets_the_property_and_repolishes(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Changing the property value sets it and re-polishes the widget.

    **Test steps:**

    * spy on the widget's style
    * call ``toggle_dynamic_property`` with a new value
    * verify the property is set and ``unpolish``/``polish`` were both called
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    unpolish = mocker.spy(widget.style(), "unpolish")
    polish = mocker.spy(widget.style(), "polish")

    toggle_dynamic_property(widget, "warning", True)

    assert widget.property("warning") is True
    unpolish.assert_called_once_with(widget)
    polish.assert_called_once_with(widget)


def test_toggle_dynamic_property_is_a_no_op_when_unchanged(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Setting the same value again does not repolish the widget.

    **Test steps:**

    * set the property once
    * spy on the widget's style, then call ``toggle_dynamic_property`` again with the same value
    * verify neither ``unpolish`` nor ``polish`` was called
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    toggle_dynamic_property(widget, "warning", True)
    unpolish = mocker.spy(widget.style(), "unpolish")
    polish = mocker.spy(widget.style(), "polish")

    toggle_dynamic_property(widget, "warning", True)

    unpolish.assert_not_called()
    polish.assert_not_called()
