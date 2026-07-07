"""Tests for ThemeManager."""

from collections.abc import Callable
from typing import Any

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.theme_manager import ThemeManager
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture

SYSTEM_ICON = "system.svg"
LIGHT_ICON = "light.svg"
DARK_ICON = "dark.svg"

SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)


def test_starts_in_the_system_scheme_and_sets_the_system_icon(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """A freshly-constructed manager applies `Unknown` (follow-system) and the system icon.

    **Test steps:**

    * mock QFile and spy on ActionIconThemeHandler.set_icon and QStyleHints.setColorScheme
    * construct a ThemeManager
    * verify the scheme applied was Unknown and the icon built from the system icon path
    """
    mock_qfile(SVG)
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    set_icon_spy = mocker.spy(ActionIconThemeHandler, "set_icon")

    ThemeManager(make_action, SYSTEM_ICON, LIGHT_ICON, DARK_ICON)

    set_scheme.assert_called_once_with(Qt.ColorScheme.Unknown)
    set_icon_spy.assert_called_once_with(mocker.ANY, SYSTEM_ICON)
    assert not make_action.icon().isNull()


def test_clicking_cycles_system_light_dark_and_back_to_system(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Each click on the action advances Unknown -> Light -> Dark -> Unknown, applying each.

    **Test steps:**

    * mock QFile and spy on ActionIconThemeHandler.set_icon and QStyleHints.setColorScheme
    * construct a ThemeManager, then trigger the action three times
    * verify each trigger applied the next scheme and set the matching icon
    """
    mock_qfile(SVG)
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    set_icon_spy = mocker.spy(ActionIconThemeHandler, "set_icon")
    ThemeManager(make_action, SYSTEM_ICON, LIGHT_ICON, DARK_ICON)
    set_scheme.reset_mock()
    set_icon_spy.reset_mock()

    make_action.trigger()
    set_scheme.assert_called_once_with(Qt.ColorScheme.Light)
    set_icon_spy.assert_called_once_with(mocker.ANY, LIGHT_ICON)
    set_scheme.reset_mock()
    set_icon_spy.reset_mock()

    make_action.trigger()
    set_scheme.assert_called_once_with(Qt.ColorScheme.Dark)
    set_icon_spy.assert_called_once_with(mocker.ANY, DARK_ICON)
    set_scheme.reset_mock()
    set_icon_spy.reset_mock()

    make_action.trigger()
    set_scheme.assert_called_once_with(Qt.ColorScheme.Unknown)
    set_icon_spy.assert_called_once_with(mocker.ANY, SYSTEM_ICON)


def test_defaults_to_being_parented_to_the_action(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """With no explicit parent, the manager is parented to the action it manages.

    **Test steps:**

    * mock QFile
    * construct a ThemeManager with no `parent` argument
    * verify its Qt parent is the action
    """
    mock_qfile(SVG)

    manager = ThemeManager(make_action, SYSTEM_ICON, LIGHT_ICON, DARK_ICON)

    assert manager.parent() is make_action


def test_accepts_an_explicit_parent(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """An explicit `parent` argument overrides the default of parenting to the action.

    **Test steps:**

    * mock QFile
    * construct a ThemeManager with an explicit parent
    * verify its Qt parent is that object, not the action
    """
    mock_qfile(SVG)
    parent = QObject()

    manager = ThemeManager(make_action, SYSTEM_ICON, LIGHT_ICON, DARK_ICON, parent)

    assert manager.parent() is parent
