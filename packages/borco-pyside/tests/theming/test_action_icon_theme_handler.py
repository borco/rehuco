"""Tests for ActionIconThemeHandler."""

from collections.abc import Callable
from typing import Any

import pytest
from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.svg_recolor import recolored_svg_icon
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture

SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)


def test_read_file_raises_when_the_file_cannot_be_opened(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """A path that fails to open raises, instead of silently building an icon from nothing.

    **Test steps:**

    * mock QFile.open to fail
    * construct an ActionIconThemeHandler for that path
    * verify RuntimeError is raised, naming the path
    """
    mock_qfile(SVG, open_ok=False)

    with pytest.raises(RuntimeError, match="missing.svg"):
        ActionIconThemeHandler(make_action, "missing.svg")


def test_construction_raises_without_a_running_qapplication(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Construction requires a running QApplication, to have somewhere to connect paletteChanged.

    **Test steps:**

    * mock QFile and QApplication.instance() to return None
    * construct an ActionIconThemeHandler
    * verify RuntimeError is raised
    """
    mock_qfile(SVG)
    mocker.patch("borco_pyside.theming.action_icon_theme_handler.QApplication.instance", return_value=None)

    with pytest.raises(RuntimeError, match="QApplication"):
        ActionIconThemeHandler(make_action, "icon.svg")


def test_construction_builds_the_unchecked_icon_from_button_text_color(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """A freshly-constructed handler immediately sets an icon colored for the unchecked state.

    **Test steps:**

    * mock QFile to return a real recolorable SVG
    * construct an ActionIconThemeHandler for a non-checkable action
    * verify the action's icon renders in the app palette's ButtonText color
    """
    mock_qfile(SVG)

    ActionIconThemeHandler(make_action, "icon.svg")

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_checking_the_action_recolors_the_icon_to_the_highlighted_text_color(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """Checking a checkable action switches its icon to the HighlightedText-colored variant.

    **Test steps:**

    * mock QFile to return a real recolorable SVG
    * construct an ActionIconThemeHandler for a checkable action
    * check the action
    * verify the icon now renders in the app palette's HighlightedText color
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg")

    make_action.setChecked(True)

    expected = QApplication.palette().color(QPalette.ColorRole.HighlightedText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_set_icon_switches_the_source_svg_and_keeps_it_themed(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """set_icon swaps the source SVG, rebuilding the icon in the current theme's color.

    **Test steps:**

    * mock QFile to return one SVG, then a second, differently-shaped one
    * construct a handler, then call set_icon with a new path
    * verify the new icon still renders in the app palette's ButtonText color
    """
    mock_qfile(SVG)
    handler = ActionIconThemeHandler(make_action, "icon.svg")

    other_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        b'<circle cx="5" cy="5" r="5" style="fill:rgb(0,0,0)"/></svg>'
    )
    mock_qfile(other_svg)

    handler.set_icon("other.svg")

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_refresh_rebuilds_the_icon_for_a_checked_state_changed_without_toggled(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """refresh() rebuilds the icon for the action's current checked state, even when nothing ever
    emitted `toggled` for it (confirmed: `CDockManager.restoreState()` can flip a dock's
    `toggleViewAction()` this way, silently, without the signal).

    **Test steps:**

    * mock QFile, make the action checkable, construct a handler (builds the unchecked icon)
    * flip checked without emitting toggled (blockSignals), simulating a silent external change
    * call refresh()
    * verify the icon now renders in the app palette's HighlightedText color
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    handler = ActionIconThemeHandler(make_action, "icon.svg")

    make_action.blockSignals(True)
    make_action.setChecked(True)
    make_action.blockSignals(False)

    handler.refresh()

    expected = QApplication.palette().color(QPalette.ColorRole.HighlightedText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_toggling_back_reuses_the_previously_cached_icon(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Returning to a checked state already built once reuses its cached icon, without rebuilding.

    **Test steps:**

    * mock QFile and spy on recolored_svg_icon
    * construct a handler, then check then uncheck the action
    * verify the icon builder ran exactly twice (once per distinct state), not three times
    """
    mock_qfile(SVG)
    build_spy = mocker.patch(
        "borco_pyside.theming.action_icon_theme_handler.recolored_svg_icon", wraps=recolored_svg_icon
    )
    make_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg")  # builds unchecked (1)

    make_action.setChecked(True)  # builds checked (2)
    make_action.setChecked(False)  # unchecked already cached -- no rebuild

    assert build_spy.call_count == 2


def test_palette_change_clears_the_cache_and_rebuilds_the_icon(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """A real app-wide palette change invalidates every cached icon and rebuilds the current one.

    **Test steps:**

    * mock QFile and spy on recolored_svg_icon
    * construct a handler (builds once)
    * change the app's palette for real (ButtonText to a new color)
    * verify the icon builder ran again, and the icon now reflects the new color
    """
    mock_qfile(SVG)
    build_spy = mocker.patch(
        "borco_pyside.theming.action_icon_theme_handler.recolored_svg_icon", wraps=recolored_svg_icon
    )
    ActionIconThemeHandler(make_action, "icon.svg")
    assert build_spy.call_count == 1

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = app.palette()
    try:
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("lime"))
        app.setPalette(palette)

        assert build_spy.call_count == 2
        pixmap = make_action.icon().pixmap(10, 10)
        assert pixmap.toImage().pixelColor(5, 5).name() == "#00ff00"
    finally:
        app.setPalette(original_palette)


def test_defaults_to_being_parented_to_the_action(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """With no explicit parent, the handler is parented to the action it manages.

    **Test steps:**

    * mock QFile
    * construct a handler with no `parent` argument
    * verify its Qt parent is the action
    """
    mock_qfile(SVG)

    handler = ActionIconThemeHandler(make_action, "icon.svg")

    assert handler.parent() is make_action


def test_accepts_an_explicit_parent(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """An explicit `parent` argument overrides the default of parenting to the action.

    **Test steps:**

    * mock QFile
    * construct a handler with an explicit parent
    * verify its Qt parent is that object, not the action
    """
    mock_qfile(SVG)
    parent = QObject()

    handler = ActionIconThemeHandler(make_action, "icon.svg", parent)

    assert handler.parent() is parent
