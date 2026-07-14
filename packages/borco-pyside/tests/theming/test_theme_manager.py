"""Tests for ThemeManager."""

from collections.abc import Callable
from typing import Any

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.theme_manager import ThemeManager
from borco_pyside.theming.theme_model import ThemeModel
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture

# mirrors test_theme_menu.py's own icon/SVG constants exactly -- kept as a separate copy rather
# than a shared import, since the two test modules are otherwise unrelated.
# pylint: disable=duplicate-code
DEFAULT_ICON = "default.svg"
LIGHT_ICON = "light.svg"
DARK_ICON = "dark.svg"

SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)
# pylint: enable=duplicate-code


def test_starts_in_the_models_current_mode_and_sets_the_matching_icon(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """A freshly-constructed manager reflects the model's already-current mode on the icon, without
    changing the model itself.

    **Test steps:**

    * mock QFile, build a model already in Dark, and spy on set_icon
    * construct a ThemeManager over that model
    * verify the model's mode was left alone, and the icon matches Dark
    """
    mock_qfile(SVG)
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel(Qt.ColorScheme.Dark)
    set_icon_spy = mocker.spy(ActionIconThemeHandler, "set_icon")

    ThemeManager(model, make_action, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert model.mode == Qt.ColorScheme.Dark
    set_icon_spy.assert_called_once_with(mocker.ANY, DARK_ICON)
    assert not make_action.icon().isNull()


def test_clicking_cycles_system_light_dark_and_back_to_system(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Each click on the action advances the model's mode Unknown -> Light -> Dark -> Unknown.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeManager over it
    * trigger the action three times
    * verify the model's mode advanced through the cycle each time
    """
    mock_qfile(SVG)
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel()
    ThemeManager(model, make_action, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    make_action.trigger()
    assert model.mode == Qt.ColorScheme.Light

    make_action.trigger()
    assert model.mode == Qt.ColorScheme.Dark

    make_action.trigger()
    assert model.mode == Qt.ColorScheme.Unknown


def test_reacts_to_a_mode_change_made_elsewhere(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """A mode change driven by another control (e.g. a `View` menu's theme entries, #57) is
    reflected on the icon, without this manager's own action ever being triggered.

    **Test steps:**

    * mock QFile, construct a ThemeManager over a shared model, then spy on set_icon
    * change the model's mode to Dark, as if another control just applied it
    * verify the icon was rebuilt for Dark
    """
    mock_qfile(SVG)
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel()
    ThemeManager(model, make_action, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)
    set_icon_spy = mocker.spy(ActionIconThemeHandler, "set_icon")

    model.mode = Qt.ColorScheme.Dark

    set_icon_spy.assert_called_once_with(mocker.ANY, DARK_ICON)


def test_defaults_to_being_parented_to_the_action(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """With no explicit parent, the manager is parented to the action it manages.

    **Test steps:**

    * mock QFile and QStyleHints.setColorScheme
    * construct a ThemeManager with no `parent` argument
    * verify its Qt parent is the action
    """
    mock_qfile(SVG)
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel()

    manager = ThemeManager(model, make_action, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert manager.parent() is make_action


def test_accepts_an_explicit_parent(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """An explicit `parent` argument overrides the default of parenting to the action.

    **Test steps:**

    * mock QFile and QStyleHints.setColorScheme
    * construct a ThemeManager with an explicit parent
    * verify its Qt parent is that object, not the action
    """
    mock_qfile(SVG)
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel()
    parent = QObject()

    manager = ThemeManager(model, make_action, DEFAULT_ICON, LIGHT_ICON, DARK_ICON, parent)

    assert manager.parent() is parent
