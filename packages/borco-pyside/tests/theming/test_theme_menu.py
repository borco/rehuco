"""Tests for ThemeMenu."""

from collections.abc import Callable
from typing import Any

from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.theme_menu import ThemeMenu
from borco_pyside.theming.theme_model import ThemeModel
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication
from pytest import fixture
from pytest_mock import MockerFixture

# mirrors test_theme_manager.py's own icon/SVG constants exactly -- kept as a separate copy rather
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


@fixture(autouse=True)
def mock_set_color_scheme(mocker: MockerFixture) -> None:
    """Prevent every ``ThemeModel`` built in this module from touching the real, process-wide
    ``QStyleHints`` scheme -- each test only cares about the model/menu's own state.
    """
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")


def test_checks_the_action_matching_the_models_current_mode_on_construction(
    mock_qfile: Callable[..., Any],
) -> None:
    """A freshly-constructed menu checks whichever action matches the model's already-current mode
    (``Unknown``, the model's own default here), leaving the other two unchecked.

    **Test steps:**

    * mock QFile and build a model
    * construct a ThemeMenu over it
    * verify only the default (follow-system) action is checked
    """
    mock_qfile(SVG)
    model = ThemeModel()

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert menu.default_action.isChecked()
    assert not menu.light_action.isChecked()
    assert not menu.dark_action.isChecked()


def test_starts_already_in_a_pinned_mode_checks_the_matching_action(mock_qfile: Callable[..., Any]) -> None:
    """A mode already active on the model before construction (e.g. a persisted choice restored on
    launch, or the toolbar's own pin) is reflected as the checked action, not overridden back to
    Default.

    **Test steps:**

    * mock QFile and build a model already in Dark
    * construct a ThemeMenu
    * verify only the dark action is checked
    """
    mock_qfile(SVG)
    model = ThemeModel(Qt.ColorScheme.Dark)

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert not menu.default_action.isChecked()
    assert not menu.light_action.isChecked()
    assert menu.dark_action.isChecked()


def test_triggering_an_action_applies_its_mode_to_the_model(mock_qfile: Callable[..., Any]) -> None:
    """Triggering ``light_action``/``dark_action`` sets the matching mode on the model.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeMenu over it
    * trigger the light action, then the dark action
    * verify the model's mode followed each trigger
    """
    mock_qfile(SVG)
    model = ThemeModel()
    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    menu.light_action.trigger()
    assert model.mode == Qt.ColorScheme.Light

    menu.dark_action.trigger()
    assert model.mode == Qt.ColorScheme.Dark


def test_triggering_an_action_unchecks_the_other_two(mock_qfile: Callable[..., Any]) -> None:
    """The three actions are mutually exclusive: checking one via the UI unchecks the other two.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeMenu over it
    * trigger the light action
    * verify it alone is checked
    """
    mock_qfile(SVG)
    model = ThemeModel()
    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    menu.light_action.trigger()

    assert not menu.default_action.isChecked()
    assert menu.light_action.isChecked()
    assert not menu.dark_action.isChecked()


def test_reacts_to_a_mode_change_made_elsewhere(mock_qfile: Callable[..., Any]) -> None:
    """A mode change driven by another control (e.g. the toolbar's cycling action, #57) is
    reflected on the checked action, without this menu's own actions ever being triggered.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeMenu over it
    * change the model's mode to Light, as if another control just applied it
    * verify the light action alone is now checked
    """
    mock_qfile(SVG)
    model = ThemeModel()
    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    model.mode = Qt.ColorScheme.Light

    assert not menu.default_action.isChecked()
    assert menu.light_action.isChecked()
    assert not menu.dark_action.isChecked()


def test_wires_a_flat_themed_icon_handler_per_action(mock_qfile: Callable[..., Any], mocker: MockerFixture) -> None:
    """Each action gets its own icon, kept themed via a ``flat`` ActionIconThemeHandler (#57) --
    ``flat`` since a plain checkmark, not a highlighted icon, communicates checked-ness in a menu.

    **Test steps:**

    * mock QFile and spy on ActionIconThemeHandler, wrapping the real class
    * build a model and construct a ThemeMenu over it
    * verify each action was wired with its own icon path and ``flat=True``, and got a real icon
    """
    mock_qfile(SVG)
    handler_spy = mocker.patch(
        "borco_pyside.theming.theme_menu.ActionIconThemeHandler", side_effect=ActionIconThemeHandler
    )
    model = ThemeModel()

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    called_icons = {call.args[0]: call.args[1] for call in handler_spy.call_args_list}
    assert called_icons == {
        menu.default_action: DEFAULT_ICON,
        menu.light_action: LIGHT_ICON,
        menu.dark_action: DARK_ICON,
    }
    for call in handler_spy.call_args_list:
        assert call.kwargs.get("flat") is True
    for action in (menu.default_action, menu.light_action, menu.dark_action):
        assert not action.icon().isNull()


def test_defaults_to_no_parent(mock_qfile: Callable[..., Any]) -> None:
    """With no explicit parent, the menu has none.

    **Test steps:**

    * mock QFile and build a model
    * construct a ThemeMenu with no `parent` argument
    * verify it has no Qt parent
    """
    mock_qfile(SVG)
    model = ThemeModel()

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert menu.parent() is None


def test_accepts_an_explicit_parent(mock_qfile: Callable[..., Any]) -> None:
    """An explicit `parent` argument parents the menu to it.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeMenu with an explicit parent
    * verify its Qt parent is that object
    """
    mock_qfile(SVG)
    model = ThemeModel()
    parent = QObject()

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON, parent)

    assert menu.parent() is parent


def test_the_three_actions_are_parented_to_the_menu(mock_qfile: Callable[..., Any]) -> None:
    """The three actions are parented to the menu itself, so Qt destroys them along with it.

    **Test steps:**

    * mock QFile, build a model, and construct a ThemeMenu
    * verify each action's Qt parent is the menu
    """
    mock_qfile(SVG)
    model = ThemeModel()

    menu = ThemeMenu(model, DEFAULT_ICON, LIGHT_ICON, DARK_ICON)

    assert menu.default_action.parent() is menu
    assert menu.light_action.parent() is menu
    assert menu.dark_action.parent() is menu
