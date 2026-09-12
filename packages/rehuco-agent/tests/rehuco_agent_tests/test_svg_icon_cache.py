"""Tests for the recolored-SVG icon cache (#248, lifted out of ``tasks`` for #266)."""

from typing import Any

from PySide6.QtGui import QColor
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent import svg_icon_cache
from rehuco_agent.svg_icon_cache import SvgIconCache

GLYPH = ":/icons/task_done.svg"
"""Any of the app's own glyphs; this cache neither knows nor cares which icons exist."""


@fixture
def cache(qapp: object) -> SvgIconCache:
    """A fresh cache; takes ``qapp`` because building an icon needs a `QGuiApplication`."""
    del qapp
    return SvgIconCache()


def test_the_same_glyph_and_color_is_built_once(cache: SvgIconCache, mocker: MockerFixture) -> None:
    """Recoloring rewrites an SVG and builds an icon engine, which must not happen per repaint.

    **Test steps:**

    * ask twice for the same glyph in the same color
    * verify the icon was built once and the same object came back
    """
    built = mocker.spy(svg_icon_cache, "recolored_svg_icon")
    path = GLYPH

    first = cache.icon(path, QColor("red"))
    second = cache.icon(path, QColor("red"))

    assert first is second
    built.assert_called_once()


def test_a_second_color_is_a_second_icon(cache: SvgIconCache) -> None:
    """A theme switch asks for colors not seen before rather than needing the cache told anything.

    **Test steps:**

    * ask for one glyph in two colors
    * verify the two are distinct icons
    """
    path = GLYPH

    assert cache.icon(path, QColor("red")) is not cache.icon(path, QColor("blue"))


def test_the_icon_renders_in_the_color_it_was_asked_for(cache: SvgIconCache) -> None:
    """The recoloring is real, not just a cache key.

    **Test steps:**

    * build a glyph in red and render it
    * verify red pixels came out
    """
    pixmap = cache.icon(GLYPH, QColor("red")).pixmap(32, 32)
    image = pixmap.toImage()
    colors: set[Any] = {image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())}

    assert "#ff0000" in colors
