"""Tests for ActionIconThemeHandler."""

from collections.abc import Callable
from typing import Any

import pytest
from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.svg_recolor import recolored_svg_icon
from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
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


def test_the_single_icon_carries_both_state_variants(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """One ``QIcon`` holds both variants: unchecked (ButtonText) as ``Off``, checked as ``On``.

    Qt itself picks the variant from the action's checked state, so a state change that never emits
    ``toggled`` (a dock closed via its tab's ``[x]``, or ``CDockManager.restoreState()``) still
    shows the right colour -- this is the fix for the icon going white on such changes.

    **Test steps:**

    * construct a handler, then read the built icon's ``Off`` and ``On`` state pixmaps
    * verify ``Off`` renders in ButtonText and ``On`` in HighlightedText
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    off = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
    on = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.On)
    assert off.toImage().pixelColor(5, 5).name() == QApplication.palette().color(QPalette.ColorRole.ButtonText).name()
    assert (
        on.toImage().pixelColor(5, 5).name() == QApplication.palette().color(QPalette.ColorRole.HighlightedText).name()
    )


def test_the_single_icon_carries_a_disabled_variant_too(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """The built icon's ``Mode.Disabled`` variant is colored from the palette's own disabled group (#41).

    A custom icon engine gets no automatic disabled-greying from Qt -- without this, a disabled
    action's icon would render identically to its enabled one (the actual bug this closes).

    **Test steps:**

    * construct a handler, then read the built icon's ``Disabled`` pixmap
    * verify it renders in the palette's ``ColorGroup.Disabled`` ``ButtonText``, not the enabled one
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    disabled = icon.pixmap(QSize(10, 10), QIcon.Mode.Disabled, QIcon.State.Off)
    expected = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert disabled.toImage().pixelColor(5, 5).name() == expected.name()


def test_the_single_icon_carries_a_disabled_checked_variant_too(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The built icon's disabled+checked corner is colored from the ``Disabled`` group's ``HighlightedText`` (#41).

    Distinct from plain ``Mode.Disabled`` (``State.Off``) -- a disabled *checkable* action (e.g. one
    mirroring a model flag the user can't toggle directly) still needs to show checked-ness while
    disabled, not collapse to one flat disabled look.

    **Test steps:**

    * construct a handler, then read the built icon's disabled+checked pixmap
    * verify it renders in the palette's ``ColorGroup.Disabled`` ``HighlightedText``, distinct from
      plain disabled
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    disabled_checked = icon.pixmap(QSize(10, 10), QIcon.Mode.Disabled, QIcon.State.On)
    expected = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText)
    assert disabled_checked.toImage().pixelColor(5, 5).name() == expected.name()


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


def test_toggling_the_action_does_not_rebuild_the_icon(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Toggling the action never rebuilds the icon -- Qt picks the state variant from the one icon.

    **Test steps:**

    * mock QFile and spy on recolored_svg_icon
    * construct a checkable handler (builds the icon once), then check and uncheck the action
    * verify the builder never ran again after construction
    """
    mock_qfile(SVG)
    build_spy = mocker.patch(
        "borco_pyside.theming.action_icon_theme_handler.recolored_svg_icon",
        wraps=recolored_svg_icon,
    )
    make_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg")  # builds the icon (1)
    assert build_spy.call_count == 1

    make_action.setChecked(True)
    make_action.setChecked(False)

    assert build_spy.call_count == 1


def test_palette_change_rebuilds_both_variants(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """A real app-wide palette change rebuilds the icon (both variants) in the new colors.

    **Test steps:**

    * mock QFile and spy on recolored_svg_icon
    * construct a handler (builds the icon once)
    * change the app's palette for real (ButtonText to a new color)
    * verify the icon was rebuilt and the unchecked variant reflects the new color
    """
    mock_qfile(SVG)
    build_spy = mocker.patch(
        "borco_pyside.theming.action_icon_theme_handler.recolored_svg_icon",
        wraps=recolored_svg_icon,
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
        pixmap = make_action.icon().pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
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
