"""Tests for ThemedIcons and the palette-resolving icon engines."""

from collections.abc import Callable
from typing import Any

from borco_pyside.theming.themed_icons import PaletteSvgIconEngine, ThemedIcons, themed_glyph_icon, themed_svg_icon
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication
from pytest import raises
from pytest_mock import MockerFixture

SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)

STAR_GLYPH = ""
"""Phosphor's "star" glyph -- a real, solid icon shape guaranteed present in the loaded test font."""


def test_the_same_source_returns_the_very_same_icon(mock_qfile: Callable[..., Any]) -> None:
    """Two requests for one source path hand back a single shared ``QIcon``.

    **Test steps:**

    * request the same path twice
    * verify both requests returned the same icon
    """
    mock_qfile(SVG)

    first = themed_svg_icon("icon.svg")
    second = themed_svg_icon("icon.svg")

    assert first.cacheKey() == second.cacheKey()


def test_the_flat_variant_is_a_separate_icon(mock_qfile: Callable[..., Any]) -> None:
    """``flat`` is part of the cache key, so a menu row's icon is not served to a toolbar button.

    **Test steps:**

    * request the same path both flat and not
    * verify they are different icons
    """
    mock_qfile(SVG)

    assert themed_svg_icon("icon.svg").cacheKey() != themed_svg_icon("icon.svg", flat=True).cacheKey()


def test_the_flat_variant_draws_the_checked_state_in_the_unchecked_color(
    mock_qfile: Callable[..., Any],
) -> None:
    """A flat icon's checked corner keeps ``ButtonText``, with no checked color of its own.

    A menu row paints no filled chrome behind its icon, so there is nothing for a checked color to
    contrast against; its own native checkmark communicates checked-ness instead.

    **Test steps:**

    * build a flat icon and read both state corners
    * verify both render in ``ButtonText``
    """
    mock_qfile(SVG)

    icon = themed_svg_icon("icon.svg", flat=True)

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText).name()
    for state in (QIcon.State.Off, QIcon.State.On):
        pixmap = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, state)
        assert pixmap.toImage().pixelColor(5, 5).name() == expected


def test_an_icon_recolors_itself_when_the_palette_changes(mock_qfile: Callable[..., Any]) -> None:
    """One icon, unrebuilt and unnotified, renders in whichever color the palette currently holds.

    This is the property the whole module exists for: a glyph's color is computed as it paints, so it
    cannot be left stale by a signal that failed to arrive (#304).

    **Test steps:**

    * build an icon and render it
    * change the app's palette for real, touching nothing else
    * render the same icon again and verify the color changed with the palette
    """
    mock_qfile(SVG)
    icon = themed_svg_icon("icon.svg")

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original = app.palette()
    try:
        palette = QPalette(original)
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("lime"))
        app.setPalette(palette)

        pixmap = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
        assert pixmap.toImage().pixelColor(5, 5).name() == "#00ff00"
    finally:
        app.setPalette(original)


def test_a_glyph_icon_is_shared_and_follows_the_palette_too(real_font_family: str) -> None:
    """The glyph icons are cached and palette-resolved on exactly the same terms as the SVG ones.

    **Test steps:**

    * request the same glyph twice and verify one shared icon came back
    * change the app's palette and verify the glyph renders in the new color
    """
    role = QPalette.ColorRole.ButtonText
    icon = themed_glyph_icon(STAR_GLYPH, real_font_family, role)

    assert icon.cacheKey() == themed_glyph_icon(STAR_GLYPH, real_font_family, role).cacheKey()

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original = app.palette()
    try:
        palette = QPalette(original)
        palette.setColor(role, QColor("lime"))
        app.setPalette(palette)

        assert icon.pixmap(16, 16).toImage().pixelColor(8, 8).name() == "#00ff00"
    finally:
        app.setPalette(original)


def test_a_source_that_cannot_be_read_raises(mock_qfile: Callable[..., Any]) -> None:
    """An unreadable path raises, instead of silently caching an icon built from nothing.

    **Test steps:**

    * mock QFile.open to fail
    * request the icon
    * verify RuntimeError is raised, naming the path
    """
    mock_qfile(SVG, open_ok=False)

    with raises(RuntimeError, match="missing.svg"):
        themed_svg_icon("missing.svg")


def test_requesting_an_icon_without_a_running_qapplication_raises(mocker: MockerFixture) -> None:
    """There is no application to hang the cache off, so the request raises rather than leaking one.

    **Test steps:**

    * mock QApplication.instance() to return None
    * request an icon
    * verify RuntimeError is raised
    """
    mocker.patch("borco_pyside.theming.themed_icons.QApplication.instance", return_value=None)

    with raises(RuntimeError, match="QApplication"):
        themed_svg_icon("icon.svg")


def test_one_cache_is_shared_by_every_caller() -> None:
    """``for_application`` hands back the one cache parented to the application, never a second.

    **Test steps:**

    * ask for the application's cache twice
    * verify the same object came back, parented to the application
    """
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    cache = ThemedIcons.for_application(app)

    assert ThemedIcons.for_application(app) is cache
    assert cache.parent() is app


def test_a_cloned_engine_keeps_the_source_and_the_flat_variant() -> None:
    """``clone()`` yields an independent engine over the same SVG that still honors ``flat``.

    Qt clones an icon's engine when a ``QIcon`` copy is detached, so a clone that dropped either
    the source or the variant would silently change how a copied icon draws.

    **Test steps:**

    * clone a flat engine and wrap the clone in its own ``QIcon``
    * verify the clone is a distinct engine of the same kind
    * verify its checked corner still renders in ``ButtonText`` -- the flat variant survived
    """
    engine = PaletteSvgIconEngine(SVG, flat=True)

    clone = engine.clone()
    icon = QIcon(clone)

    assert isinstance(clone, PaletteSvgIconEngine)
    assert clone is not engine
    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText).name()
    pixmap = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.On)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected


def test_requesting_a_glyph_icon_without_a_running_qapplication_raises(mocker: MockerFixture) -> None:
    """The glyph entry point guards the missing application the same way the SVG one does.

    **Test steps:**

    * mock QApplication.instance() to return None
    * request a glyph icon
    * verify RuntimeError is raised
    """
    mocker.patch("borco_pyside.theming.themed_icons.QApplication.instance", return_value=None)

    with raises(RuntimeError, match="QApplication"):
        themed_glyph_icon(STAR_GLYPH, "", QPalette.ColorRole.Text)
